from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "docx_math_long_packet_assembler_output_v0.1"
PACKET_SCHEMA = "docx_math_refined_question_packet_v0.1"
OUT_ROOT = Path("outputs/docx_math_long_packet_assembler_v0_1")

sys.path.insert(0, str((ROOT / "tools").resolve()))
import docx_math_question_refiner_v01 as question_refiner  # noqa: E402


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def render_template(text: str, values: dict[str, Any]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = str(text or "").strip()
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


def asset_tokens(text: str) -> list[str]:
    return sorted(set(re.findall(r"asset://([A-Za-z0-9_-]+)", str(text or ""))))


def field_payload(field: dict[str, Any]) -> dict[str, Any]:
    markdown = str(field.get("markdown") or "")
    return {
        "block_ids": [str(item) for item in field.get("block_ids") or []],
        "markdown": markdown,
        "asset_ids": [
            str(asset.get("asset_id") or "")
            for asset in field.get("asset_refs") or []
            if isinstance(asset, dict) and asset.get("asset_id")
        ]
        + asset_tokens(markdown),
        "formula_count": int(field.get("formula_count") or 0),
    }


def load_drafts(input_root: Path, doc_id_contains: list[str], group_ids: set[str]) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    for path in sorted(input_root.glob("*/source_backed_draft/docx_math_source_backed_draft_items.json")):
        payload = read_json(path)
        doc_id = str(payload.get("doc_id") or "")
        if doc_id_contains and not any(fragment in doc_id for fragment in doc_id_contains):
            continue
        for draft in payload.get("draft_items") or []:
            if group_ids and draft.get("source_group_id") not in group_ids and draft.get("draft_id") not in group_ids:
                continue
            drafts.append(draft)
    return drafts


def source_refs_by_field(draft: dict[str, Any]) -> dict[str, list[str]]:
    fields = draft.get("fields") or {}
    return {
        name: [str(item) for item in (fields.get(name) or {}).get("block_ids") or []]
        for name in ["context", "stem", "subquestions", "options", "answer", "explanation", "teaching_note", "other_evidence"]
    }


def build_model_input(draft: dict[str, Any], long_packet: dict[str, Any]) -> dict[str, Any]:
    fields = draft.get("fields") or {}
    q = long_packet.get("standard_question") or {}
    segments: list[dict[str, Any]] = []
    if q.get("stem_md"):
        segments.append(
            {
                "segment_id": "assembled_stem_hint",
                "role": "stem",
                "label": "",
                "markdown": q.get("stem_md"),
                "asset_ids": asset_tokens(str(q.get("stem_md") or "")),
            }
        )
    for segment in q.get("nested_subquestions") or []:
        if not isinstance(segment, dict):
            continue
        segments.append(
            {
                "segment_id": segment.get("segment_id"),
                "role": segment.get("role"),
                "label": segment.get("label"),
                "prompt_md": segment.get("prompt_md"),
                "answer_md": segment.get("answer_md"),
                "explanation_md": segment.get("explanation_md"),
                "asset_ids": segment.get("asset_ids") or [],
                "source_refs": segment.get("source_refs") or {},
            }
        )
    return {
        "draft_id": draft.get("draft_id"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "record_kind": draft.get("record_kind"),
        "solution_policy": draft.get("solution_policy"),
        "source_backed_fields": {
            name: field_payload(fields.get(name) or {})
            for name in ["context", "stem", "subquestions", "options", "answer", "explanation", "teaching_note", "other_evidence"]
        },
        "source_refs_by_field": source_refs_by_field(draft),
        "asset_refs": draft.get("asset_refs") or [],
        "long_composite_segments": segments,
        "long_composite_plan": long_packet.get("plan") or {},
    }


def call_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def normalize_subquestions(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        markdown = str(item.get("markdown") or "").strip()
        label = str(item.get("label") or "").strip()
        if not markdown:
            continue
        out.append(
            {
                "label": label,
                "markdown": markdown,
                "answer_md": str(item.get("answer_md") or "").strip(),
                "explanation_md": str(item.get("explanation_md") or "").strip(),
            }
        )
    return out


def standard_packet_from_output(
    *,
    draft: dict[str, Any],
    long_packet: dict[str, Any],
    output: dict[str, Any] | None,
    prompt_version: str,
) -> dict[str, Any]:
    q_out = (output or {}).get("standard_question") if isinstance(output, dict) else {}
    if not isinstance(q_out, dict):
        q_out = {}
    q = {
        "title": str(q_out.get("title") or "").strip(),
        "question_type": str(q_out.get("question_type") or "composite").strip() or "composite",
        "stem_md": str(q_out.get("stem_md") or "").strip(),
        "subquestions": normalize_subquestions(q_out.get("subquestions")),
        "options": q_out.get("options") if isinstance(q_out.get("options"), list) else [],
        "answer_md": str(q_out.get("answer_md") or "").strip(),
        "explanation_md": str(q_out.get("explanation_md") or "").strip(),
        "teaching_note_md": str(q_out.get("teaching_note_md") or "").strip(),
        "context_md": str(q_out.get("context_md") or "").strip(),
    }
    q["render_markdown"] = question_refiner.canonical_render_markdown(q)
    return {
        "schema": PACKET_SCHEMA,
        "doc_id": draft.get("doc_id"),
        "source_draft_id": draft.get("draft_id"),
        "source_group_id": draft.get("source_group_id"),
        "prompt_version": prompt_version,
        "refine_status": "REFINED_READY" if (output or {}).get("status") == "READY" else "REFINED_NEEDS_REVIEW",
        "question_type": q["question_type"],
        "solution_policy": draft.get("solution_policy") or "unknown",
        "standard_question": q,
        "condition_groups": [],
        "source_refs": question_refiner.required_source_refs(draft),
        "asset_refs": {"visual_refs": draft.get("asset_refs") or []},
        "missing_fields": [],
        "warnings": list((output or {}).get("warnings") or []),
        "normalization_actions": [
            {
                "action": "long_packet_assembler_model_field_placement",
                "scope": "long_packet_assembler",
                "source_long_packet_status": long_packet.get("status"),
            }
        ],
        "status_breakdown": {
            "content_status": "CLEAN",
            "source_status": "CLEAN",
            "projection_status": "READY",
            "risk_codes": [],
        },
        "long_packet_assembler": {
            "schema": (output or {}).get("schema"),
            "source_usage": (output or {}).get("source_usage") or {},
        },
    }


def restore_missing_source_assets(packet: dict[str, Any], draft: dict[str, Any]) -> int:
    q = packet.get("standard_question")
    if not isinstance(q, dict):
        return 0
    fields = draft.get("fields") or {}
    field_targets = {
        "stem": "stem_md",
        "subquestions": "stem_md",
        "options": "stem_md",
        "answer": "answer_md",
        "explanation": "explanation_md",
        "teaching_note": "teaching_note_md",
        "other_evidence": "explanation_md",
    }
    output_text = "\n".join(question_refiner.refined_text_chunks(packet))
    present_assets = set(asset_tokens(output_text))
    restored = 0
    actions: list[dict[str, Any]] = []
    for source_field, target_field in field_targets.items():
        source_markdown = str((fields.get(source_field) or {}).get("markdown") or "")
        source_assets = set(asset_tokens(source_markdown))
        missing_assets = sorted(source_assets - present_assets)
        if not missing_assets:
            continue
        additions = [f"![{asset_id}](asset://{asset_id})" for asset_id in missing_assets]
        current = str(q.get(target_field) or "").strip()
        q[target_field] = "\n\n".join(part for part in [current, "\n\n".join(additions)] if part.strip())
        present_assets.update(missing_assets)
        restored += len(missing_assets)
        actions.append(
            {
                "action": "restore_missing_source_assets",
                "scope": "long_packet_assembler_post_model_coverage",
                "source_field": source_field,
                "target_field": target_field,
                "asset_ids": missing_assets,
            }
        )
    if restored:
        q["render_markdown"] = question_refiner.canonical_render_markdown(q)
        packet.setdefault("normalization_actions", []).extend(actions)
    return restored


def render_review(packet: dict[str, Any], validation: dict[str, Any], model_input: dict[str, Any], raw_content: str) -> str:
    q = packet.get("standard_question") or {}
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Long Packet Assembler Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fb;color:#111827;line-height:1.55}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card{{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:16px;margin:16px 0}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;overflow:auto;max-height:520px}}
code{{background:#eef2f7;padding:2px 5px;border-radius:4px}}
</style>
<h1>DOCX Long Packet Assembler Review</h1>
<p>group=<code>{html.escape(str(packet.get('source_group_id') or ''))}</code> status=<code>{html.escape(str(packet.get('refine_status') or ''))}</code> valid=<code>{validation.get('valid')}</code></p>
<div class="grid">
<div class="card"><h2>Rendered Markdown</h2><pre>{html.escape(str(q.get('render_markdown') or ''))}</pre></div>
<div class="card"><h2>Validation</h2><pre>{html.escape(json.dumps(validation, ensure_ascii=False, indent=2))}</pre></div>
</div>
<div class="card"><h2>Standard Question</h2><pre>{html.escape(json.dumps(q, ensure_ascii=False, indent=2))}</pre></div>
<div class="card"><h2>Model Input</h2><pre>{html.escape(json.dumps(model_input, ensure_ascii=False, indent=2))}</pre></div>
<div class="card"><h2>Raw Model Content</h2><pre>{html.escape(raw_content)}</pre></div>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node4c_long_packet_assembler"]
    out_root = workspace_path(config.get("owned_output_root") or OUT_ROOT) / args.run_id
    draft_root = workspace_path(args.input_draft_root)
    long_packet = read_json(workspace_path(args.long_packet_json))
    group_id = str(long_packet.get("source_group_id") or args.group_id or "")
    drafts = load_drafts(draft_root, args.doc_id_contains or [], {group_id} if group_id else set(args.group_ids or []))
    if len(drafts) != 1:
        raise SystemExit(f"expected exactly one matching source draft, got {len(drafts)}")
    draft = drafts[0]
    model_input = build_model_input(draft, long_packet)
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    user_prompt = render_template(
        user_template,
        {
            "prompt_version": node["prompt_version"],
            "doc_id": draft.get("doc_id") or "",
            "source_draft_id": draft.get("draft_id") or "",
            "source_group_id": draft.get("source_group_id") or "",
            "input_json": json.dumps(model_input, ensure_ascii=False, indent=2),
        },
    )
    write_json(out_root / "model_input.json", model_input)
    write_text(out_root / "prompt.json", json.dumps({"system": system_prompt, "user": user_prompt}, ensure_ascii=False, indent=2))
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.prepare_only and not args.raw_model_response_json:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')} or --api-key")
    model_result: dict[str, Any]
    if args.raw_model_response_json:
        cached = read_json(workspace_path(args.raw_model_response_json))
        model_result = {
            "parsed": cached.get("parsed"),
            "parse_error": cached.get("parse_error") or "",
            "raw_content": cached.get("raw_content") or "",
            "raw_response": cached.get("raw_response") or {},
            "request_body": cached.get("request_body") or {},
            "latency_seconds": 0,
            "cached_from": rel(workspace_path(args.raw_model_response_json)),
        }
    elif args.prepare_only:
        model_result = {"parsed": None, "parse_error": "prepare_only", "raw_content": "", "raw_response": {}, "request_body": {}, "latency_seconds": 0}
    else:
        model_result = call_model(config, node, system_prompt, user_prompt, api_key)
    write_json(out_root / "raw_model_response.json", model_result)
    output = model_result.get("parsed") if isinstance(model_result.get("parsed"), dict) else None
    packet = standard_packet_from_output(draft=draft, long_packet=long_packet, output=output, prompt_version=node["prompt_version"])
    restored_asset_count = restore_missing_source_assets(packet, draft)
    validation = question_refiner.validate_refined(packet, draft, node["prompt_version"])
    if not validation.get("valid"):
        packet["refine_status"] = "REFINED_NEEDS_REVIEW"
        packet["status_breakdown"]["projection_status"] = "BLOCKED"
        packet["status_breakdown"]["risk_codes"] = [str(err.get("code") or err.get("message") or "validation_error") for err in validation.get("errors") or []]
    write_json(out_root / "assembled_question_packet.json", packet)
    write_json(out_root / "validation_report.json", validation)
    write_text(out_root / "review.html", render_review(packet, validation, model_input, str(model_result.get("raw_content") or "")))
    summary = {
        "schema": "docx_math_long_packet_assembler.run_summary_v0.1",
        "run_id": args.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "parsed": output is not None,
        "parse_error": model_result.get("parse_error") or "",
        "valid": bool(validation.get("valid")),
        "error_count": len(validation.get("errors") or []),
        "restored_asset_count": restored_asset_count,
        "refine_status": packet.get("refine_status"),
        "usage": ((model_result.get("raw_response") or {}).get("usage") or {}),
        "latency_seconds": model_result.get("latency_seconds"),
        "packet_json": rel(out_root / "assembled_question_packet.json"),
        "review_html": rel(out_root / "review.html"),
    }
    write_json(out_root / "run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/docx_math_long_packet_assembler_v01.yaml")
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--long-packet-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id-contains", action="append", default=[])
    parser.add_argument("--group-id", default="")
    parser.add_argument("--group-ids", action="append", default=[])
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--raw-model-response-json", default="")
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
