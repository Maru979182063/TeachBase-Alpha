#!/usr/bin/env python3
"""Render optimized no-panel review pages for English DOCX delivery packs."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from english_docx_parent_child_projection_v02 import (
    block_markdown,
    load_blocks,
    render_text,
    safe_rel,
    unknown_parent_field_policy,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]


FIELD_ORDER = [
    "source_label",
    "instruction",
    "passage",
    "question_option_flow",
    "question_items",
    "options",
    "response_area",
    "answer",
    "guide",
    "explanation",
    "sample_answer",
    "teaching_note",
]

WRITING_FIELD_ORDER = [
    "source_label",
    "instruction",
    "passage",
    "question_items",
    "response_area",
    "sample_answer",
    "guide",
    "explanation",
    "teaching_note",
    "answer",
    "options",
]
WRITING_KINDS = {"writing_letter", "continuation_writing"}

FIELD_LABELS = {
    "source_label": "来源/标题",
    "instruction": "说明/题干要求",
    "passage": "文章/材料",
    "question_option_flow": "题目与选项",
    "question_items": "题目/小问",
    "options": "选项",
    "response_area": "作答区",
    "answer": "答案",
    "guide": "导语",
    "explanation": "解析",
    "sample_answer": "范文/示例答案",
    "teaching_note": "知识点/教学标签",
}

DOC_TITLE = {
    "doc1": "doc1 语法填空父级审核",
    "doc2": "doc2 阅读理解父级审核",
    "doc3": "doc3 完形子题标签审核",
    "doc4": "doc4 七选五父级审核",
    "doc5": "doc5 读后续写父级审核",
    "doc6": "doc6 应用文写作父级审核",
}
UNLABELED_BLANK_RE = re.compile(r"\[\[BLANK_UNLABELED_\d+\]\]")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field)


def records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [record for record in payload.get("records") or [] if isinstance(record, dict)]


def record_kind(record: dict[str, Any]) -> str:
    return str(record.get("parent_kind") or record.get("normalized_kind") or record.get("upstream_group_kind") or "")


def field_order_for_record(record: dict[str, Any]) -> list[str]:
    return WRITING_FIELD_ORDER if record_kind(record) in WRITING_KINDS else FIELD_ORDER


def blocks_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = str(payload.get("source_block_stream") or "").strip()
    if not source:
        return {}
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.exists():
        return {}
    return load_blocks(source_path)


def block_order(block_id: str, blocks_by_id: dict[str, dict[str, Any]]) -> tuple[int, str]:
    block = blocks_by_id.get(block_id) or {}
    order = block.get("block_order")
    if isinstance(order, int):
        return (order, block_id)
    try:
        return (int(str(block_id).rsplit("_", 1)[-1]), block_id)
    except ValueError:
        return (10**9, block_id)


def ordered_unique_ids(ids: list[Any], blocks_by_id: dict[str, dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for block_id in sorted((str(item) for item in ids if str(item).strip()), key=lambda item: block_order(item, blocks_by_id)):
        if block_id in seen:
            continue
        seen.add(block_id)
        out.append(block_id)
    return out


def question_option_flow(record: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> str:
    kind = str(record.get("normalized_kind") or record.get("upstream_group_kind") or record.get("parent_kind") or "")
    if kind != "reading":
        return ""
    field_block_ids = record.get("field_block_ids") or {}
    ids = ordered_unique_ids(
        list(field_block_ids.get("question_items") or []) + list(field_block_ids.get("options") or []),
        blocks_by_id,
    )
    rows = [block_markdown(blocks_by_id.get(block_id)) for block_id in ids]
    return "\n\n".join(row for row in rows if row.strip())


def parent_from_record(record: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    if isinstance(record.get("parent"), dict):
        return record.get("parent") or {}
    fields = record.get("fields") or {}
    field_order = field_order_for_record(record)
    parent = {
        field: str(fields.get(field) or "")
        for field in field_order
        if field != "question_option_flow" and str(fields.get(field) or "").strip()
    }
    flow = question_option_flow(record, blocks_by_id)
    if flow:
        parent.pop("question_items", None)
        parent.pop("options", None)
        parent["question_option_flow"] = flow
    notes: list[str] = []
    warnings: list[str] = []
    unknown_parent_field_policy(parent, notes, warnings)
    return parent


def render_parent_field(field: str, text: str) -> str:
    if not str(text or "").strip():
        return ""
    return (
        f'<section class="parent-field parent-field-{html.escape(field)}">'
        f"<h3>{html.escape(field_label(field))}</h3>{render_doc_text(text)}</section>"
    )


def ordered_parent_fields(parent: dict[str, Any], field_order: list[str]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for field in field_order:
        value = str(parent.get(field) or "").strip()
        if value:
            fields.append((field, value))
    for field, value in parent.items():
        if field in FIELD_ORDER or field in WRITING_FIELD_ORDER or field == "unknown":
            continue
        value_text = str(value or "").strip()
        if value_text:
            fields.append((str(field), value_text))
    return fields


def split_options(options: str) -> list[str]:
    raw = str(options or "").strip()
    if not raw:
        return []
    pieces = [piece.strip() for piece in raw.replace("\r", "\n").split("\n") if piece.strip()]
    if len(pieces) <= 1:
        pieces = [piece.strip() for piece in raw.split("\t") if piece.strip()]
    return pieces


def render_options(options: str) -> str:
    pieces = split_options(options)
    if len(pieces) > 1:
        items = "".join(f'<div class="option-item">{html.escape(piece)}</div>' for piece in pieces)
        return f'<div class="option-list">{items}</div>'
    return render_doc_text(options)


def render_doc_text(text: str) -> str:
    rendered = render_text(text)
    return UNLABELED_BLANK_RE.sub('<span class="blank" title="BLANK_UNLABELED"></span>', rendered)


def tag_text(child: dict[str, Any]) -> str:
    tags = child.get("skill_tags") or {}
    return str(tags.get("primary_label_zh") or "").strip()


def tag_evidence(child: dict[str, Any]) -> str:
    tags = child.get("skill_tags") or {}
    return str(tags.get("evidence") or "").strip()


def render_child(child: dict[str, Any], index: int) -> str:
    title = f'第 {html.escape(str(child.get("item_no") or index))} 题'
    kind = html.escape(str(child.get("item_kind") or ""))
    tag = tag_text(child)
    evidence = tag_evidence(child)
    context = str(child.get("relevant_context") or child.get("question") or "")
    sections = [
        ("相关原文" if context else "", context, "question-section-related"),
        ("选项" if str(child.get("options") or "").strip() else "", str(child.get("options") or ""), "question-section-options"),
        ("答案" if str(child.get("answer") or "").strip() else "", str(child.get("answer") or ""), "question-section-answer"),
        ("解析" if str(child.get("explanation") or "").strip() else "", str(child.get("explanation") or ""), "question-section-analysis"),
    ]
    section_html: list[str] = []
    for label, text, class_name in sections:
        if not label:
            continue
        body = render_options(text) if class_name == "question-section-options" else render_doc_text(text)
        section_html.append(f'<section class="{class_name}"><h4>{html.escape(label)}</h4>{body}</section>')
    tag_html = f'<div class="question-tags"><span class="tag-chip">{html.escape(tag)}</span></div>' if tag else ""
    evidence_html = f'<div class="evidence">{html.escape(evidence)}</div>' if evidence else ""
    return (
        f'<article class="child" id="{html.escape(str(child.get("item_id") or ""))}">'
        '<header><div class="question-title">'
        f'<h3>{title} <small>{kind}</small></h3></div></header>'
        f"{tag_html}{evidence_html}{''.join(section_html)}</article>"
    )


def render_group(record: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> str:
    parent = parent_from_record(record, blocks_by_id)
    parent_html = "".join(render_parent_field(field, value) for field, value in ordered_parent_fields(parent, field_order_for_record(record)))
    children = [child for child in record.get("children") or [] if isinstance(child, dict)]
    children_html = "".join(render_child(child, index) for index, child in enumerate(children, start=1))
    notes = [str(item) for item in record.get("projection_notes") or [] if str(item).strip()]
    warnings = [str(item) for item in record.get("warnings") or [] if str(item).strip()]
    note_html = "".join(f"<li>{html.escape(item)}</li>" for item in notes)
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in warnings)
    return (
        f'<article class="group" id="{html.escape(str(record.get("group_id") or ""))}">'
        f'<h2>{html.escape(str(record.get("group_id") or ""))} '
        f'<small>{html.escape(record_kind(record))}</small></h2>'
        + (f'<ul class="notes">{note_html}</ul>' if note_html else "")
        + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
        + f'<div class="parent">{parent_html}</div>'
        + (f'<div class="children">{children_html}</div>' if children_html else "")
        + "</article>"
    )


def nav_title(record: dict[str, Any], index: int, blocks_by_id: dict[str, dict[str, Any]]) -> str:
    parent = parent_from_record(record, blocks_by_id)
    for key in ["source_label", "instruction", "passage"]:
        value = str(parent.get(key) or "").strip().splitlines()
        if value:
            title = value[0].strip()
            return title[:20] if title else f"第 {index} 组"
    return f"第 {index} 组"


def optimized_css() -> str:
    return """
