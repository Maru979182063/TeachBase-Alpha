from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


BUILDER_VERSION = "english_question_packet_builder_v0.1_one_draft_in_one_packet_out_20260717"

CONTENT_FIELDS = [
    "instruction",
    "stem",
    "options",
    "passage",
    "answer",
    "analysis",
    "translation",
    "context",
    "examples",
    "rubric",
]

MOJIBAKE_MARKERS = [
    "鐭",
    "鏂",
    "銆",
    "鍥",
    "涓",
    "戞",
    "愮",
    "藞",
    "蓹",
    "蕦",
    "€?",
]

REVIEW_WARNING_CODES = {
    "missing_corresponding_answer",
    "TRUNCATED_ANALYSIS_CONTENT",
    "incomplete_answer_block",
    "missing_block_ref",
    "missing_page_image",
    "source_text_mojibake_suspected",
}


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def copy_field(field: dict[str, Any] | None) -> dict[str, Any]:
    field = field or {}
    return {
        "text": str(field.get("text") or ""),
        "refs": list(field.get("refs") or []),
        "missing_refs": list(field.get("missing_refs") or []),
    }


def packet_family(draft: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(draft.get("record_kind") or ""),
            str(draft.get("semantic_role") or ""),
            str(draft.get("doc_id") or ""),
        ]
    ).lower()
    if "reading" in text:
        return "reading"
    if "writing" in text or "invitation" in text or "composition" in text:
        return "writing"
    if "grammar" in text or "clause" in text:
        return "grammar"
    if "vocabulary" in text or "phrase" in text:
        return "vocabulary"
    if draft.get("projection_target_hint") == "knowledge_node":
        return "knowledge"
    return "open"


def detect_mojibake(content: dict[str, dict[str, Any]]) -> dict[str, Any]:
    suspect_fields: list[str] = []
    signals: list[dict[str, Any]] = []
    for field_name, field in content.items():
        text = str(field.get("text") or "")
        hits = [marker for marker in MOJIBAKE_MARKERS if marker in text]
        if hits:
            suspect_fields.append(field_name)
            signals.append(
                {
                    "field": field_name,
                    "markers": hits[:8],
                    "sample": text[:240],
                }
            )
    return {
        "mojibake_suspected": bool(suspect_fields),
        "suspect_fields": suspect_fields,
        "signals": signals,
    }


def has_primary_text(packet: dict[str, Any]) -> bool:
    content = packet["content"]
    return bool(
        content["stem"]["text"].strip()
        or content["instruction"]["text"].strip()
        or content["passage"]["text"].strip()
    )


def has_review_warning(draft: dict[str, Any]) -> bool:
    return any(str(warning.get("code", "")) in REVIEW_WARNING_CODES for warning in draft.get("warnings") or [])


def projection_status(draft: dict[str, Any], text_health: dict[str, Any], content: dict[str, dict[str, Any]]) -> str:
    if not draft.get("project_directly_to_question"):
        return "PRESERVED_NON_DIRECT"
    if text_health.get("mojibake_suspected"):
        return "DRAFT_NEEDS_REVIEW"
    if has_review_warning(draft):
        return "DRAFT_NEEDS_REVIEW"
    if not (
        content["stem"]["text"].strip()
        or content["instruction"]["text"].strip()
        or content["passage"]["text"].strip()
    ):
        return "DRAFT_NEEDS_REVIEW"
    return "DRAFT_READY"


