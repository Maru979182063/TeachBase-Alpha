from __future__ import annotations

import argparse
import base64
import concurrent.futures
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
TARGET_STATUSES = {"READY", "READY_WITH_LOSS", "NEEDS_REVIEW", "UNSUPPORTED", "BLOCKED"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = text.strip()
    try:
        return json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def compact_blocks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for region in doc["source_evidence"]["regions"]:
        blocks.append(
            {
                "line_ref": region["line_ref"],
                "page": region["page_number"],
                "label": region.get("label", ""),
                "text": region.get("text", ""),
                "coordinate_status": region.get("coordinate_status", ""),
            }
        )
    return blocks


def compact_units(doc: dict[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for obj in doc["semantic_objects"]:
        raw = obj.get("raw_unit")
        if not raw:
            continue
        units.append(
            {
                "unit_id": raw.get("unit_id"),
                "observation_label": obj.get("observations", [{}])[0].get("label", ""),
                "title": raw.get("title", ""),
                "source_refs": raw.get("source_refs", []),
                "visual_refs": raw.get("visual_refs", []),
                "role_tags": raw.get("role_tags", []),
                "facets": raw.get("facets", []),
                "relation_to_parent": raw.get("relation_to_parent", ""),
                "parent_hint": raw.get("parent_hint", ""),
                "completeness": raw.get("completeness", ""),
            }
        )
    return units


def targets_for_doc(human_review: dict[str, Any], doc_id: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for item in human_review.get("packets", []):
        if item.get("doc_id") != doc_id:
            continue
        packet_id = str(item.get("packet_id", ""))
        source_unit_id = packet_id.split(f"{doc_id}_", 1)[-1] if packet_id.startswith(f"{doc_id}_") else ""
        targets.append({"packet_id": packet_id, "source_unit_id": source_unit_id})
    return targets


def doc_page_images(doc: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for page in doc["source_evidence"]["pages"]:
        value = str(page.get("image_path", "") or "")
        path = workspace_path(value) if value else Path()
        if path.exists():
            paths.append(path)
    return paths


def system_prompt() -> str:
    return """You are a semantic graph reviewer for an English image-PDF ingest rescue pipeline.

Your job:
- Review one 8-page teacher handout using the page images and full transcription/units.
- Decide whether each target observed unit can be projected to the current Runtime target.
- Do not create QuestionPacket text. Do not rewrite or repair the material.
- Treat question_like_unit as an observation only, not as a final kind.
- Use open-world reasoning: preserve content that Runtime cannot express.
- If a writing surface/table/rubric/response area is needed, say so and cite evidence refs.
- If parent context is required, say what it depends on and cite evidence refs.
- If an answer/solution is not found in current evidence, mark BLOCKED. Do not invent answers.
- If a tail is incomplete, mark BLOCKED and keep unresolved continuation.
- Output JSON only. No markdown.
"""


def user_prompt(doc: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    schema = {
        "doc_id": "string",
        "target_assessments": [
            {
                "packet_id": "string",
                "source_unit_id": "string",
                "semantic_status": "COMPLETE | AMBIGUOUS | INCOMPLETE_SOURCE",
                "evidence_status": "COMPLETE | PARTIAL_ASSET | COORDINATE_INVALID | ENCODING_ERROR",
                "projection_status": "READY | READY_WITH_LOSS | NEEDS_REVIEW | UNSUPPORTED | BLOCKED",
                "relations": [
                    {
                        "predicate": "contains | depends_on | continues_on | answers | shares_context | uses_asset | other",
                        "object_hint": "string",
                        "evidence_refs": ["p001:b2"],
                        "reason": "string"
                    }
                ],
                "asset_requirements": [
                    {
                        "requirement": "string",
                        "evidence_refs": ["p001:b2"],
                        "status": "COMPLETE | PARTIAL | MISSING | NOT_REQUIRED"
                    }
                ],
                "risks": ["string"],
                "confidence": 0.0
            }
        ],
        "document_coverage": {
            "unexplained_major_content": ["string"],
            "unsupported_but_preserved_content": ["string"],
            "notes": "string"
        }
    }
    payload = {
        "task": "Review this document for semantic-graph-first ingest and target-specific projection. Return JSON matching output_schema.",
        "output_schema": schema,
        "doc_id": doc["doc_id"],
        "targets_to_assess": targets,
        "full_transcription_blocks": compact_blocks(doc),
        "observed_units": compact_units(doc),
        "asset_refs": doc["source_evidence"]["assets"],
        "allowed_projection_statuses": sorted(TARGET_STATUSES),
        "important_constraints": [
            "Do not use family-specific hard gates.",
            "Do not treat normalized hints as semantic facts.",
            "Do not invent missing answers.",
            "Current page image is the fact source; crops are derivative views.",
            "Projection status is target-specific and separate from semantic/evidence status.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def call_model(doc: dict[str, Any], targets: list[dict[str, Any]], *, api_key: str, model: str, timeout: int) -> dict[str, Any]:
    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt(doc, targets)}]
    image_paths = doc_page_images(doc)
    for image_path in image_paths:
        user_content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": user_content},
        ],
    }
    started = time.time()
    response = requests.post(
        ARK_API_URL,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, error = extract_json(content)
    return {
        "doc_id": doc["doc_id"],
        "called": True,
        "model": model,
        "latency_seconds": round(time.time() - started, 3),
        "image_count": len(image_paths),
        "parsed": parsed is not None,
        "parse_error": error,
        "raw_content": content if parsed is None else "",
        "result": parsed or {},
        "usage": raw.get("usage", {}),
    }


def human_projection_match(human_verdict: str, model_status: str, risks: list[str], relations: list[dict[str, Any]]) -> bool:
    status = str(model_status or "")
    risk_text = " ".join(str(item) for item in risks).lower()
    relation_text = " ".join(
        [str(item.get("predicate", "")) + " " + str(item.get("reason", "")) for item in relations]
    ).lower()
    if human_verdict.startswith("ACCEPT_WITH_MINOR_FORMAT_ISSUE"):
        return status in {"READY", "READY_WITH_LOSS", "NEEDS_REVIEW"}
    if human_verdict == "ACCEPT":
        return status in {"READY", "READY_WITH_LOSS"}
    if human_verdict.startswith("ACCEPT_WITH_PARENT_LINK"):
        return status in {"READY", "NEEDS_REVIEW", "READY_WITH_LOSS"}
    if human_verdict == "HOLD_PARENT_RELATION":
        return status in {"NEEDS_REVIEW", "BLOCKED", "READY_WITH_LOSS"} and (
            "depend" in relation_text or "parent" in risk_text or "context" in risk_text or "context" in relation_text
        )
    if human_verdict == "HOLD_BAD_ASSET_INCOMPLETE_WRITING_SURFACE":
        return status in {"READY_WITH_LOSS", "NEEDS_REVIEW", "BLOCKED"} and (
            "asset" in risk_text
            or "surface" in risk_text
            or "rubric" in risk_text
            or "table" in risk_text
            or "uses_asset" in relation_text
        )
    if human_verdict == "HOLD_MISSING_SOLUTION":
        return status == "BLOCKED" and ("answer" in risk_text or "solution" in risk_text)
    if human_verdict == "HOLD_INCOMPLETE_TAIL":
        return status == "BLOCKED" and ("continu" in risk_text or "incomplete" in risk_text or "continues_on" in relation_text)
    return False


def build_comparison(model_calls: list[dict[str, Any]], human_review: dict[str, Any]) -> dict[str, Any]:
    model_by_packet: dict[str, dict[str, Any]] = {}
    for call in model_calls:
        result = call.get("result", {}) if call.get("parsed") else {}
        for assessment in result.get("target_assessments", []) or []:
            packet_id = str(assessment.get("packet_id", "") or "")
            if packet_id:
                model_by_packet[packet_id] = assessment
    rows: list[dict[str, Any]] = []
    for human in human_review.get("packets", []):
        packet_id = str(human.get("packet_id", "") or "")
        assessment = model_by_packet.get(packet_id, {})
        risks = [str(item) for item in assessment.get("risks", []) or []]
        relations = list(assessment.get("relations", []) or [])
        match = human_projection_match(str(human.get("human_verdict", "")), str(assessment.get("projection_status", "")), risks, relations)
        rows.append(
            {
                "packet_id": packet_id,
                "doc_id": human.get("doc_id"),
                "human_verdict": human.get("human_verdict"),
                "human_note": human.get("note", ""),
                "model_projection_status": assessment.get("projection_status", "MISSING_MODEL_ASSESSMENT"),
                "model_semantic_status": assessment.get("semantic_status", "MISSING"),
                "model_evidence_status": assessment.get("evidence_status", "MISSING"),
                "model_relations": relations,
                "model_asset_requirements": assessment.get("asset_requirements", []),
                "model_risks": risks,
                "model_confidence": assessment.get("confidence"),
                "matches_human_direction": match,
            }
        )
    return {
        "schema": "english_text_first_model_graph_regression_v01.comparison",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "counts": {
            "items": len(rows),
            "matched": sum(1 for row in rows if row["matches_human_direction"]),
            "mismatched": sum(1 for row in rows if not row["matches_human_direction"]),
            "missing_model_assessment": sum(1 for row in rows if row["model_projection_status"] == "MISSING_MODEL_ASSESSMENT"),
        },
    }


def render_review_html(out_dir: Path, model_calls: list[dict[str, Any]], comparison: dict[str, Any]) -> str:
    parts: list[str] = [
        "<!doctype html><meta charset='utf-8'><title>English Model Graph Regression Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.45} table{border-collapse:collapse;width:100%;font-size:13px} th,td{border:1px solid #ddd;padding:8px;vertical-align:top} th{background:#f5f5f5}.ok{background:#eef9f0}.bad{background:#fff0f0}.mono{font-family:Consolas,monospace;white-space:pre-wrap}.call{margin:16px 0;padding:12px;border:1px solid #ddd;background:#fafafa}</style>",
        "<h1>English Model Graph Regression Review</h1>",
        f"<p>Generated at {html.escape(comparison['generated_at'])}. This page compares true model assessments against the existing human acceptance review.</p>",
        "<h2>Model Calls</h2>",
    ]
    for call in model_calls:
        css = "ok" if call.get("parsed") else "bad"
        parts.append(f"<div class='call {css}'>")
        parts.append(f"<b>{html.escape(str(call.get('doc_id')))}</b> parsed={call.get('parsed')} images={call.get('image_count')} latency={call.get('latency_seconds')}s")
        parts.append(f"<div>usage: {html.escape(json.dumps(call.get('usage', {}), ensure_ascii=False))}</div>")
        if not call.get("parsed"):
            parts.append(f"<pre class='mono'>{html.escape(str(call.get('parse_error', '')))}\n{html.escape(str(call.get('raw_content', ''))[:4000])}</pre>")
        parts.append("</div>")
    parts.append("<h2>17-Item Human Comparison</h2>")
    parts.append(f"<p>matched: {comparison['counts']['matched']} / {comparison['counts']['items']}; mismatched: {comparison['counts']['mismatched']}; missing model assessment: {comparison['counts']['missing_model_assessment']}</p>")
    parts.append("<table><thead><tr><th>packet</th><th>human</th><th>model statuses</th><th>model relations / assets / risks</th><th>match</th></tr></thead><tbody>")
    for row in comparison["rows"]:
        css = "ok" if row["matches_human_direction"] else "bad"
        model_bits = {
            "projection": row["model_projection_status"],
            "semantic": row["model_semantic_status"],
            "evidence": row["model_evidence_status"],
            "confidence": row["model_confidence"],
        }
        detail = {
            "relations": row["model_relations"],
            "asset_requirements": row["model_asset_requirements"],
            "risks": row["model_risks"],
        }
        parts.append(f"<tr class='{css}'>")
        parts.append(f"<td>{html.escape(row['packet_id'])}<br><small>{html.escape(str(row['doc_id']))}</small></td>")
        parts.append(f"<td><b>{html.escape(str(row['human_verdict']))}</b><br>{html.escape(str(row['human_note']))}</td>")
        parts.append(f"<td><pre class='mono'>{html.escape(json.dumps(model_bits, ensure_ascii=False, indent=2))}</pre></td>")
        parts.append(f"<td><pre class='mono'>{html.escape(json.dumps(detail, ensure_ascii=False, indent=2))}</pre></td>")
        parts.append(f"<td>{row['matches_human_direction']}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    parts.append("<h2>Raw Model Output</h2>")
    for call in model_calls:
        parts.append(f"<h3>{html.escape(str(call.get('doc_id')))}</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(call.get('result', {}), ensure_ascii=False, indent=2))}</pre>")
    html_text = "\n".join(parts)
    write_text(out_dir / "model_vs_human_review.html", html_text)
    return html_text


def run(args: argparse.Namespace) -> dict[str, Any]:
    api_key = str(args.api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing_ark_api_key")
    sidecar_root = workspace_path(args.sidecar_root)
    out_dir = workspace_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = read_json(sidecar_root / "semantic_graph.json")
    human_review = read_json(workspace_path(args.human_review))
    docs = list(graph.get("documents", []))
    calls: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as executor:
        futures = [
            executor.submit(
                call_model,
                doc,
                targets_for_doc(human_review, doc["doc_id"]),
                api_key=api_key,
                model=args.model,
                timeout=int(args.timeout),
            )
            for doc in docs
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                calls.append(future.result())
            except Exception as exc:  # noqa: BLE001 - persisted as run evidence
                calls.append({"called": True, "parsed": False, "error": f"{type(exc).__name__}: {exc}", "result": {}})
    calls.sort(key=lambda item: str(item.get("doc_id", "")))
    comparison = build_comparison(calls, human_review)
    write_json(out_dir / "model_graph_calls.json", {"schema": "english_text_first_model_graph_regression_v01.calls", "calls": calls})
    write_json(out_dir / "model_vs_human_comparison.json", comparison)
    render_review_html(out_dir, calls, comparison)
    summary = {
        "schema": "english_text_first_model_graph_regression_v01.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "model_calls": len(calls),
        "parsed_calls": sum(1 for item in calls if item.get("parsed")),
        "failed_calls": sum(1 for item in calls if not item.get("parsed")),
        "comparison_counts": comparison["counts"],
        "out_dir": rel_workspace(out_dir),
        "review_html": rel_workspace(out_dir / "model_vs_human_review.html"),
    }
    write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run model graph regression over the 24-page English sidecar evidence.")
    parser.add_argument("--sidecar-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/sidecar_rescue_v01_20260715")
    parser.add_argument("--human-review", default="outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json")
    parser.add_argument("--out", default="outputs/english_text_first_pipeline_v02_spec_20260715/model_graph_regression_24p_20260715")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
