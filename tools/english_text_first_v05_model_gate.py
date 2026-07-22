from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path


def load_packet_jobs(input_root: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for doc_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
        packet_path = doc_dir / "question_packet_candidates.json"
        node_path = doc_dir / "semantic_nodes.json"
        asset_path = doc_dir / "asset_manifest.json"
        if not packet_path.exists():
            continue
        packet_payload = read_json(packet_path)
        semantic_payload = read_json(node_path) if node_path.exists() else {"semantic_nodes": []}
        asset_payload = read_json(asset_path) if asset_path.exists() else {"assets": []}
        nodes_by_unit = {
            str(node.get("source_unit_id", "") or ""): node
            for node in semantic_payload.get("semantic_nodes", [])
        }
        for packet in packet_payload.get("packets", []):
            unit_id = str(packet.get("source_unit_id", "") or "")
            jobs.append(
                {
                    "doc_id": doc_dir.name,
                    "packet_id": packet.get("packet_id"),
                    "packet": packet,
                    "source_node": nodes_by_unit.get(unit_id, {}),
                    "asset_manifest_excerpt": [
                        asset
                        for asset in asset_payload.get("assets", [])
                        if str(asset.get("parent_hint", "") or "") == unit_id
                        or str(asset.get("unit_id", "") or "") == unit_id
                    ],
                }
            )
    return jobs


def compact_job(job: dict[str, Any]) -> dict[str, Any]:
    packet = job["packet"]
    exact = packet.get("source_text_exact", {})
    return {
        "doc_id": job["doc_id"],
        "packet_id": packet.get("packet_id"),
        "packet_family": packet.get("packet_family"),
        "current_local_status": packet.get("release_status"),
        "current_local_hold_reasons": packet.get("hold_reasons", []),
        "title": packet.get("title", ""),
        "source_text_exact": {
            "passage": str(exact.get("passage", "") or "")[:5000],
            "stem": str(exact.get("stem", "") or "")[:5000],
            "solution": str(exact.get("solution", "") or "")[:5000],
        },
        "evidence": packet.get("evidence", {}),
        "related_assets": packet.get("related_assets", []),
        "source_node": job.get("source_node", {}),
        "asset_manifest_excerpt": job.get("asset_manifest_excerpt", []),
    }


def system_prompt() -> str:
    return """You are the QA Gate for an English image-PDF text-first ingest pipeline.

Your only job is to review one QuestionPacket candidate.

Rules:
- Do not rewrite, polish, summarize, translate, or add content.
- Judge whether the candidate can proceed as a production-ready candidate.
- Every useful field must be backed by source_text_exact and evidence refs.
- If a required teacher solution, analysis, translation, passage, or visual/writing surface is missing or only rough, return HOLD.
- For writing tasks, a writing surface/review table is required and rough bbox assets are HOLD.
- For embedded grammar checks inside a knowledge block, HOLD unless parent knowledge relation is explicit.
- Return JSON only.
"""


def user_prompt(job: dict[str, Any]) -> str:
    schema = {
        "packet_id": "string",
        "model_status": "READY or HOLD",
        "model_hold_reasons": ["short reason strings"],
        "source_fidelity": "PASS or HOLD",
        "evidence_coverage": "PASS or HOLD",
        "visual_asset_status": "PASS or HOLD or NOT_REQUIRED",
        "notes": "short Chinese note",
    }
    return json.dumps(
        {
            "task": "Review this exact-source QuestionPacket candidate. Return JSON matching output_schema.",
            "output_schema": schema,
            "candidate": compact_job(job),
        },
        ensure_ascii=False,
        indent=2,
    )


def parse_model_json(text: str) -> tuple[dict[str, Any] | None, str]:
    cleaned = text.strip()
    try:
        return json.loads(cleaned), ""
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1]), ""
            except json.JSONDecodeError as exc:
                return None, str(exc)
        return None, "model_output_not_json"


