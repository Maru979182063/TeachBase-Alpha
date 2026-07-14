from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.docx_native_config_v01 import load_config, nested_get, workspace_path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_json_block(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("empty_model_response")
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            return json.loads(clean[start : end + 1])
        raise


def build_prompt(task: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Refine DOCX-native math Markdown into storage-safe canonical blocks.",
            "rules": [
                "Return JSON only. Do not use markdown fences.",
                "Do not remove native image Markdown or image paths.",
                "Do not invent content that is not present in input_markdown or OMML candidates.",
                "Preserve Chinese prose and visible labels such as 【答案】, 【分析】, 【详解】.",
                "Normalize condition groups into canonical condition_group blocks.",
                "For each condition group, keep each condition as a separate item; do not flatten into one inline formula.",
                "Use $...$ for inline math and :::condition-group blocks for condition groups.",
            ],
            "output_schema": {
                "question_id": "string",
                "status": "ok|needs_human_review|failed",
                "refined_markdown": "string",
                "condition_groups": [
                    {
                        "formula_id": "string",
                        "items": ["string"],
                        "markdown": ":::condition-group source=formula_id\\n- $...$\\n:::",
                    }
                ],
                "review_flags": ["string"],
                "notes": "short Chinese note",
            },
            "input": task,
        },
        ensure_ascii=False,
        indent=2,
    )


def call_ark_chat(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict K12 math content normalization worker. "
                    "You preserve source content and return valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    return {
        "raw_response": data,
        "raw_content": content,
        "parsed": extract_json_block(content),
    }