def builder_warnings(draft: dict[str, Any], status: str, text_health: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if status == "PRESERVED_NON_DIRECT":
        warnings.append(
            {
                "code": "non_direct_preserved",
                "message": "This draft is preserved as source-backed material but must not be imported as a direct question.",
                "refs": [draft.get("source_group_id", "")],
            }
        )
    if text_health.get("mojibake_suspected"):
        warnings.append(
            {
                "code": "source_text_mojibake_suspected",
                "message": "One or more copied source text fields appear to contain mojibake. Builder preserved text exactly and marked the packet for review.",
                "refs": text_health.get("suspect_fields") or [],
            }
        )
    for warning in draft.get("warnings") or []:
        warnings.append(
            {
                "code": str(warning.get("code", "upstream_warning")),
                "message": str(warning.get("message", "")),
                "refs": list(warning.get("refs") or []),
                "source": "node4_draft",
            }
        )
    return warnings


def build_packet(draft: dict[str, Any]) -> dict[str, Any]:
    fields = draft.get("fields") or {}
    content = {field_name: copy_field(fields.get(field_name)) for field_name in CONTENT_FIELDS}
    text_health = detect_mojibake(content)
    status = projection_status(draft, text_health, content)
    packet_id = f"packet_{safe_id(str(draft.get('doc_id') or 'doc'))}_{safe_id(str(draft.get('source_group_id') or draft.get('draft_id') or 'draft'))}"
    visual_field = copy_field(fields.get("visual"))
    surface_field = copy_field(fields.get("writing_surface"))
    page_images = list(draft.get("page_image_refs") or [])
    return {
        "packet_id": packet_id,
        "doc_id": str(draft.get("doc_id") or ""),
        "source_draft_id": str(draft.get("draft_id") or ""),
        "source_group_id": str(draft.get("source_group_id") or ""),
        "projection_status": status,
        "packet_family": packet_family(draft),
        "project_directly_to_question": bool(draft.get("project_directly_to_question")),
        "content": content,
        "evidence": {
            "source_refs": list(draft.get("source_refs") or []),
            "source_pages": list(draft.get("source_pages") or []),
            "page_image_refs": page_images,
            "field_ref_map": {field_name: content[field_name]["refs"] for field_name in CONTENT_FIELDS},
        },
        "relations": draft.get("relations") or {},
        "asset_refs": {
            "visual_refs": visual_field["refs"],
            "writing_surface_refs": surface_field["refs"],
            "page_image_refs": page_images,
        },
        "source_text_health": text_health,
        "missing_fields": list(draft.get("missing_fields") or []),
        "builder_warnings": [],
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }


def finalize_packet_warnings(packet: dict[str, Any], draft: dict[str, Any]) -> None:
    packet["builder_warnings"] = builder_warnings(draft, packet["projection_status"], packet["source_text_health"])


def validate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not packet.get("packet_id"):
        errors.append({"path": "$.packet_id", "message": "missing packet_id"})
    if packet.get("runtime_import_enabled") is not False:
        errors.append({"path": "$.runtime_import_enabled", "message": "must remain false"})
    if packet.get("database_write_enabled") is not False:
        errors.append({"path": "$.database_write_enabled", "message": "must remain false"})
    for field_name in CONTENT_FIELDS:
        field = (packet.get("content") or {}).get(field_name)
        if not isinstance(field, dict):
            errors.append({"path": f"$.content.{field_name}", "message": "missing field"})
            continue
        for key in ("text", "refs", "missing_refs"):
            if key not in field:
                errors.append({"path": f"$.content.{field_name}.{key}", "message": "missing key"})
    if packet.get("projection_status") == "DRAFT_READY" and not has_primary_text(packet):
        errors.append({"path": "$.projection_status", "message": "DRAFT_READY requires primary text"})
    return {"valid": not errors, "errors": errors}


def write_one_packet(out_root: Path, packet: dict[str, Any], source_draft: dict[str, Any]) -> dict[str, Any]:
    packet_dir = out_root / "packets" / packet["packet_id"]
    write_json(packet_dir / "input_draft_item.json", source_draft)
    write_json(packet_dir / "packet_candidate.json", packet)
    validation = validate_packet(packet)
    write_json(packet_dir / "validation_report.json", validation)
    return {
        "packet_id": packet["packet_id"],
        "source_draft_id": packet["source_draft_id"],
        "source_group_id": packet["source_group_id"],
        "projection_status": packet["projection_status"],
        "packet_family": packet["packet_family"],
        "validation": validation,
        "packet_path": rel_workspace(packet_dir / "packet_candidate.json"),
    }


def render_packet_card(packet: dict[str, Any]) -> str:
    def field_block(title: str, key: str) -> str:
        field = packet["content"][key]
        refs = ", ".join(field.get("refs") or [])
        text = html.escape(field.get("text") or "")
        if not text:
            text = "<span class='muted'>空</span>"
        return f"<section><h4>{html.escape(title)} <small>{html.escape(refs)}</small></h4><pre>{text}</pre></section>"

    warnings = html.escape(json.dumps(packet.get("builder_warnings") or [], ensure_ascii=False, indent=2))
    health = html.escape(json.dumps(packet.get("source_text_health") or {}, ensure_ascii=False, indent=2))
    relations = html.escape(json.dumps(packet.get("relations") or {}, ensure_ascii=False, indent=2))
    return f"""
<article class="card">
  <h2>{html.escape(packet['packet_id'])} <small>{html.escape(packet['projection_status'])} / {html.escape(packet['packet_family'])}</small></h2>
  <p><b>source_group_id（来源组）</b>: <code>{html.escape(packet['source_group_id'])}</code> <b>direct（是否直投）</b>: <code>{packet['project_directly_to_question']}</code></p>
  {field_block("passage（文章/材料）", "passage")}
  {field_block("instruction（指令）", "instruction")}
  {field_block("stem（题干）", "stem")}
  {field_block("options（选项）", "options")}
  {field_block("examples（例句/例子）", "examples")}
  {field_block("answer（答案）", "answer")}
  {field_block("analysis（解析）", "analysis")}
  {field_block("translation（翻译）", "translation")}
  {field_block("context（上下文）", "context")}
  {field_block("rubric（评分标准）", "rubric")}
  <details><summary>relations（关系）</summary><pre>{relations}</pre></details>
  <details><summary>source_text_health（源文本健康）</summary><pre>{health}</pre></details>
  <details><summary>warnings（警告）</summary><pre>{warnings}</pre></details>
</article>
"""


def render_review(payload: dict[str, Any]) -> str:
    cards = "\n".join(render_packet_card(packet) for packet in payload.get("packet_candidates", []))
    summary = payload["summary"]
    return f"""<!doctype html>
<meta charset="utf-8">
<title>English Question Packet Builder Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f9;color:#202124;line-height:1.45}}
.card{{background:white;border:1px solid #d8dce2;border-radius:8px;padding:16px;margin:18px 0}}
code{{background:#eef0f3;padding:1px 4px;border-radius:4px}}
small{{color:#5f6368;font-weight:400}}
pre{{white-space:pre-wrap;background:#f8f9fb;border:1px solid #e2e5ea;border-radius:6px;padding:10px;overflow:auto}}
section{{border-top:1px solid #eef0f3;padding-top:8px;margin-top:8px}}
.muted{{color:#8a8f98}}
</style>
<h1>Node5 English Question Packet Builder Review</h1>
<p>doc_id=<code>{html.escape(payload['doc_id'])}</code>, packets=<code>{summary['packet_count']}</code>, direct=<code>{summary['direct_packet_count']}</code>, non_direct=<code>{summary['non_direct_preserved_count']}</code>, needs_review=<code>{summary['needs_review_count']}</code>, mojibake=<code>{summary['mojibake_suspected_count']}</code></p>
{cards}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    draft_path = workspace_path(args.draft_items_json)
    draft_payload = read_json(draft_path)
    doc_id = args.doc_id or draft_payload["doc_id"]
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    selected_ids = set(args.draft_ids or [])
    drafts = draft_payload.get("draft_items") or []
    if selected_ids:
        drafts = [draft for draft in drafts if draft.get("draft_id") in selected_ids or draft.get("source_group_id") in selected_ids]

    packet_candidates = []
    packet_records = []
    for draft in drafts:
        packet = build_packet(draft)
        finalize_packet_warnings(packet, draft)
        packet_candidates.append(packet)
        packet_records.append(write_one_packet(out_root, packet, draft))

    payload = {
        "schema": "english_question_packet_candidates_v0.1",
        "doc_id": doc_id,
        "builder_version": BUILDER_VERSION,
        "packet_candidates": packet_candidates,
        "summary": {
            "input_draft_count": len(drafts),
            "packet_count": len(packet_candidates),
            "direct_packet_count": sum(1 for packet in packet_candidates if packet["project_directly_to_question"]),
            "non_direct_preserved_count": sum(1 for packet in packet_candidates if packet["projection_status"] == "PRESERVED_NON_DIRECT"),
            "needs_review_count": sum(1 for packet in packet_candidates if packet["projection_status"] == "DRAFT_NEEDS_REVIEW"),
            "mojibake_suspected_count": sum(1 for packet in packet_candidates if packet["source_text_health"]["mojibake_suspected"]),
        },
    }
    validations = [record["validation"] for record in packet_records]
    summary = {
        "schema": "english_question_packet_builder.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node5_question_packet_builder",
        "doc_id": doc_id,
        "builder_version": BUILDER_VERSION,
        "draft_items_json": rel_workspace(draft_path),
        "out_dir": rel_workspace(out_root),
        "packet_count": len(packet_candidates),
        "valid_packet_count": sum(1 for validation in validations if validation["valid"]),
        "invalid_packet_count": sum(1 for validation in validations if not validation["valid"]),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "model_call_enabled": False,
        "packet_candidates_json": rel_workspace(out_root / "question_packet_candidates.json"),
        "review_html": rel_workspace(out_root / "review.html"),
        "packet_records": packet_records,
        "payload_summary": payload["summary"],
    }
    write_json(out_root / "question_packet_candidates.json", payload)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(payload))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--draft-items-json", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--draft-ids", nargs="*", default=[])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
