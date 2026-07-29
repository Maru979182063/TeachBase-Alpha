#!/usr/bin/env python3
"""Render audit HTML pages for English DOCX normalized variants."""

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

CHILD_LABELS = {
    "question": "题目",
    "options": "选项",
    "response_area": "作答区",
    "answer": "答案",
    "explanation": "解析",
}

BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
CURRENT_BLANK_RE = re.compile(r"\[\[CURRENT_BLANK_(\d+)\]\]")
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")
ASSET_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(asset://([^)]+)\)")
ASSET_SRC_BY_ID: dict[str, str] = {}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_asset_src_by_id(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = read_json(path)
    refs: dict[str, str] = {}
    for asset in data.get("assets") or []:
        asset_id = str(asset.get("asset_id") or "").strip()
        storage_key = str(asset.get("storage_key") or "").strip()
        if not asset_id or not storage_key:
            continue
        refs[asset_id] = Path(storage_key).resolve().as_uri()
    return refs


def render_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = ASSET_IMAGE_RE.sub(
        lambda match: (
            '<figure class="asset-figure">'
            f'<img class="asset-image" src="{html.escape(ASSET_SRC_BY_ID.get(match.group(2), ""))}" '
            f'alt="{html.escape(match.group(1))}" loading="lazy">'
            f'<figcaption>{html.escape(match.group(1) or match.group(2))}</figcaption>'
            "</figure>"
        )
        if ASSET_SRC_BY_ID.get(match.group(2))
        else f'<code>{html.escape(match.group(0))}</code>',
        escaped,
    )
    escaped = CURRENT_BLANK_RE.sub(
        lambda match: f'<span class="current-blank" title="CURRENT_BLANK_{match.group(1)}"></span>',
        escaped,
    )
    escaped = BLANK_RE.sub(
        lambda match: f'<span class="blank" title="BLANK_{match.group(1)}"></span>',
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
    pieces: list[str] = []
    for para in re.split(r"\n{2,}", str(text or "").strip()):
        if not para.strip():
            continue
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
        pieces.extend(local)
    return "\n".join(pieces)


def field_section(label: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {class_name}"><h3>{html.escape(label)}</h3>{render_text(text)}</section>'


def render_parent_local_group(record: dict[str, Any]) -> str:
    fields = record.get("fields") or {}
    field_html = []
    for field in FIELD_ORDER:
        value = fields.get(field)
        klass = "answerish" if field in {"answer", "guide", "explanation", "sample_answer", "teaching_note"} else ""
        field_html.append(field_section(FIELD_LABELS.get(field, field), value or "", klass))
    return (
        '<article class="group">'
        f'<h2>{html.escape(str(record.get("group_id") or ""))} '
        f'<span>{html.escape(str(record.get("parent_kind") or record.get("normalized_kind") or "unknown"))}</span></h2>'
        f'{"".join(field_html)}'
        "</article>"
    )


def render_child(child: dict[str, Any], with_tags: bool) -> str:
    tag_html = ""
    if with_tags:
        tag = child.get("skill_tags") or {}
        secondary = " / ".join(str(item) for item in (tag.get("secondary_tags_zh") or []))
        tag_html = (
            '<div class="tags">'
            f'<b>{html.escape(str(tag.get("primary_label_zh") or "未知"))}</b>'
            f'<span>{html.escape(str(tag.get("category") or "unknown"))}</span>'
            f'<em>{html.escape(secondary)}</em>'
            "</div>"
            f'<div class="evidence">{html.escape(str(tag.get("evidence") or ""))}</div>'
        )
    parts = [
        field_section(CHILD_LABELS["question"], child.get("question") or ""),
        field_section(CHILD_LABELS["options"], child.get("options") or ""),
        field_section(CHILD_LABELS["response_area"], child.get("response_area") or ""),
        field_section(CHILD_LABELS["answer"], child.get("answer") or "", "answerish"),
        field_section(CHILD_LABELS["explanation"], child.get("explanation") or "", "answerish"),
    ]
    return (
        '<article class="child">'
        f'<h4>第 {html.escape(str(child.get("item_no") or ""))} 题 '
        f'<span>{html.escape(str(child.get("item_kind") or ""))}</span></h4>'
        f"{tag_html}"
        f'{"".join(parts)}'
        "</article>"
    )


def render_parent_child_group(record: dict[str, Any], with_tags: bool) -> str:
    parent = record.get("parent") or {}
    parent_html = []
    for field in FIELD_ORDER:
        if field in parent:
            parent_html.append(field_section(FIELD_LABELS.get(field, field), parent.get(field) or ""))
    children = record.get("children") or []
    child_html = "".join(render_child(child, with_tags) for child in children)
    return (
        '<article class="group">'
        f'<h2>{html.escape(str(record.get("group_id") or ""))} '
        f'<span>{html.escape(str(record.get("parent_kind") or "unknown"))} · children={len(children)}</span></h2>'
        '<div class="parent-block">'
        '<div class="block-title">父级原题</div>'
        f'{"".join(parent_html)}'
        "</div>"
        '<div class="child-block">'
        '<div class="block-title">子题拆分</div>'
        f"{child_html}"
        "</div>"
        "</article>"
    )


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef2f5; color:#1f2933; font:16px/1.7 "Times New Roman","Microsoft YaHei",serif; }}
    header {{ position:sticky; top:0; z-index:2; padding:14px 28px; background:#fff; border-bottom:1px solid #d0d7de; }}
    h1 {{ margin:0; font:600 18px/1.35 "Microsoft YaHei",sans-serif; }}
    main {{ width:min(1120px,calc(100vw - 32px)); margin:22px auto 56px; }}
    .group {{ margin:0 0 22px; padding:22px 26px; background:#fffefa; border:1px solid #d0d7de; border-radius:6px; }}
    h2 {{ margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid #d0d7de; font:700 20px/1.3 "Microsoft YaHei",sans-serif; }}
    h2 span,h4 span {{ color:#667085; font-size:13px; font-weight:500; }}
    h3 {{ margin:12px 0 5px; color:#0f766e; font:700 14px/1.35 "Microsoft YaHei",sans-serif; }}
    h4 {{ margin:0 0 8px; color:#1d4ed8; font:700 15px/1.35 "Microsoft YaHei",sans-serif; }}
    p {{ margin:6px 0; white-space:pre-wrap; }}
    .answerish {{ color:#8a4b00; }}
    .parent-block {{ margin-bottom:16px; }}
    .child-block {{ display:grid; gap:10px; }}
    .child {{ padding:12px 14px; background:#fff; border:1px solid #d8dee5; border-radius:6px; }}
    .block-title {{ margin:12px 0 8px; color:#475467; font:700 13px/1.35 "Microsoft YaHei",sans-serif; }}
    .blank {{ display:inline-block; width:5.2em; height:.95em; margin:0 .18em; border-bottom:1.5px solid #111827; vertical-align:-.08em; }}
    .current-blank {{ display:inline-block; width:5.2em; height:.95em; margin:0 .18em; border-bottom:2px solid #111827; vertical-align:-.08em; background:#fff7cc; }}
    .response-box {{ margin:8px 0 12px; padding:8px 0 2px; border:1px solid #d8dee5; border-radius:4px; background:#fff; }}
    .response-meta {{ padding:0 12px 4px; color:#667085; font:12px/1.3 "Microsoft YaHei",sans-serif; }}
    .write-line {{ height:30px; margin:0 12px; border-bottom:1px solid #333; }}
    .tags {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0; }}
    .tags b {{ display:inline-block; padding:2px 8px; border-radius:999px; background:#e0f2fe; color:#075985; font:700 13px/1.4 "Microsoft YaHei",sans-serif; }}
    .tags span,.tags em {{ color:#667085; font:12px/1.4 "Microsoft YaHei",sans-serif; }}
    .evidence {{ color:#8a4b00; font:13px/1.5 "Microsoft YaHei",sans-serif; }}
    .asset-figure {{ margin:12px 0; padding:10px; border:1px solid #d8dee5; border-radius:6px; background:#fff; }}
    .asset-image {{ display:block; max-width:100%; height:auto; margin:0 auto; }}
    .asset-figure figcaption {{ margin-top:6px; color:#667085; font:12px/1.4 "Microsoft YaHei",sans-serif; }}
  </style>
</head>
<body>
  <header><h1>{html.escape(title)}</h1></header>
  <main>{body}</main>
</body>
</html>
"""


def render_parent_local(input_path: Path, output_path: Path, title: str) -> None:
    data = read_json(input_path)
    body = "".join(render_parent_local_group(record) for record in data.get("records") or [])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page(title, body), encoding="utf-8")


def render_parent_child(input_path: Path, output_path: Path, title: str, with_tags: bool) -> None:
    data = read_json(input_path)
    body = "".join(render_parent_child_group(record, with_tags) for record in data.get("records") or [])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page(title, body), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["parent-local", "parent-child"])
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--with-tags", action="store_true")
    parser.add_argument("--asset-manifest", type=Path)
    args = parser.parse_args()
    global ASSET_SRC_BY_ID
    ASSET_SRC_BY_ID = load_asset_src_by_id(args.asset_manifest)
    if args.mode == "parent-local":
        render_parent_local(args.input, args.output, args.title)
    else:
        render_parent_child(args.input, args.output, args.title, args.with_tags)
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
