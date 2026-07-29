#!/usr/bin/env python3
"""Render normalized English DOCX groups to a lightweight HTML preview."""

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

BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = BLANK_RE.sub(
        lambda m: f'<span class="blank" title="BLANK_{m.group(1)}"></span>',
        escaped,
    )
    return escaped


def response_area_html(index: str, chars: int) -> str:
    line_count = max(3, min(12, round(chars / 72)))
    lines = "\n".join('<div class="write-line"></div>' for _ in range(line_count))
    return (
        f'<div class="response-box" data-response-area="{html.escape(index)}" '
        f'data-chars="{chars}">'
        f'<div class="response-meta">作答区 {html.escape(index)} · {chars} chars · {line_count} lines</div>'
        f"{lines}</div>"
    )


def render_text(text: str) -> str:
    if not text:
        return ""
    blocks: list[str] = []
    for para in re.split(r"\n{2,}", text.strip()):
        if not para:
            continue
        cursor = 0
        para_bits: list[str] = []
        for match in RESPONSE_RE.finditer(para):
            before = para[cursor : match.start()]
            if before.strip():
                para_bits.append(f"<p>{render_inline(before.strip())}</p>")
            para_bits.append(response_area_html(match.group(1), int(match.group(2))))
            cursor = match.end()
        after = para[cursor:]
        if after.strip():
            para_bits.append(f"<p>{render_inline(after.strip())}</p>")
        if para_bits:
            blocks.extend(para_bits)
        else:
            blocks.append(f"<p>{render_inline(para.strip())}</p>")
    return "\n".join(blocks)


def render_record(record: dict[str, Any]) -> str:
    kind = html.escape(record.get("normalized_kind") or record.get("upstream_group_kind") or "unknown")
    group_id = html.escape(record.get("group_id", ""))
    issue_count = len(record.get("issues") or [])
    title = f"{group_id} <span>{kind}</span>"
    fields = record.get("fields") or {}
    field_parts = []
    for field in FIELD_ORDER:
        value = fields.get(field)
        if not value:
            continue
        label = FIELD_LABELS.get(field, field)
        field_parts.append(
            f'<section class="field field-{html.escape(field)}">'
            f"<h3>{html.escape(label)}</h3>"
            f"{render_text(str(value))}"
            "</section>"
        )
    issues = ""
    if issue_count:
        issues = f'<div class="issues">issues: {issue_count}</div>'
    return (
        f'<article class="group" id="{group_id}">'
        f"<h2>{title}</h2>"
        f"{issues}"
        f"{''.join(field_parts)}"
        "</article>"
    )


def render_doc(data: dict[str, Any], output_path: Path, only_response_area: bool = False) -> None:
    doc_id = data.get("doc_id", output_path.stem)
    records = data.get("records") or []
    if only_response_area:
        records = [record for record in records if (record.get("fields") or {}).get("response_area")]
    body = "\n".join(render_record(record) for record in records)
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(doc_id)} · normalized preview</title>
  <style>
    :root {{
      --ink: #1f2933;
      --muted: #667085;
      --line: #d0d7de;
      --paper: #fffefa;
      --soft: #f3f6f8;
      --accent: #0f766e;
      --answer: #8a4b00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #eef2f5;
      color: var(--ink);
      font: 16px/1.72 "Times New Roman", "Noto Serif SC", "Microsoft YaHei", serif;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 14px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(8px);
    }}
    header h1 {{
      margin: 0;
      font: 600 18px/1.35 "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }}
    main {{
      width: min(1060px, calc(100vw - 32px));
      margin: 24px auto 56px;
    }}
    .group {{
      margin: 0 0 22px;
      padding: 22px 26px 26px;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    h2 {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin: 0 0 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--line);
      font: 700 20px/1.3 "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }}
    h2 span {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }}
    .field {{
      margin-top: 16px;
    }}
    .field h3 {{
      margin: 0 0 6px;
      color: var(--accent);
      font: 700 14px/1.35 "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }}
    p {{
      margin: 7px 0;
      white-space: pre-wrap;
    }}
    .blank {{
      display: inline-block;
      width: 5.2em;
      height: 0.95em;
      margin: 0 0.18em;
      border-bottom: 1.5px solid #111827;
      vertical-align: -0.08em;
    }}
    .response-box {{
      margin: 10px 0 14px;
      padding: 9px 0 2px;
      background: #fff;
      border: 1px solid #d8dee5;
      border-radius: 4px;
    }}
    .response-meta {{
      padding: 0 12px 5px;
      color: var(--muted);
      font: 12px/1.3 "Microsoft YaHei", sans-serif;
    }}
    .write-line {{
      height: 30px;
      margin: 0 12px;
      border-bottom: 1px solid #333;
    }}
    .field-answer,
    .field-guide,
    .field-explanation,
    .field-sample_answer,
    .field-teaching_note {{
      padding-top: 10px;
      border-top: 1px dashed #d9a65f;
      color: var(--answer);
    }}
    .issues {{
      margin-bottom: 10px;
      color: #b42318;
      font: 13px/1.4 "Microsoft YaHei", sans-serif;
    }}
    @media (max-width: 640px) {{
      body {{ font-size: 15px; }}
      header {{ padding: 12px 16px; }}
      main {{ width: calc(100vw - 18px); margin-top: 12px; }}
      .group {{ padding: 16px 14px 18px; }}
      h2 {{ font-size: 17px; }}
      .blank {{ width: 4.2em; }}
      .write-line {{ height: 28px; margin-inline: 9px; }}
    }}
  </style>
</head>
<body>
  <header><h1>{html.escape(doc_id)} · 归一化渲染预览</h1></header>
  <main>{body}</main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--only-response-area", action="store_true")
    parser.add_argument("--only-groups", default="")
    args = parser.parse_args()
    data = load_json(args.input)
    if args.only_groups.strip():
        wanted = {item.strip() for item in args.only_groups.split(",") if item.strip()}
        data = dict(data)
        data["records"] = [record for record in data.get("records", []) if str(record.get("group_id") or "") in wanted]
    render_doc(data, args.output, only_response_area=args.only_response_area)
    print(json.dumps({"input": str(args.input), "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