:root{--bg:#f5f7fb;--surface:#fff;--soft:#f8fafc;--line:#e2e8f0;--text:#172033;--muted:#64748b;--primary:#5146e5;--primary-soft:#f2f1ff;--tag-bg:#eaf3ff;--tag-text:#245b91;--success:#18794e;--success-bg:#edf9f2;--warning:#b45309;--warning-bg:#fff8e8}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.7 "Times New Roman",SimSun,"宋体","Microsoft YaHei",serif}.top{height:64px;position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:24px;padding:0 24px;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(10px)}.top h1{margin:0;font:700 18px/1.3 "Microsoft YaHei",sans-serif}.summary{margin-left:auto;color:var(--muted);font:13px/1.4 "Microsoft YaHei",sans-serif}.progress-pill{padding:5px 10px;border-radius:999px;background:var(--primary-soft);color:var(--primary);font-weight:700}
.workbench{display:grid;grid-template-columns:184px minmax(0,1fr);min-height:calc(100vh - 64px)}.group-sidebar{position:sticky;top:64px;height:calc(100vh - 64px);overflow:auto;background:var(--surface);border-right:1px solid var(--line);padding:18px 10px;font-family:SimSun,"宋体",serif}.sidebar-title{padding:0 10px 10px;color:var(--muted);font-size:12px;font-weight:700;letter-spacing:.08em}.group-nav{width:100%;display:grid;grid-template-columns:1fr auto;align-items:center;gap:8px;padding:11px 10px;margin:2px 0;border:0;border-radius:8px;background:transparent;color:var(--text);text-align:left;cursor:pointer}.group-nav:hover{background:#f8fafc}.group-nav.active{background:var(--primary-soft);color:var(--primary)}.group-nav-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.group-nav-progress{color:var(--muted);font-size:11px}
.content{width:100%;max-width:1500px;margin:0 auto;padding:24px 34px 80px;overflow:visible}.group{display:none;margin:0;padding:0;border:0;border-radius:0;background:transparent}.group.active{display:block}.group>h2{display:none}.parent{padding:22px 24px;overflow:hidden;background:var(--surface);border:1px solid #d9e2ee;border-left:4px solid #8da9d2;border-radius:10px;box-shadow:0 2px 10px rgba(15,23,42,.025)}.parent-field{margin:0!important;padding:0!important;border:0!important;background:transparent!important}.parent-field:first-child{padding-bottom:12px!important;margin-bottom:14px!important;border-bottom:1px solid var(--line)!important}.parent-field h3{margin:0 0 4px;color:var(--muted);font:700 12px/1.35 "Microsoft YaHei",sans-serif}.parent-field:first-child p{font-weight:700}.parent-field p{margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}.parent-field-passage p,.parent-field-question_items p{font:16px/1.9 "Times New Roman",SimSun,"宋体",serif}
.children{display:grid;gap:14px;margin-top:20px}.child{padding:17px 18px;border:1px solid var(--line);border-left:3px solid transparent;border-radius:10px;background:var(--surface)}.child>header{display:flex;align-items:center;justify-content:space-between;margin:0 0 7px}.question-title{display:flex;align-items:center;gap:0}.child h3{margin:0;color:#000;font:700 16px/1.35 "Microsoft YaHei",sans-serif}.child h3 small{color:var(--muted);font-size:12px;font-weight:500}.question-tags{display:flex;flex-wrap:wrap;gap:7px;margin:4px 0 18px}.tag-chip{padding:5px 12px;border-radius:999px;background:#e5f4ff;color:#086b9c;font:700 14px/1.4 SimSun,"宋体",sans-serif}.evidence{color:#8a4b00;margin:4px 0 8px;font:13px/1.5 "Microsoft YaHei",sans-serif}
.child>section{margin:0 0 10px!important;padding:12px 14px!important;border:0!important;border-radius:8px!important;color:#000!important;background:#fff!important;font-family:"Times New Roman",SimSun,"宋体",serif!important}.child>section:last-of-type{margin-bottom:0!important}.child>section h4{margin:0 0 7px!important;color:#000!important;font:700 15px/1.4 SimSun,"宋体",serif!important}.child>section p{margin:0!important;color:#000!important;white-space:pre-wrap;font:15px/1.75 "Times New Roman",SimSun,"宋体",serif!important}.child>.question-section-answer{border:1px solid #f2e5b5!important;background:#fffdf4!important}.child>.question-section-answer p{font-weight:700!important}.child>.question-section-analysis{border:1px solid #dceee1!important;background:#f7fcf8!important}
.option-list{display:grid;gap:8px}.option-item{padding:7px 10px;border:1px solid #e5e7eb;border-radius:6px;background:#fff;color:#000;font:15px/1.55 SimSun,"宋体",serif}.current-blank{position:relative;display:inline-block;width:5.2em;height:1em;margin:0 .22em;background:#fff1a8!important;border:0!important;box-shadow:inset 0 -2px 0 #9a7400;vertical-align:-.12em;line-height:1}.current-blank::before{content:"\\00a0"}.blank{display:inline-block;width:5.2em;height:1em;margin:0 .22em;border-bottom:1px solid #111;vertical-align:-.12em;line-height:1}.blank::before{content:"\\00a0"}.filled-blank,.filled{display:inline-block;min-width:5.2em;margin:0 .18em;padding:0 .35em;border-bottom:1.5px solid #111;text-align:center;text-decoration:none;line-height:1}.response-box{margin:8px 0 12px;padding:8px 0 2px;border:1px solid #d8dee5;border-radius:4px;background:#fff}.response-meta{padding:0 12px 4px;color:#667085;font:12px/1.3 "Microsoft YaHei",sans-serif}.write-line{height:30px;margin:0 12px;border-bottom:1px solid #333}.notes{margin:8px 0;padding-left:18px;color:#667085;font:13px/1.45 "Microsoft YaHei",sans-serif}.warnings{margin:8px 0;padding-left:18px;color:#a15c00;font:13px/1.45 "Microsoft YaHei",sans-serif}
@media(max-width:900px){.workbench{grid-template-columns:155px minmax(0,1fr)}.content{padding:18px 18px 70px}.top{padding:0 14px}.summary{display:none}}@media(max-width:760px){.workbench{display:block}.group-sidebar{position:static;width:100%;height:auto;display:flex;overflow-x:auto;padding:8px;border:0;border-bottom:1px solid var(--line)}.sidebar-title{display:none}.group-nav{min-width:115px}.content{padding:16px 12px 70px}.parent{padding:18px}}
"""


def optimized_js() -> str:
    return """
(()=>{
  const groups=[...document.querySelectorAll('.group')];
  const nav=[...document.querySelectorAll('.group-nav')];
  function showGroup(i, reset){
    groups.forEach((g,j)=>g.classList.toggle('active',i===j));
    nav.forEach((b,j)=>b.classList.toggle('active',i===j));
    if(reset) window.scrollTo(0,0);
  }
  nav.forEach((button,i)=>button.addEventListener('click',()=>showGroup(i,true)));
  showGroup(0,false);
})();
"""


def render_html(payload: dict[str, Any], doc_key: str) -> str:
    records = records_from_payload(payload)
    blocks_by_id = blocks_from_payload(payload)
    title = DOC_TITLE.get(doc_key, str(payload.get("doc_id") or doc_key))
    child_count = sum(len(record.get("children") or []) for record in records)
    nav = "".join(
        f'<button class="group-nav" type="button"><span class="group-nav-title">{html.escape(nav_title(record, index, blocks_by_id))}</span>'
        f'<span class="group-nav-progress">{len(record.get("children") or []) or "父级"}</span></button>'
        for index, record in enumerate(records, start=1)
    )
    body = "".join(render_group(record, blocks_by_id) for record in records)
    summary = f"groups={len(records)}" + (f" · children={child_count}" if child_count else " · parent only")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{optimized_css()}</style></head>"
        f'<body><header class="top"><h1>{html.escape(title)}</h1>'
        f'<div class="summary"><span class="progress-pill">{html.escape(summary)}</span></div></header>'
        f'<div class="workbench"><nav class="group-sidebar"><div class="sidebar-title">大题导航</div>{nav}</nav>'
        f'<main class="content">{body}</main></div><script>{optimized_js()}</script></body></html>'
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = read_json(args.input_json)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    html_text = render_html(payload, args.doc_key)
    (args.output_dir / "index.html").write_text(html_text, encoding="utf-8")
    write_json(args.output_dir / "review_data.json", payload)
    summary = {
        "schema_version": "english_docx_optimized_review_summary.v0.1",
        "doc_key": args.doc_key,
        "source_json": safe_rel(args.input_json),
        "group_count": len(records_from_payload(payload)),
        "child_count": sum(len(record.get("children") or []) for record in records_from_payload(payload)),
        "artifacts": {
            "index": safe_rel(args.output_dir / "index.html"),
            "review_data": safe_rel(args.output_dir / "review_data.json"),
            "summary": safe_rel(args.output_dir / "summary.json"),
        },
    }
    write_json(args.output_dir / "summary.json", summary)
    if args.zip:
        zip_path = Path(shutil.make_archive(str(args.output_dir), "zip", root_dir=args.output_dir))
        summary["artifacts"]["zip"] = safe_rel(zip_path)
        write_json(args.output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", required=True, type=Path)
    parser.add_argument("--doc-key", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--zip", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
