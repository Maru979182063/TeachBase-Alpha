#!/usr/bin/env python3
"""Render itemized English DOCX groups with one child card per business item."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    return BLANK_RE.sub(lambda m: f'<span class="blank" title="BLANK_{m.group(1)}"></span>', escaped)


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


def field_section(title: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {class_name}"><h3>{html.escape(title)}</h3>{render_text(text)}</section>'


def render_item(item: dict[str, Any]) -> str:
    display_no = str(item.get("item_no") or "")
    source_no = str(item.get("source_item_no") or "")
    no_text = html.escape(f"第 {display_no} 题") if display_no else ""
    if source_no and source_no != display_no:
        no_text += f" <span>原始 {html.escape(source_no)}</span>"
    head_parts = [
        part
        for part in [
            no_text,
            html.escape(str(item.get("item_id") or "")),
            html.escape(str(item.get("item_kind") or "")),
            html.escape(str(item.get("anchor") or "")),
        ]
        if part
    ]
    head = " ".join(head_parts)
    body = [
        field_section("题目", item.get("question_markdown") or ""),
        field_section("选项", item.get("options_markdown") or ""),
        field_section("作答区", item.get("response_area_markdown") or ""),
        field_section("答案", item.get("answer_text") or "", "answer"),
        field_section("解析", item.get("explanation_markdown") or "", "answer"),
    ]
    return f'<article class="item"><h4>{head}</h4>{"".join(body)}</article>'


def render_group(itemized: dict[str, Any], parent: dict[str, Any] | None) -> str:
    fields = (parent or {}).get("fields") or {}
    items = itemized.get("items") or []
    context = [
        field_section("来源", fields.get("source_label") or ""),
        field_section("题干", fields.get("instruction") or ""),
        field_section("材料", fields.get("passage") or ""),
        field_section("共享选项", fields.get("options") or ""),
    ]
    item_html = "".join(render_item(item) for item in items)
    return (
        '<section class="group">'
        f'<h2>{html.escape(str(itemized.get("group_id") or ""))} '
        f'<span>{html.escape(str(itemized.get("parent_kind") or ""))} · items={len(items)}</span></h2>'
        f'{"".join(context)}'
        f'<div class="items">{item_html}</div>'
        "</section>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normalized", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    normalized = read_json(args.normalized)
    itemized = read_json(args.itemized)
    parents = {record.get("group_id"): record for record in normalized.get("records") or []}
    groups = "\n".join(render_group(record, parents.get(record.get("group_id"))) for record in itemized.get("records") or [])
    doc_id = itemized.get("doc_id") or normalized.get("doc_id") or args.output.stem
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(str(doc_id))} · itemized preview</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef2f5; color:#1f2933; font:16px/1.68 "Times New Roman","Microsoft YaHei",serif; }}
    header {{ position:sticky; top:0; z-index:2; padding:14px 28px; background:#fff; border-bottom:1px solid #d0d7de; }}
    h1 {{ margin:0; font:600 18px/1.35 "Microsoft YaHei",sans-serif; }}
    main {{ width:min(1120px, calc(100vw - 32px)); margin:22px auto 56px; }}
    .group {{ margin:0 0 22px; padding:22px 26px; background:#fffefa; border:1px solid #d0d7de; border-radius:6px; }}
    h2 {{ margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid #d0d7de; font:700 20px/1.3 "Microsoft YaHei",sans-serif; }}
    h2 span {{ color:#667085; font-size:13px; font-weight:500; }}
    h3 {{ margin:12px 0 5px; color:#0f766e; font:700 14px/1.35 "Microsoft YaHei",sans-serif; }}
    h4 {{ margin:0 0 9px; font:700 15px/1.35 "Microsoft YaHei",sans-serif; color:#1d4ed8; }}
    h4 span {{ color:#667085; font-size:12px; font-weight:500; }}
    p {{ margin:6px 0; white-space:pre-wrap; }}
    .items {{ display:grid; grid-template-columns:1fr; gap:10px; margin-top:14px; }}
    .item {{ padding:12px 14px; background:#fff; border:1px solid #d8dee5; border-radius:6px; }}
    .answer {{ color:#8a4b00; }}
    .blank {{ display:inline-block; width:5.2em; height:.95em; margin:0 .18em; border-bottom:1.5px solid #111827; vertical-align:-.08em; }}
    .response-box {{ margin:8px 0 12px; padding:8px 0 2px; border:1px solid #d8dee5; border-radius:4px; background:#fff; }}
    .response-meta {{ padding:0 12px 4px; color:#667085; font:12px/1.3 "Microsoft YaHei",sans-serif; }}
    .write-line {{ height:30px; margin:0 12px; border-bottom:1px solid #333; }}
    @media (max-width:640px) {{ main {{ width:calc(100vw - 18px); }} .group {{ padding:16px 14px; }} body {{ font-size:15px; }} }}
  </style>
</head>
<body>
  <header><h1>{html.escape(str(doc_id))} · 小题成组预览</h1></header>
  <main>{groups}</main>
</body>
</html>
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
