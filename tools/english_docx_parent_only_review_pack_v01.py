#!/usr/bin/env python3
"""Build parent-only review pages from English DOCX normalized groups."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any

from english_docx_parent_child_projection_v02 import (
    label_for_field,
    render_text,
    safe_rel,
    unknown_parent_field_policy,
    write_json,
)


FIELD_ORDER = [
    "source_label",
    "instruction",
    "passage",
    "question_items",
    "options",
    "response_area",
    "answer",
    "guide",
    "explanation",
    "sample_answer",
    "teaching_note",
]

FIELD_LABELS = {
    "question_items": "题目/小问",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field) or label_for_field(field)


def parent_fields(record: dict[str, Any], projection_notes: list[str], warnings: list[str]) -> dict[str, str]:
    source = record.get("fields") or {}
    parent = {field: str(source.get(field) or "") for field in FIELD_ORDER if str(source.get(field) or "").strip()}
    if str(source.get("unknown") or "").strip():
        parent["unknown"] = str(source.get("unknown") or "")
    unknown_parent_field_policy(parent, projection_notes, warnings)
    return parent


def build_records(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in normalized.get("records") or []:
        if not isinstance(record, dict):
            continue
        notes: list[str] = ["parent_only_review_no_child_projection"]
        warnings: list[str] = []
        fields = parent_fields(record, notes, warnings)
        records.append(
            {
                "group_id": str(record.get("group_id") or ""),
                "parent_kind": str(record.get("normalized_kind") or record.get("upstream_group_kind") or ""),
                "parent": fields,
                "source_block_ids": record.get("source_block_ids") or [],
                "normalization_block_ids": record.get("normalization_block_ids") or [],
                "excluded_block_ids": record.get("excluded_block_ids") or [],
                "projection_notes": notes,
                "warnings": warnings,
            }
        )
    return records


def render_field(field: str, text: str) -> str:
    if not str(text or "").strip():
        return ""
    return (
        f'<section class="field parent-{html.escape(field)}">'
        f"<h3>{html.escape(field_label(field))}</h3>{render_text(text)}</section>"
    )


def render_record(record: dict[str, Any]) -> str:
    parent = record.get("parent") or {}
    note_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in record.get("projection_notes") or [])
    warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in record.get("warnings") or [])
    field_html = "".join(render_field(field, str(parent.get(field) or "")) for field in FIELD_ORDER if parent.get(field))
    return (
        f'<article class="group" id="{html.escape(str(record.get("group_id") or ""))}">'
        f'<h2>{html.escape(str(record.get("group_id") or ""))} '
        f'<span>{html.escape(str(record.get("parent_kind") or ""))} · parent only</span></h2>'
        f'<div class="meta">原始块 {len(record.get("source_block_ids") or [])} · '
        f'入题块 {len(record.get("normalization_block_ids") or [])} · '
        f'隔离块 {len(record.get("excluded_block_ids") or [])}</div>'
        + (f'<ul class="notes">{note_html}</ul>' if note_html else "")
        + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
        + field_html
        + "</article>"
    )


def render_index(payload: dict[str, Any], out_path: Path) -> None:
    records = payload.get("records") or []
    nav = "".join(
        f'<a href="#{html.escape(str(record.get("group_id") or ""))}">'
        f'<b>{html.escape(str(record.get("group_id") or ""))}</b>'
        f'<span>{html.escape(str(record.get("parent_kind") or ""))}</span></a>'
        for record in records
    )
    css = """