def load_prompt_pack(ingest_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    prompt_pack_name = str(nested_get(config, "contracts.prompt_pack", "model_refine_prompt_pack.json"))
    return read_json(ingest_dir / prompt_pack_name)


def merge_refined_packets(ingest_dir: Path, out_dir: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    packets_path = ingest_dir / "question_packets_backend_preview.json"
    if not packets_path.exists():
        return {"status": "skipped", "reason": "question_packets_missing"}
    packets = read_json(packets_path)
    by_question = {
        record["question_id"]: record["parsed"]
        for record in records
        if record.get("status") == "ok" and isinstance(record.get("parsed"), dict)
    }
    refined_count = 0
    for question in packets.get("questions", []):
        parsed = by_question.get(question.get("question_id", ""))
        if not parsed:
            continue
        question["model_refine"] = {
            "status": parsed.get("status", "ok"),
            "model_refined_markdown": parsed.get("refined_markdown", ""),
            "condition_groups": parsed.get("condition_groups", []),
            "review_flags": parsed.get("review_flags", []),
            "notes": parsed.get("notes", ""),
        }
        if parsed.get("refined_markdown"):
            question["display_markdown_model_refined"] = parsed["refined_markdown"]
        refined_count += 1
    out_path = out_dir / "question_packets_model_refined_preview.json"
    write_json(out_path, packets)
    return {"status": "ok", "refined_count": refined_count, "path": str(out_path)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    config, config_path = load_config(args.config)
    ingest_dir = args.ingest_dir
    if ingest_dir is None:
        raise SystemExit("missing_ingest_dir")
    if not ingest_dir.is_absolute():
        ingest_dir = workspace_path(ingest_dir)
    output_dir_name = str(nested_get(config, "model_refine.output_dir_name", "model_refine_doubao2_0_mini_v01"))
    out_dir = args.out if args.out else ingest_dir / output_dir_name
    if not out_dir.is_absolute():
        out_dir = workspace_path(out_dir)

    endpoint = str(nested_get(config, "model_refine.endpoint", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"))
    model = args.model or str(nested_get(config, "model_refine.model", "doubao-seed-2.0-mini"))
    api_key_env = str(nested_get(config, "model_refine.api_key_env", "ARK_API_KEY"))
    api_key = args.api_key or os.environ.get(api_key_env, "")
    temperature = float(args.temperature if args.temperature is not None else nested_get(config, "model_refine.temperature", 0.1))
    max_tokens = int(args.max_tokens if args.max_tokens is not None else nested_get(config, "model_refine.max_tokens", 4096))
    timeout_seconds = int(nested_get(config, "model_refine.timeout_seconds", 120) or 120)
    retry_count = int(nested_get(config, "model_refine.retry_count", 2) or 2)
    default_limit = int(nested_get(config, "model_refine.default_limit", 3) or 3)
    limit = args.limit if args.limit is not None else default_limit

    prompt_pack = load_prompt_pack(ingest_dir, config)
    tasks = list(prompt_pack.get("tasks", []))
    if limit and limit > 0:
        tasks = tasks[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if not api_key and not args.prepare_only:
        summary = {
            "schema_version": "docx_native_model_refine_summary.v0.1",
            "status": "blocked",
            "reason": "missing_api_key",
            "api_key_env": api_key_env,
            "model": model,
            "task_count": len(tasks),
            "out_dir": str(out_dir),
            "loaded_config_path": str(config_path),
            "no_runtime_import": True,
            "no_database_write": True,
        }
        write_json(out_dir / "model_refine_summary.json", summary)
        return summary

    for index, task in enumerate(tasks, start=1):
        started = time.time()
        question_id = str(task.get("question_id", ""))
        prompt = build_prompt(task)
        prompt_path = out_dir / "prompts" / f"{question_id or index:03}.prompt.json"
        write_json(prompt_path, {"question_id": question_id, "prompt": prompt})
        record: dict[str, Any] = {
            "question_id": question_id,
            "index": index,
            "status": "prepared" if args.prepare_only else "failed",
            "prompt_path": str(prompt_path),
            "model": model,
            "started_at": now_iso(),
        }
        if args.prepare_only:
            record["latency_seconds"] = round(time.time() - started, 3)
            records.append(record)
            append_jsonl(out_dir / "model_refine_records.jsonl", record)
            continue
        last_error = ""
        for attempt in range(1, retry_count + 2):
            try:
                result = call_ark_chat(
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                )
                parsed = result["parsed"]
                record.update(
                    {
                        "status": "ok" if parsed.get("status") in {"ok", "needs_human_review"} else "failed",
                        "parsed": parsed,
                        "raw_content": result["raw_content"],
                        "usage": result["raw_response"].get("usage", {}),
                        "attempt": attempt,
                    }
                )
                break
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, KeyError) as exc:
                last_error = str(exc)
                record["error"] = last_error[:500]
                record["attempt"] = attempt
                if attempt <= retry_count:
                    time.sleep(min(2 * attempt, 8))
        record["latency_seconds"] = round(time.time() - started, 3)
        records.append(record)
        write_json(out_dir / "records" / f"{question_id or index:03}.json", record)
        append_jsonl(out_dir / "model_refine_records.jsonl", record)

    merge_result = merge_refined_packets(ingest_dir, out_dir, records)
    status_counts: dict[str, int] = {}
    for record in records:
        status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
    summary = {
        "schema_version": "docx_native_model_refine_summary.v0.1",
        "status": "ok" if status_counts.get("ok", 0) == len(records) else "partial",
        "model": model,
        "provider": str(nested_get(config, "model_refine.provider", "volcengine_ark")),
        "endpoint": endpoint,
        "api_key_env": api_key_env,
        "task_count": len(tasks),
        "status_counts": status_counts,
        "out_dir": str(out_dir),
        "loaded_config_path": str(config_path),
        "merge_result": merge_result,
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "model_refine_summary.json", summary)
    write_json(out_dir / "model_refine_records.json", {"records": records})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="DOCX-native condition-group model refine worker v0.1")
    parser.add_argument("--config", default="")
    parser.add_argument("--ingest-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--prepare-only", action="store_true")
    summary = run(parser.parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
