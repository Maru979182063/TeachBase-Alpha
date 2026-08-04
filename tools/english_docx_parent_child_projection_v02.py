#!/usr/bin/env python3
"""Render English DOCX parent/child projection from normalized groups and itemizer output."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")
BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
CURRENT_BLANK_RE = re.compile(r"\[\[CURRENT_BLANK_(\d+)\]\]")
UNDERLINE_FILL_RE = re.compile(r"\[\[UNDERLINE_FILL_(\d+)\]\](.*?)\[\[/UNDERLINE_FILL_\1\]\]")
LEADING_SOURCE_NO_RE = re.compile(r"^(\s*)(\d{1,3})([\.、．:：)])\s*")
DETAIL_SOURCE_NO_RE = re.compile(r"^(\s*【详解】\s*)(\d{1,3})([\.、．:：)])\s*")
CLOZE_UNDERSCORE_RE = re.compile(r"_{2,}\s*(\d{1,3})\s*_{2,}")
OPTION_LABEL_RE = re.compile(r"(?<![A-Za-z])([A-H])\.\s*")

PARENT_ONLY_KINDS = {"writing_letter", "continuation_writing"}
PARENT_FIELDS = [
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
DEFAULT_CHILD_PARENT_FIELDS = ["source_label", "instruction", "passage", "response_area", "sample_answer", "teaching_note"]
PARENT_FIELDS_BY_KIND = {
    "reading": ["source_label", "instruction", "passage", "teaching_note"],
    "cloze": ["source_label", "instruction", "passage", "teaching_note"],
    "grammar_cloze": ["source_label", "instruction", "passage", "teaching_note"],
    "seven_choice": ["source_label", "instruction", "passage", "options", "teaching_note"],
    "seven_choices_five": ["source_label", "instruction", "passage", "options", "teaching_note"],
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def group_kind(record: dict[str, Any]) -> str:
    return str(record.get("normalized_kind") or record.get("upstream_group_kind") or record.get("parent_kind") or "mixed_or_unknown")


def source_order_from_id(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return 10**9


def sorted_ids(ids: list[Any]) -> list[str]:
    return sorted((str(item) for item in ids), key=lambda item: (source_order_from_id(item), item))


def load_blocks(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    blocks = payload.get("blocks") if isinstance(payload, dict) else payload
    out: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or block.get("id") or f"b_{index:06d}")
        out[block_id] = block
    return out


def block_markdown(block: dict[str, Any] | None) -> str:
    if not block:
        return ""
    return str(
        block.get("display_markdown")
        or block.get("markdown")
        or block.get("md")
        or block.get("plain_text_lossy")
        or block.get("text")
        or ""
    )


def ids_markdown(ids: list[str], blocks_by_id: dict[str, dict[str, Any]]) -> str:
    rows = [block_markdown(blocks_by_id.get(block_id)) for block_id in ids]
    return "\n\n".join(row for row in rows if row.strip())


def itemized_records_by_group(itemized: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(record.get("group_id") or ""): record for record in itemized.get("records") or [] if isinstance(record, dict)}


def parent_fields_for(record: dict[str, Any], fields: list[str]) -> dict[str, str]:
    source = record.get("fields") or {}
    return {field: str(source.get(field) or "") for field in fields if str(source.get(field) or "").strip()}


def unknown_parent_field_policy(parent: dict[str, str], notes: list[str], warnings: list[str]) -> None:
    unknown = str(parent.pop("unknown", "") or "").strip()
    if not unknown:
        return
    teaching_markers = [
        "【难度】",
        "【知识点】",
        "【点睛】",
        "【高分句型",
        "【详解】",
        "续写线索",
        "词类激活",
        "词汇激活",
        "句式拓展",
    ]
    if any(marker in unknown for marker in teaching_markers):
        existing = str(parent.get("teaching_note") or "").strip()
        parent["teaching_note"] = "\n\n".join(part for part in [existing, unknown] if part)
        notes.append("unknown_parent_field_promoted_to_teaching_note")
        return
    warnings.append("unknown_parent_field_quarantined_not_projected")


def reading_option_ids_from_field_roles(record: dict[str, Any], item: dict[str, Any], index: int) -> list[str]:
    field_ids = record.get("field_block_ids") or {}
    qids = sorted_ids(field_ids.get("question_items") or [])
    option_ids = sorted_ids(field_ids.get("options") or [])
    item_qids = [str(value) for value in item.get("question_block_ids") or []]
    qid = item_qids[0] if item_qids else (qids[index - 1] if index - 1 < len(qids) else "")
    if not qid:
        return []
    try:
        q_index = qids.index(qid)
    except ValueError:
        q_index = index - 1
    current_order = source_order_from_id(qid)
    next_order = source_order_from_id(qids[q_index + 1]) if q_index + 1 < len(qids) else 10**9
    return [block_id for block_id in option_ids if current_order < source_order_from_id(block_id) < next_order]


def cloze_option_ids_from_field_roles(record: dict[str, Any], item: dict[str, Any], index: int) -> list[str]:
    option_ids = sorted_ids((record.get("field_block_ids") or {}).get("options") or [])
    source_no = str(item.get("source_item_no") or item.get("item_no") or "").strip()
    try:
        local_index = int(source_no)
    except ValueError:
        local_index = index
    if 1 <= local_index <= len(option_ids):
        return [option_ids[local_index - 1]]
    return []


def child_from_item(
    group_id: str,
    index: int,
    item: dict[str, Any],
    *,
    record: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    group_answer_map: dict[str, str],
) -> dict[str, Any]:
    item_id = str(item.get("item_id") or f"{group_id}_q_{index:03d}")
    option_block_ids = [str(value) for value in item.get("option_block_ids") or []]
    options = str(item.get("options_markdown") or "")
    projection_notes: list[str] = []
    if group_kind(record) == "reading" and not options.strip():
        option_block_ids = reading_option_ids_from_field_roles(record, item, index)
        options = ids_markdown(option_block_ids, blocks_by_id)
        if option_block_ids:
            projection_notes.append("option_blocks_filled_from_normalized_field_roles")
    source_item_no = str(item.get("source_item_no") or "")
    item_kind = str(item.get("item_kind") or "unknown")
    if item_kind == "cloze_choice" and not options.strip():
        option_block_ids = cloze_option_ids_from_field_roles(record, item, index)
        options = ids_markdown(option_block_ids, blocks_by_id)
        if option_block_ids:
            projection_notes.append("cloze_option_block_filled_from_normalized_field_roles")
    question = strip_source_number_prefix(str(item.get("question_markdown") or ""), source_item_no)
    explanation = strip_source_number_prefix(str(item.get("explanation_markdown") or ""), source_item_no)
    if item_kind == "cloze_choice":
        question = render_cloze_numbered_blanks(question, source_item_no, group_answer_map)
        explanation = render_cloze_explanation_blanks(explanation, source_item_no, group_answer_map)
    child = {
        "item_id": f"{group_id}_q_{index:03d}",
        "source_item_id": item_id,
        "item_no": str(index),
        "source_item_no": source_item_no,
        "item_kind": item_kind,
        "anchor": str(item.get("anchor") or ""),
        "question": question,
        "options": strip_source_number_prefix(options, source_item_no),
        "response_area": str(item.get("response_area_markdown") or ""),
        "answer": str(item.get("answer_text") or ""),
        "explanation": explanation,
        "source_refs": {
            "question_block_ids": [str(value) for value in item.get("question_block_ids") or []],
            "option_block_ids": option_block_ids,
            "response_area_block_ids": [str(value) for value in item.get("response_area_block_ids") or []],
            "explanation_block_ids": [str(value) for value in item.get("explanation_block_ids") or []],
        },
        "projection_source": "model_itemizer",
        "projection_notes": projection_notes,
        "warnings": [],
    }
    if not child["answer"] and child["item_kind"] not in {"writing_task", "continuation_writing_task"}:
        child["warnings"].append("missing_child_answer_from_itemizer")
    if not child["explanation"] and child["item_kind"] not in {"writing_task", "continuation_writing_task"}:
        child["warnings"].append("missing_child_explanation_from_itemizer")
    return child


def render_cloze_numbered_blanks(text: str, source_item_no: str, answer_map: dict[str, str]) -> str:
    current = str(source_item_no or "").strip()
    try:
        current_num = int(current)
    except ValueError:
        current_num = -1

    def with_soft_spacing(original: str, start: int, end: int, value: str) -> str:
        before = original[start - 1] if start > 0 else ""
        after = original[end] if end < len(original) else ""
        if before.isalnum() and value and value[0] != " ":
            value = " " + value
        if after.isalnum() and value and not value.endswith(" "):
            value = value + " "
        return value

    def repl(match: re.Match[str]) -> str:
        blank_no = match.group(1)
        try:
            blank_num = int(blank_no)
        except ValueError:
            blank_num = -1
        if blank_no == current:
            value = f"[[CURRENT_BLANK_{blank_no}]]"
        elif current_num > 0 and blank_num > 0 and blank_num < current_num:
            answer = answer_map.get(blank_no, "")
            value = f"[[UNDERLINE_FILL_{blank_no}]]{answer}[[/UNDERLINE_FILL_{blank_no}]]" if answer else f"[[BLANK_{blank_no}]]"
        else:
            value = f"[[BLANK_{blank_no}]]"
        return with_soft_spacing(match.string, match.start(), match.end(), value)

    return CLOZE_UNDERSCORE_RE.sub(repl, str(text or ""))


def render_cloze_explanation_blanks(text: str, source_item_no: str, answer_map: dict[str, str]) -> str:
    current = str(source_item_no or "").strip()
    try:
        current_num = int(current)
    except ValueError:
        current_num = -1

    def with_soft_spacing(original: str, start: int, end: int, value: str) -> str:
        before = original[start - 1] if start > 0 else ""
        after = original[end] if end < len(original) else ""
        if before.isalnum() and value and value[0] != " ":
            value = " " + value
        if after.isalnum() and value and not value.endswith(" "):
            value = value + " "
        return value

    def repl(match: re.Match[str]) -> str:
        blank_no = match.group(1)
        try:
            blank_num = int(blank_no)
        except ValueError:
            blank_num = -1
        if current_num > 0 and blank_num > 0 and blank_num < current_num:
            answer = answer_map.get(blank_no, "")
            value = f"[[UNDERLINE_FILL_{blank_no}]]{answer}[[/UNDERLINE_FILL_{blank_no}]]" if answer else match.group(0)
            return with_soft_spacing(match.string, match.start(), match.end(), value)
        return match.group(0)

    return CLOZE_UNDERSCORE_RE.sub(repl, str(text or ""))


def answer_map_from_items(items: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source_no = str(item.get("source_item_no") or "").strip()
        answer = str(item.get("answer_text") or "").strip()
        if source_no and answer:
            if str(item.get("item_kind") or "") == "cloze_choice":
                out[source_no] = option_text_for_answer(str(item.get("options_markdown") or ""), answer) or answer
            else:
                out[source_no] = answer
    return out


def option_text_for_answer(options_markdown: str, answer: str) -> str:
    answer_label = str(answer or "").strip().split()[0].strip(".,;:，。；：")
    if not answer_label:
        return ""
    text = strip_source_number_prefix(str(options_markdown or ""), "")
    matches = list(OPTION_LABEL_RE.finditer(text))
    for index, match in enumerate(matches):
        label = match.group(1)
        if label != answer_label:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[start:end].strip()
    return ""


def strip_source_number_prefix(text: str, source_item_no: str) -> str:
    value = str(text or "")
    source_no = str(source_item_no or "").strip()
    if not source_no:
        return value
    detail_match = DETAIL_SOURCE_NO_RE.match(value)
    if detail_match and detail_match.group(2) == source_no:
        return value[: detail_match.start()] + detail_match.group(1) + value[detail_match.end() :]
    match = LEADING_SOURCE_NO_RE.match(value)
    if match and match.group(2) == source_no:
        return value[: match.start()] + match.group(1) + value[match.end() :]
    return value


def project_group(
    record: dict[str, Any],
    itemized_by_group: dict[str, dict[str, Any]],
    *,
    blocks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    group_id = str(record.get("group_id") or "")
    kind = group_kind(record)
    parent_fields = PARENT_FIELDS if kind in PARENT_ONLY_KINDS else PARENT_FIELDS_BY_KIND.get(kind, DEFAULT_CHILD_PARENT_FIELDS)
    projected = {
        "group_id": group_id,
        "parent_kind": kind,
        "projection_mode": "parent_only" if kind in PARENT_ONLY_KINDS else "parent_with_children",
        "parent": parent_fields_for(record, parent_fields),
        "children": [],
        "source_block_ids": record.get("source_block_ids") or [],
        "normalization_block_ids": record.get("normalization_block_ids") or [],
        "excluded_block_ids": record.get("excluded_block_ids") or [],
        "warnings": [],
        "projection_notes": [],
    }
    unknown_parent_field_policy(projected["parent"], projected["projection_notes"], projected["warnings"])
    if kind in PARENT_ONLY_KINDS:
        projected["projection_notes"].append("writing_group_kept_parent_only")
        return projected
    field_block_ids = record.get("field_block_ids") or {}
    if kind == "reading" and not field_block_ids.get("question_items"):
        projected["warnings"].append("reading_group_has_no_question_items_upstream_split_suspect")
        return projected
    if kind == "reading" and not field_block_ids.get("passage"):
        projected["warnings"].append("reading_group_has_no_passage_upstream_split_suspect")
    itemized = itemized_by_group.get(group_id)
    if not itemized:
        projected["warnings"].append("missing_model_itemizer_result")
        return projected
    items = [item for item in itemized.get("items") or [] if isinstance(item, dict)]
    group_answer_map = answer_map_from_items(items)
    projected["children"] = [
        child_from_item(group_id, index, item, record=record, blocks_by_id=blocks_by_id, group_answer_map=group_answer_map)
        for index, item in enumerate(items, start=1)
    ]
    if not projected["children"]:
        projected["warnings"].append("model_itemizer_returned_no_children")
    return projected


def render_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = UNDERLINE_FILL_RE.sub(
        lambda match: f'<u class="filled-blank" title="BLANK_{match.group(1)}">{match.group(2)}</u>',
        escaped,
    )
    escaped = CURRENT_BLANK_RE.sub(
        lambda match: f'<span class="current-blank" title="CURRENT_BLANK_{match.group(1)}"></span>',
        escaped,
    )
    escaped = BLANK_RE.sub(lambda match: f'<span class="blank" title="BLANK_{match.group(1)}"></span>', escaped)
    escaped = escaped.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
    escaped = escaped.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>").replace("&lt;br /&gt;", "<br>")
    return escaped


def render_response_box(index: str, chars: int) -> str:
    line_count = max(3, min(14, round(chars / 72)))
    lines = "".join('<div class="write-line"></div>' for _ in range(line_count))
    return f'<div class="response-box"><div class="response-meta">作答区 {html.escape(index)} · {chars} chars</div>{lines}</div>'


def split_markdown_table_row(line: str) -> list[str]:
    value = str(line or "").strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def is_markdown_table_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    for cell in cells:
        marker = cell.strip()
        if not marker or any(char not in "-: " for char in marker) or "-" not in marker:
            return False
    return True


def markdown_table_lines(block: str) -> list[str]:
    lines = [line.strip() for line in str(block or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = split_markdown_table_row(lines[0])
    separator = split_markdown_table_row(lines[1])
    if len(header) < 2 or len(separator) != len(header):
        return []
    if not is_markdown_table_separator(separator):
        return []
    for line in lines:
        if "|" not in line:
            return []
    return lines


def render_markdown_table(lines: list[str]) -> str:
    header = split_markdown_table_row(lines[0])
    body_rows = [split_markdown_table_row(line) for line in lines[2:]]
    width = len(header)
    head_html = "".join(f"<th>{render_inline(cell)}</th>" for cell in header)
    rows_html: list[str] = []
    for row in body_rows:
        cells = (row + [""] * width)[:width]
        rows_html.append("<tr>" + "".join(f"<td>{render_inline(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="md-table-wrap"><table class="md-table">'
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )


def render_text(text: str) -> str:
    pieces: list[str] = []
    for para in re.split(r"\n{2,}", str(text or "").strip()):
        if not para.strip():
            continue
        table_lines = markdown_table_lines(para)
        if table_lines:
            pieces.append(render_markdown_table(table_lines))
            continue
        cursor = 0
        local: list[str] = []
        for match in RESPONSE_RE.finditer(para):
            before = para[cursor : match.start()]
            if before.strip():
                local.append(f"<p>{render_inline(before.strip())}</p>")
            local.append(render_response_box(match.group(1), int(match.group(2))))
            cursor = match.end()
        after = para[cursor:]
        if after.strip():
            local.append(f"<p>{render_inline(after.strip())}</p>")
        pieces.extend(local)
    return "\n".join(pieces) or '<p class="muted">(empty)</p>'


def label_for_field(field: str) -> str:
    return {
        "source_label": "来源/标题",
        "instruction": "说明/题干要求",
        "passage": "文章/材料",
        "options": "共享选项",
        "response_area": "作答区",
        "answer": "答案",
        "guide": "导语",
        "explanation": "解析",
        "sample_answer": "范文/示例答案",
        "teaching_note": "知识点/教学标签",
        "unknown": "未归类",
    }.get(field, field)


def render_field(label: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {html.escape(class_name)}"><h3>{html.escape(label)}</h3>{render_text(text)}</section>'


def render_group(group: dict[str, Any]) -> str:
    parent = group.get("parent") or {}
    parent_html = "".join(render_field(label_for_field(key), value, f"parent-{key}") for key, value in parent.items())
    children_html = []
    for child in group.get("children") or []:
        warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in child.get("warnings") or [])
        children_html.append(
            '<article class="child">'
            f'<h4>第 {html.escape(str(child.get("item_no") or ""))} 题 '
            f'<span>原始 {html.escape(str(child.get("source_item_no") or ""))} · {html.escape(str(child.get("item_kind") or ""))}</span></h4>'
            f'{render_field("题目", child.get("question") or "")}'
            f'{render_field("选项", child.get("options") or "")}'
            f'{render_field("作答区", child.get("response_area") or "")}'
            f'{render_field("答案", child.get("answer") or "", "answerish")}'
            f'{render_field("解析", child.get("explanation") or "", "answerish")}'
            + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
            + "</article>"
        )
    warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in group.get("warnings") or [])
    note_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in group.get("projection_notes") or [])
    return (
        f'<article class="group" id="{html.escape(str(group.get("group_id") or ""))}">'
        f'<h2>{html.escape(str(group.get("group_id") or ""))} '
        f'<span>{html.escape(str(group.get("parent_kind") or ""))} · {html.escape(str(group.get("projection_mode") or ""))} · children={len(group.get("children") or [])}</span></h2>'
        f'<div class="meta">原始块 {len(group.get("source_block_ids") or [])} · 入题块 {len(group.get("normalization_block_ids") or [])} · 隔离块 {len(group.get("excluded_block_ids") or [])}</div>'
        + (f'<ul class="notes">{note_html}</ul>' if note_html else "")
        + (f'<ul class="warnings">{warning_html}</ul>' if warning_html else "")
        + f'<div class="parent">{parent_html}</div>'
        + f'<div class="children">{"".join(children_html)}</div>'
        + "</article>"
    )


def render_index(payload: dict[str, Any], out_path: Path) -> None:
    records = payload.get("records") or []
    nav = "".join(
        f'<a href="#{html.escape(str(group.get("group_id") or ""))}"><b>{html.escape(str(group.get("group_id") or ""))}</b>'
        f'<span>{html.escape(str(group.get("parent_kind") or ""))} · {len(group.get("children") or [])}</span></a>'
        for group in records
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
h2 span,h4 span{color:#667085;font-size:13px;font-weight:500}
.meta{color:#536174;font:13px/1.5 Arial,sans-serif;margin-bottom:12px}
.field{border-top:1px solid #e4eaf2;margin-top:10px;padding-top:10px}
.field h3{margin:0 0 6px;color:#0f766e;font:700 14px/1.35 "Microsoft YaHei",sans-serif}
.field p{margin:6px 0;white-space:pre-wrap}
.md-table-wrap{overflow-x:auto;margin:8px 0 12px}.md-table{width:100%;border-collapse:collapse;background:#fff;font-size:15px;line-height:1.55}.md-table th,.md-table td{border:1px solid #d7e0ec;padding:8px 10px;vertical-align:top;text-align:left}.md-table th{background:#eef4fb;font-weight:700;color:#0f2742}.md-table tbody tr:nth-child(even){background:#fbfdff}
.children{display:grid;gap:12px;margin-top:16px}
.child{padding:13px 15px;background:#fff;border:1px solid #d8dee8;border-radius:7px}
h4{margin:0 0 8px;color:#1d4ed8;font:700 15px/1.35 "Microsoft YaHei",sans-serif}
.answerish{background:#fff9ed}
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
        f'<title>{html.escape(str(payload.get("doc_id") or ""))} parent child projection v02</title>'
        f"<style>{css}</style></head><body><div class=\"layout\"><nav><h2>题组</h2>{nav}</nav><main>"
        f'<header><h1>{html.escape(str(payload.get("doc_id") or ""))} 父子投影 v02</h1>'
        f'<p class="meta">groups={len(records)} · children={sum(len(group.get("children") or []) for group in records)} · parent_only={sum(1 for group in records if group.get("projection_mode") == "parent_only")}</p></header>'
        + "".join(render_group(group) for group in records)
        + "</main></div></body></html>"
    )
    out_path.write_text(html_doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-normalized", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    normalized = read_json(args.input_normalized)
    itemized = read_json(args.itemized)
    source_block_stream = Path(str(normalized.get("source_block_stream") or ""))
    if not source_block_stream.is_absolute():
        source_block_stream = ROOT / source_block_stream
    blocks_by_id = load_blocks(source_block_stream)
    itemized_by_group = itemized_records_by_group(itemized)
    records = [
        project_group(record, itemized_by_group, blocks_by_id=blocks_by_id)
        for record in normalized.get("records") or []
        if isinstance(record, dict)
    ]
    payload = {
        "schema_version": "english_docx_parent_child_projection.v0.2",
        "doc_id": normalized.get("doc_id"),
        "source_normalized_groups": safe_rel(args.input_normalized),
        "source_itemized_groups": safe_rel(args.itemized),
        "records": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "parent_child_projection.json", payload)
    summary = {
        "schema_version": "english_docx_parent_child_projection_summary.v0.2",
        "doc_id": normalized.get("doc_id"),
        "group_count": len(records),
        "child_count": sum(len(record.get("children") or []) for record in records),
        "parent_only_count": sum(1 for record in records if record.get("projection_mode") == "parent_only"),
        "warning_count": sum(
            len(record.get("warnings") or [])
            + sum(len(child.get("warnings") or []) for child in record.get("children") or [])
            for record in records
        ),
        "artifacts": {
            "projection": safe_rel(args.output_dir / "parent_child_projection.json"),
            "index": safe_rel(args.output_dir / "index.html"),
            "summary": safe_rel(args.output_dir / "summary.json"),
        },
    }
    write_json(args.output_dir / "summary.json", summary)
    render_index(payload, args.output_dir / "index.html")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