body{margin:0;background:#f5f7fb;color:#172033;font:16px/1.72 "Times New Roman","Microsoft YaHei",serif}
.layout{display:grid;grid-template-columns:280px 1fr;min-height:100vh}
nav{position:sticky;top:0;height:100vh;overflow:auto;background:#fff;border-right:1px solid #d7dfeb;padding:18px}
nav h2{margin:0 0 12px;font:700 18px/1.35 "Microsoft YaHei",sans-serif}
nav a{display:block;text-decoration:none;color:#1f2937;border-radius:6px;padding:8px 10px}
nav a:hover{background:#edf6ff}
nav b{display:block;color:#0f766e}
nav span{display:block;color:#667085;font:12px/1.35 Arial,sans-serif}
main{padding:24px 28px 56px;max-width:1280px}
header,.group{background:#fff;border:1px solid #d7dfeb;border-radius:8px;margin-bottom:18px;padding:18px 22px}
h1{margin:0 0 8px;font:700 28px/1.25 "Microsoft YaHei",sans-serif}
h2{margin:0 0 8px;font:700 22px/1.3 "Microsoft YaHei",sans-serif}
h2 span{color:#667085;font-size:13px;font-weight:500}
.meta{color:#536174;font:13px/1.5 Arial,sans-serif;margin-bottom:12px}
.field{border-top:1px solid #e4eaf2;margin-top:10px;padding-top:10px}
.field h3{margin:0 0 6px;color:#0f766e;font:700 14px/1.35 "Microsoft YaHei",sans-serif}
.field p{margin:6px 0;white-space:pre-wrap}
.parent-answer,.parent-explanation,.parent-guide,.parent-sample_answer,.parent-teaching_note{background:#fff9ed}
.notes{margin:8px 0;padding-left:18px;color:#667085;font:13px/1.45 "Microsoft YaHei",sans-serif}
.warnings{margin:8px 0;padding-left:18px;color:#a15c00;font:13px/1.45 "Microsoft YaHei",sans-serif}
.current-blank{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:2px solid #111827;vertical-align:-.08em;background:#fff7cc}
.filled-blank{display:inline-block;min-width:5.2em;height:1.05em;margin:0 .18em;padding:0 .35em;border-bottom:1.5px solid #111827;text-align:center;line-height:1;vertical-align:-.08em;text-decoration:none}
.blank{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:1.5px solid #111827;vertical-align:-.08em}
.response-box{margin:8px 0 12px;padding:8px 0 2px;border:1px solid #d8dee5;border-radius:4px;background:#fff}
.response-meta{padding:0 12px 4px;color:#667085;font:12px/1.3 "Microsoft YaHei",sans-serif}
.write-line{height:30px;margin:0 12px;border-bottom:1px solid #333}
u{text-underline-offset:3px;text-decoration-thickness:1px}
"""
    html_doc = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(str(payload.get("doc_id") or ""))} parent only review</title>'
        f"<style>{css}</style></head><body><div class=\"layout\"><nav><h2>题组</h2>{nav}</nav><main>"
        f'<header><h1>{html.escape(str(payload.get("doc_id") or ""))} 父级审核页</h1>'
        f'<p class="meta">groups={len(records)} · child_projection=disabled</p></header>'
        + "".join(render_record(record) for record in records)
        + "</main></div></body></html>"
    )
    out_path.write_text(html_doc, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    normalized = read_json(args.input_normalized)
    records = build_records(normalized)
    payload = {
        "schema_version": "english_docx_parent_only_review.v0.1",
        "doc_id": args.doc_id or normalized.get("doc_id"),
        "source_normalized_groups": safe_rel(args.input_normalized),
        "records": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "parent_only_groups.json", payload)
    render_index(payload, args.output_dir / "index.html")
    summary = {
        "schema_version": "english_docx_parent_only_review_summary.v0.1",
        "doc_id": payload["doc_id"],
        "group_count": len(records),
        "unknown_parent_field_count": sum(1 for item in records if (item.get("parent") or {}).get("unknown")),
        "warning_count": sum(len(item.get("warnings") or []) for item in records),
        "artifacts": {
            "parent_only_groups": safe_rel(args.output_dir / "parent_only_groups.json"),
            "index": safe_rel(args.output_dir / "index.html"),
            "summary": safe_rel(args.output_dir / "summary.json"),
        },
    }
    write_json(args.output_dir / "summary.json", summary)
    if args.zip:
        zip_base = args.output_dir.with_suffix("")
        zip_path = shutil.make_archive(str(zip_base), "zip", root_dir=args.output_dir)
        summary["artifacts"]["zip"] = safe_rel(Path(zip_path))
        write_json(args.output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-normalized", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--zip", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