def call_model(job: dict[str, Any], *, api_key: str, model: str, timeout: int, retries: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": user_prompt(job)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    last_error = ""
    started = time.time()
    for attempt in range(1, retries + 2):
        try:
            response = requests.post(ARK_API_URL, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            raw = response.json()
            content = str(raw["choices"][0]["message"]["content"])
            parsed, parse_error = parse_model_json(content)
            if parsed is None:
                last_error = parse_error
                continue
            return {
                "packet_id": job["packet_id"],
                "doc_id": job["doc_id"],
                "called": True,
                "attempts": attempt,
                "latency_seconds": round(time.time() - started, 3),
                "model": model,
                "parsed": True,
                "model_result": parsed,
                "usage": raw.get("usage", {}),
            }
        except Exception as exc:  # noqa: BLE001 - persisted as model-call evidence
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 * attempt, 6))
    return {
        "packet_id": job["packet_id"],
        "doc_id": job["doc_id"],
        "called": True,
        "attempts": retries + 1,
        "latency_seconds": round(time.time() - started, 3),
        "model": model,
        "parsed": False,
        "error": last_error,
        "model_result": {
            "packet_id": job["packet_id"],
            "model_status": "HOLD",
            "model_hold_reasons": ["model_gate_call_failed"],
            "source_fidelity": "HOLD",
            "evidence_coverage": "HOLD",
            "visual_asset_status": "HOLD",
            "notes": "模型门闸调用或解析失败，保守 HOLD。",
        },
    }


def merge_model_gate(input_root: Path, model_results: list[dict[str, Any]], out_root: Path) -> dict[str, Any]:
    result_by_packet = {str(item.get("packet_id", "")): item for item in model_results}
    docs: dict[str, Any] = {}
    for doc_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
        packet_path = doc_dir / "question_packet_candidates.json"
        if not packet_path.exists():
            continue
        payload = read_json(packet_path)
        merged_packets = []
        ready = 0
        hold = 0
        for packet in payload.get("packets", []):
            model_call = result_by_packet.get(str(packet.get("packet_id", "")), {})
            model_result = model_call.get("model_result", {})
            local_status = packet.get("release_status")
            model_status = model_result.get("model_status", "HOLD")
            final_status = "READY" if local_status == "READY" and model_status == "READY" else "HOLD"
            if final_status == "READY":
                ready += 1
            else:
                hold += 1
            merged = dict(packet)
            merged["model_gate"] = model_call
            merged["final_status"] = final_status
            merged["final_hold_reasons"] = list(packet.get("hold_reasons", [])) + list(
                model_result.get("model_hold_reasons", []) or []
            )
            merged_packets.append(merged)
        doc_payload = {
            "schema": "english_text_first_v05.model_gated_question_packet_candidates",
            "doc_id": doc_dir.name,
            "packet_count": len(merged_packets),
            "final_ready_count": ready,
            "final_hold_count": hold,
            "packets": merged_packets,
        }
        docs[doc_dir.name] = {
            "packet_count": len(merged_packets),
            "final_ready_count": ready,
            "final_hold_count": hold,
        }
        write_json(out_root / doc_dir.name / "model_gated_question_packet_candidates.json", doc_payload)
    return docs


def run_model_gate(args: argparse.Namespace) -> dict[str, Any]:
    input_root = workspace_path(args.input)
    out_root = workspace_path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    jobs = load_packet_jobs(input_root)
    api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing_ark_api_key")

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as executor:
        futures = [
            executor.submit(
                call_model,
                job,
                api_key=api_key,
                model=args.model,
                timeout=int(args.timeout),
                retries=int(args.retries),
            )
            for job in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: (str(item.get("doc_id", "")), str(item.get("packet_id", ""))))
    write_json(out_root / "model_gate_calls.json", {"schema": "english_text_first_v05.model_gate_calls", "calls": results})
    docs = merge_model_gate(input_root, results, out_root)
    summary = {
        "schema": "english_text_first_v05.model_gate_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_root": str(input_root),
        "out_root": str(out_root),
        "model": args.model,
        "model_calls": len(results),
        "parsed_calls": sum(1 for item in results if item.get("parsed")),
        "failed_calls": sum(1 for item in results if not item.get("parsed")),
        "docs": docs,
    }
    write_json(out_root / "model_gate_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run model-in-loop QA gate over English text-first v0.5 candidates.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run_model_gate(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
