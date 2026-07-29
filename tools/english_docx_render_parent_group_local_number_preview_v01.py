#!/usr/bin/env python3
"""Render parent groups in source-like form with parent-local item numbering."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


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
    "unknown",
]

FIELD_LABELS = {
    "source_label": "来源",
    "instruction": "题干",
    "passage": "材料",
    "question_items": "小题",
    "options": "选项",
    "response_area": "作答区",
    "answer": "答案",
    "guide": "导语",
    "explanation": "解析",
    "sample_answer": "范文",
    "teaching_note": "教学补充",
    "unknown": "未归类",
}

RENUMBER_FIELDS = {"question_items", "options", "answer", "explanation"}
BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_to_local_map(itemized_record: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in itemized_record.get("items") or []:
        source_no = str(item.get("source_item_no") or "").strip()
        local_no = str(item.get("item_no") or "").strip()
        if source_no and local_no:
            mapping[source_no] = local_no
    return mapping


def renumber_text(text: str, mapping: dict[str, str]) -> str:
    result = str(text or "")
    # Longer source numbers first avoids replacing "1." inside "11.".
    for source_no in sorted(mapping, key=lambda value: (-len(value), value)):
        local_no = mapping[source_no]
        if source_no == local_no:
            continue
        escaped = re.escape(source_no)
        result = re.sub(
            rf"(?<![\dA-Za-z]){escaped}\s*([.．、])",
            rf"{local_no}\1",
            result,
        )
    return result


def render_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = BLANK_RE.sub(
        lambda m: f'<span class="blank" title="BLANK_{m.group(1)}"></span>',
        escaped,
    )
    return escaped


def response_box(index: str, chars: int) -> str:
    line_count = max(3, min(12, round(chars / 72)))
    lines = "".join('<div class="write-line"></div>' for _ in range(line_count))
    return (
        f'<div class="response-box"><div class="response-meta">作答区 {html.escape(index)} · '
        f"{chars} chars · {line_count} lines</div>{lines}</div>"
    )


def render_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    pieces: list[str] = []
    for para in re.split(r"\n{2,}", text):
        cursor = 0
        local: list[str] = []
        for match in RESPONSE_RE.finditer(para):
            before = para[cursor : match.start()]
            if before.strip():
                local.append(f"<p>{render_inline(before.strip())}</p>")
            local.append(response_box(match.group(1), int(match.group(2))))
            cursor = match.end()
        after = para[cursor:]
        if after.strip():
            local.append(f"<p>{render_inline(after.strip())}</p>")
        if local:
            pieces.extend(local)
    return "\n".join(pieces)


def render_field(field: str, text: str) -> str:
    if not str(text or "").strip():
        return ""
    label = FIELD_LABELS.get(field, field)
    class_name = "answerish" if field in {"answer", "guide", "explanation", "sample_answer", "teaching_note"} else ""
    return f'<section class="field field-{html.escape(field)} {class_name}"><h3>{html.escape(label)}</h3>{render_text(text)}</section>'


def project_record(parent: dict[str, Any], itemized_record: dict[str, Any]) -> dict[str, Any]:
    mapping = source_to_local_map(itemized_record)
    fields = dict(parent.get("fields") or {})
    projected_fields: dict[str, str] = {}
    for field, value in fields.items():
        projected_fields[field] = renumber_text(value, mapping) if field in RENUMBER_FIELDS else str(value or "")
    return {
        "group_id": parent.get("group_id"),
        "parent_kind": itemized_record.get("parent_kind") or parent.get("normalized_kind"),
        "item_count": len(itemized_record.get("items") or []),
        "number_map": mapping,
        "fields": projected_fields,
    }


def render_group(record: dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    map_bits = [
        f"{html.escape(src)}→{html.escape(local)}"
        for src, local in (record.get("number_map") or {}).items()
        if src != local
    ]
    map_html = f'<div class="map">编号投影：{"; ".join(map_bits)}</div>' if map_bits else ""
    parts = [render_field(field, fields.get(field) or "") for field in FIELD_ORDER]
    return (
        f'<article class="group" id="{html.escape(str(record.get("group_id") or ""))}">'
        f'<h2>{html.escape(str(record.get("group_id") or ""))} '
        f'<span>{html.escape(str(record.get("parent_kind") or ""))} · items={record.get("item_count")}</span></h2>'
        f"{map_html}"
        f"{''.join(parts)}"
        "</article>"
    )


def write_group_markdown(record: dict[str, Any], output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {record.get('group_id')} {record.get('parent_kind')}", ""]
    for field in FIELD_ORDER:
        value = (record.get("fields") or {}).get(field)
        if not str(value or "").strip():
            continue
        lines.extend([f"## {FIELD_LABELS.get(field, field)}", "", str(value).strip(), ""])
    path = output_dir / f"{record.get('group_id')}.local_number.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    normalized = read_json(args.normalized)
    itemized = read_json(args.itemized)
    parents = {record.get("group_id"): record for record in normalized.get("records") or []}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    projected = [
        project_record(parents[record.get("group_id")], record)
        for record in itemized.get("records") or []
        if record.get("group_id") in parents
    ]
    markdown_paths = [write_group_markdown(record, args.output_dir / "groups_md") for record in projected]
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(str(normalized.get("doc_id") or ""))} · parent local numbering</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef2f5; color:#1f2933; font:16px/1.72 "Times New Roman","Microsoft YaHei",serif; }}
    header {{ position:sticky; top:0; z-index:2; padding:14px 28px; background:#fff; border-bottom:1px solid #d0d7de; }}
    h1 {{ margin:0; font:600 18px/1.35 "Microsoft YaHei",sans-serif; }}
    main {{ width:min(1080px, calc(100vw - 32px)); margin:22px auto 56px; }}
    .group {{ margin:0 0 22px; padding:22px 26px; background:#fffefa; border:1px solid #d0d7de; border-radius:6px; }}
    h2 {{ margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid #d0d7de; font:700 20px/1.3 "Microsoft YaHei",sans-serif; }}
    h2 span {{ color:#667085; font-size:13px; font-weight:500; }}
    h3 {{ margin:14px 0 6px; color:#0f766e; font:700 14px/1.35 "Microsoft YaHei",sans-serif; }}
    p {{ margin:7px 0; white-space:pre-wrap; }}
    .map {{ margin:0 0 12px; color:#667085; font:12px/1.45 "Microsoft YaHei",sans-serif; }}
    .answerish {{ color:#8a4b00; padding-top:8px; border-top:1px dashed #d9a65f; }}
    .blank {{ display:inline-block; width:5.2em; height:.95em; margin:0 .18em; border-bottom:1.5px solid #111827; vertical-align:-.08em; }}
    .response-box {{ margin:8px 0 12px; padding:8px 0 2px; border:1px solid #d8dee5; border-radius:4px; background:#fff; }}
    .response-meta {{ padding:0 12px 4px; color:#667085; font:12px/1.3 "Microsoft YaHei",sans-serif; }}
    .write-line {{ height:30px; margin:0 12px; border-bottom:1px solid #333; }}
    @media (max-width:640px) {{ main {{ width:calc(100vw - 18px); }} .group {{ padding:16px 14px; }} body {{ font-size:15px; }} }}
  </style>
</head>
<body>
  <header><h1>{html.escape(str(normalized.get("doc_id") or ""))} · 父组源式局部编号预览</h1></header>
  <main>{"".join(render_group(record) for record in projected)}</main>
</body>
</html>
"""
    (args.output_dir / "index.html").write_text(html_doc, encoding="utf-8")
    payload = {
        "schema_version": "english_docx_parent_group_local_number_projection.v0.1",
        "doc_id": normalized.get("doc_id"),
        "source_normalized_groups": str(args.normalized),
        "source_itemized_groups": str(args.itemized),
        "records": projected,
        "artifacts": {
            "index": str(args.output_dir / "index.html"),
            "groups_md_dir": str(args.output_dir / "groups_md"),
            "markdown_files": markdown_paths,
        },
    }
    (args.output_dir / "parent_groups.local_number.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "doc_id": normalized.get("doc_id"),
        "group_count": len(projected),
        "groups": [
            {
                "group_id": record.get("group_id"),
                "parent_kind": record.get("parent_kind"),
                "item_count": record.get("item_count"),
                "renumbered_pairs": [
                    [src, local] for src, local in (record.get("number_map") or {}).items() if src != local
                ],
            }
            for record in projected
        ],
        "artifacts": payload["artifacts"],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
