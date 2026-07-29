#!/usr/bin/env python3
"""Project locally numbered English groups into parent/child views."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


BLANK_RE = re.compile(r"\[\[BLANK_(\d+)\]\]")
CURRENT_BLANK_RE = re.compile(r"\[\[CURRENT_BLANK_(\d+)\]\]")
RESPONSE_RE = re.compile(r"\[\[RESPONSE_AREA_(\d+)\s+chars=(\d+)\]\]")
OPTION_LABEL_RE = re.compile(r"(?<![A-Za-z])([A-H])\.\s*")
OPTION_ROW_RE = re.compile(r"^\s*(\d+)\s*[.．、)]\s*(.*)$")

PARENT_FIELDS = ["source_label", "instruction", "passage", "options", "guide", "teaching_note"]
CHILD_FIELD_LABELS = {
    "question": "题目",
    "options": "选项",
    "response_area": "作答区",
    "answer": "答案",
    "explanation": "解析",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_options(markdown: str) -> dict[str, str]:
    text = re.sub(r"^\s*\d+\s*[.．、)]\s*", "", str(markdown or "").strip())
    matches = list(OPTION_LABEL_RE.finditer(text))
    options: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip()
        if value:
            options[label] = value
    return options


def parse_option_rows(markdown: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in str(markdown or "").splitlines():
        match = OPTION_ROW_RE.match(line.strip())
        if not match:
            continue
        item_no = match.group(1)
        options = parse_options(match.group(2))
        if options:
            rows[item_no] = options
    return rows


def option_fill_text(item: dict[str, Any], option_bank: dict[str, str]) -> str:
    answer = str(item.get("answer_text") or "").strip()
    if not answer:
        return ""
    letter = answer.split()[0].strip(".,;:，。；：")
    if letter in option_bank:
        return option_bank[letter]
    return answer


def build_fill_map(items: list[dict[str, Any]], parent_options: str) -> dict[str, str]:
    shared_option_bank = parse_options(parent_options)
    option_rows = parse_option_rows(parent_options)
    fill_map: dict[str, str] = {}
    for item in items:
        source_no = str(item.get("source_item_no") or "").strip()
        item_no = str(item.get("item_no") or "").strip()
        if not source_no:
            continue
        item_kind = str(item.get("item_kind") or "")
        if item_kind in {"cloze_choice", "reading_question"}:
            bank = parse_options(item.get("options_markdown") or "") or option_rows.get(item_no) or shared_option_bank
            fill_map[source_no] = option_fill_text(item, bank)
        elif item_kind == "seven_choice_blank":
            fill_map[source_no] = option_fill_text(item, shared_option_bank)
        else:
            fill_map[source_no] = str(item.get("answer_text") or "").strip()
    return {key: value for key, value in fill_map.items() if value}


def fill_question_blanks(text: str, *, current_source_no: str, fill_map: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        blank_no = match.group(1)
        if blank_no == current_source_no:
            value = f"[[CURRENT_BLANK_{blank_no}]]"
        else:
            value = fill_map.get(blank_no, f"[[FILLED_BLANK_{blank_no}]]")
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        is_token = value.startswith("[[") and value.endswith("]]")
        if before.isalnum() and value and (is_token or value[0].isalnum()):
            value = " " + value
        if after.isalnum() and value and (is_token or value[-1].isalnum()):
            value = value + " "
        return value

    return BLANK_RE.sub(repl, str(text or ""))


def localize_leading_number(text: str, source_no: str, item_no: str) -> str:
    value = str(text or "")
    if not source_no or not item_no or source_no == item_no:
        return value
    patterns = [
        (f"{source_no}.", f"{item_no}."),
        (f"{source_no}．", f"{item_no}．"),
        (f"{source_no}、", f"{item_no}、"),
        (f"({source_no})", f"({item_no})"),
        (f"（{source_no}）", f"（{item_no}）"),
    ]
    stripped_len = len(value) - len(value.lstrip())
    prefix = value[:stripped_len]
    body = value[stripped_len:]
    for old, new in patterns:
        if body.startswith(old):
            return prefix + new + body[len(old) :]
    return value


def render_options_for_child(item: dict[str, Any], parent_option_rows: dict[str, dict[str, str]]) -> str:
    option_md = str(item.get("options_markdown") or "")
    options = parse_options(option_md)
    if not options:
        options = parent_option_rows.get(str(item.get("item_no") or "").strip()) or {}
    if not options:
        return localize_leading_number(
            option_md,
            str(item.get("source_item_no") or ""),
            str(item.get("item_no") or ""),
        )
    bits = [f"{item.get('item_no')}."] if item.get("item_no") else []
    bits.extend(f"{label}. {value}" for label, value in options.items())
    return "    ".join(bits)


def child_from_item(item: dict[str, Any], fill_map: dict[str, str], parent_option_rows: dict[str, dict[str, str]]) -> dict[str, Any]:
    source_no = str(item.get("source_item_no") or "").strip()
    item_no = str(item.get("item_no") or "").strip()
    question = fill_question_blanks(item.get("question_markdown") or "", current_source_no=source_no, fill_map=fill_map)
    question = localize_leading_number(question, source_no, item_no)
    explanation = localize_leading_number(str(item.get("explanation_markdown") or ""), source_no, item_no)
    return {
        "item_id": item.get("item_id"),
        "item_no": item_no,
        "source_item_no": source_no,
        "item_kind": item.get("item_kind"),
        "anchor": item.get("anchor"),
        "question": question,
        "options": render_options_for_child(item, parent_option_rows),
        "response_area": item.get("response_area_markdown") or "",
        "answer": item.get("answer_text") or "",
        "explanation": explanation,
        "fill_strategy": "non_current_blanks_filled_from_answers_or_option_text",
    }


def project_group(local_record: dict[str, Any], item_record: dict[str, Any]) -> dict[str, Any]:
    parent_fields = local_record.get("fields") or {}
    items = item_record.get("items") or []
    fill_map = build_fill_map(items, parent_fields.get("options") or "")
    parent_option_rows = parse_option_rows(parent_fields.get("options") or "")
    return {
        "group_id": local_record.get("group_id"),
        "parent_kind": item_record.get("parent_kind") or local_record.get("parent_kind"),
        "parent": {field: parent_fields.get(field) or "" for field in PARENT_FIELDS if parent_fields.get(field)},
        "children": [child_from_item(item, fill_map, parent_option_rows) for item in items],
    }


def render_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = CURRENT_BLANK_RE.sub(
        lambda m: f'<span class="current-blank" title="CURRENT_BLANK_{m.group(1)}"></span>',
        escaped,
    )
    escaped = BLANK_RE.sub(
        lambda m: f'<span class="blank" title="BLANK_{m.group(1)}"></span>',
        escaped,
    )
    return escaped


def response_box(index: str, chars: int) -> str:
    line_count = max(3, min(12, round(chars / 72)))
    lines = "".join('<div class="write-line"></div>' for _ in range(line_count))
    return f'<div class="response-box"><div class="response-meta">作答区 {html.escape(index)} · {chars} chars</div>{lines}</div>'


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


def render_field(label: str, text: str, class_name: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<section class="field {class_name}"><h3>{html.escape(label)}</h3>{render_text(text)}</section>'


def render_group(group: dict[str, Any]) -> str:
    parent = group.get("parent") or {}
    parent_html = "".join(render_field(key, value) for key, value in parent.items())
    children_html: list[str] = []
    for child in group.get("children") or []:
        parts = [
            render_field(CHILD_FIELD_LABELS["question"], child.get("question") or ""),
            render_field(CHILD_FIELD_LABELS["options"], child.get("options") or ""),
            render_field(CHILD_FIELD_LABELS["response_area"], child.get("response_area") or ""),
            render_field(CHILD_FIELD_LABELS["answer"], child.get("answer") or "", "answerish"),
            render_field(CHILD_FIELD_LABELS["explanation"], child.get("explanation") or "", "answerish"),
        ]
        children_html.append(
            '<article class="child">'
            f'<h4>第 {html.escape(str(child.get("item_no") or ""))} 题 '
            f'<span>{html.escape(str(child.get("item_kind") or ""))}</span></h4>'
            f'{"".join(parts)}'
            "</article>"
        )
    return (
        '<article class="group">'
        f'<h2>{html.escape(str(group.get("group_id") or ""))} '
        f'<span>{html.escape(str(group.get("parent_kind") or ""))} · children={len(group.get("children") or [])}</span></h2>'
        f'<div class="parent">{parent_html}</div>'
        f'<div class="children">{"".join(children_html)}</div>'
        "</article>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-numbered", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--only-groups", default="")
    parser.add_argument("--only-items", default="")
    args = parser.parse_args()
    local_numbered = read_json(args.local_numbered)
    itemized = read_json(args.itemized)
    local_by_id = {record.get("group_id"): record for record in local_numbered.get("records") or []}
    wanted = {item.strip() for item in args.only_groups.split(",") if item.strip()}
    wanted_items = {item.strip() for item in args.only_items.split(",") if item.strip()}
    groups = []
    for item_record in itemized.get("records") or []:
        group_id = item_record.get("group_id")
        if wanted and group_id not in wanted:
            continue
        if group_id in local_by_id:
            group = project_group(local_by_id[group_id], item_record)
            if wanted_items:
                group["children"] = [
                    child
                    for child in group.get("children") or []
                    if str(child.get("item_no") or "") in wanted_items
                ]
            groups.append(group)
    payload = {
        "schema_version": "english_docx_parent_child_split_projection.v0.1",
        "doc_id": local_numbered.get("doc_id"),
        "source_local_numbered_groups": str(args.local_numbered),
        "source_itemized_groups": str(args.itemized),
        "records": groups,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "parent_child_groups.json", payload)
    html_doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(str(local_numbered.get("doc_id") or ""))} · parent child split</title>
<style>
body{{margin:0;background:#eef2f5;color:#1f2933;font:16px/1.72 "Times New Roman","Microsoft YaHei",serif}}
header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #d0d7de;padding:14px 28px;z-index:2}}
h1{{margin:0;font:600 18px/1.35 "Microsoft YaHei",sans-serif}}
main{{width:min(1120px,calc(100vw - 32px));margin:22px auto 56px}}
.group{{margin:0 0 22px;padding:22px 26px;background:#fffefa;border:1px solid #d0d7de;border-radius:6px}}
h2{{margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid #d0d7de;font:700 20px/1.3 "Microsoft YaHei",sans-serif}}
h2 span,h4 span{{color:#667085;font-size:13px;font-weight:500}}
h3{{margin:12px 0 5px;color:#0f766e;font:700 14px/1.35 "Microsoft YaHei",sans-serif}}
h4{{margin:0 0 9px;color:#1d4ed8;font:700 15px/1.35 "Microsoft YaHei",sans-serif}}
p{{margin:6px 0;white-space:pre-wrap}}
.children{{display:grid;gap:10px;margin-top:16px}}
.child{{padding:12px 14px;background:#fff;border:1px solid #d8dee5;border-radius:6px}}
.answerish{{color:#8a4b00}}
.current-blank{{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:2px solid #111827;vertical-align:-.08em;background:#fff7cc}}
.blank{{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:1.5px solid #111827;vertical-align:-.08em}}
.response-box{{margin:8px 0 12px;padding:8px 0 2px;border:1px solid #d8dee5;border-radius:4px;background:#fff}}
.response-meta{{padding:0 12px 4px;color:#667085;font:12px/1.3 "Microsoft YaHei",sans-serif}}
.write-line{{height:30px;margin:0 12px;border-bottom:1px solid #333}}
</style></head><body><header><h1>{html.escape(str(local_numbered.get("doc_id") or ""))} · 父子拆开预览</h1></header><main>{"".join(render_group(group) for group in groups)}</main></body></html>"""
    (args.output_dir / "index.html").write_text(html_doc, encoding="utf-8")
    summary = {
        "doc_id": local_numbered.get("doc_id"),
        "group_count": len(groups),
        "child_count": sum(len(group.get("children") or []) for group in groups),
        "artifacts": {
            "parent_child_groups": str(args.output_dir / "parent_child_groups.json"),
            "index": str(args.output_dir / "index.html"),
        },
    }
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
