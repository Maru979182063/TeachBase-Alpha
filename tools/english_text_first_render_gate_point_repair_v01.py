from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover - optional during local bring-up
    Draft202012Validator = None  # type: ignore[assignment]

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


GATE_VERSION = "english_render_gate_point_repair_v0.1_md_contract_20260722"
DISPLAY_FIELDS = [
    "stem_markdown",
    "answer_markdown",
    "analysis_markdown",
    "translation_markdown",
    "context_markdown",
]
SOURCE_FIELDS = ["stem", "answer", "analysis", "translation", "context"]


def normalize_text(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = lowered.replace("&nbsp;", " ")
    return re.sub(r"[\s`*_#|:：,，.。;；!！?？()（）\[\]{}<>/\\\-—–\"'“”‘’]+", "", lowered)


def significant_segment(text: str) -> bool:
    norm = normalize_text(text)
    return len(norm) >= 18


def split_segments(text: str) -> list[str]:
    """Return source-backed chunks large enough for field-boundary checks.

    This deliberately uses generic line/paragraph segmentation, not question
    type keywords. It only answers: did a chunk from one field move into
    another field?
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    candidates: list[str] = []
    for para in re.split(r"\n\s*\n+", raw):
        para = para.strip()
        if para:
            candidates.append(para)
    for line in raw.splitlines():
        line = line.strip()
        if line:
            candidates.append(line)
    out: list[str] = []
    seen: set[str] = set()
    for segment in candidates:
        norm = normalize_text(segment)
        if significant_segment(segment) and norm not in seen:
            seen.add(norm)
            out.append(segment)
    out.sort(key=len, reverse=True)
    return out


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    if not cells:
        return False
    for cell in cells:
        value = cell.strip()
        if not value:
            return False
        if not re.fullmatch(r":?-{3,}:?", value):
            return False
    return True


def render_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def repair_markdown_tables(markdown: str) -> tuple[str, list[dict[str, Any]]]:
    lines = str(markdown or "").splitlines()
    out: list[str] = []
    repairs: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            start_line = i + 1
            header = split_table_row(line)
            width = max(1, len(header))
            table_lines = [render_table_row(header), render_table_row(["----"] * width)]
            original_lines = [line, lines[i + 1]]
            i += 2
            changed = table_lines[0] != original_lines[0] or table_lines[1] != original_lines[1]
            while i < len(lines) and lines[i].strip().startswith("|"):
                original = lines[i]
                cells = split_table_row(original)
                before = cells[:]
                if len(cells) > width:
                    cells = cells[: width - 1] + [" ".join(cell for cell in cells[width - 1 :] if cell).strip()]
                if len(cells) < width:
                    cells.extend([""] * (width - len(cells)))
                table_lines.append(render_table_row(cells))
                changed = changed or cells != before or table_lines[-1] != original
                original_lines.append(original)
                i += 1
            out.extend(table_lines)
            if changed:
                repairs.append(
                    {
                        "risk_code": "markdown_table_invalid",
                        "line_start": start_line,
                        "line_end": start_line + len(original_lines) - 1,
                        "message": "Markdown table rows normalized to the header column count.",
                    }
                )
            continue
        out.append(line)
        i += 1
    return "\n".join(out), repairs


def markdown_table_issues(markdown: str) -> list[dict[str, Any]]:
    lines = str(markdown or "").splitlines()
    issues: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|"):
            if i + 1 >= len(lines) or not is_table_separator(lines[i + 1]):
                issues.append(
                    {
                        "risk_code": "markdown_table_missing_separator",
                        "line": i + 1,
                        "message": "A pipe-style Markdown table row is not followed by a valid separator row.",
                    }
                )
                i += 1
                continue
            width = len(split_table_row(line))
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                row_width = len(split_table_row(lines[j]))
                if row_width != width:
                    issues.append(
                        {
                            "risk_code": "markdown_table_column_mismatch",
                            "line": j + 1,
                            "expected_columns": width,
                            "actual_columns": row_width,
                            "message": "Markdown table row column count differs from header.",
                        }
                    )
                j += 1
            i = j
            continue
        i += 1
    return issues


def markdown_parse_issues(markdown: str, field_path: str, md: MarkdownIt) -> list[dict[str, Any]]:
    try:
        md.parse(str(markdown or ""))
        return []
    except Exception as exc:
        return [
            {
                "risk_code": "markdown_parse_error",
                "field_path": field_path,
                "message": str(exc),
        }
        ]


def is_table_like_line(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    cells = split_table_row(stripped)
    return len([cell for cell in cells if cell.strip()]) >= 2


def table_like_blocks(markdown: str) -> list[dict[str, Any]]:
    lines = str(markdown or "").splitlines()
    blocks: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if not is_table_like_line(lines[i]):
            i += 1
            continue
        start = i
        block_lines: list[str] = []
        while i < len(lines) and (is_table_like_line(lines[i]) or is_table_separator(lines[i])):
            block_lines.append(lines[i])
            i += 1
        table_like_count = sum(1 for line in block_lines if is_table_like_line(line))
        if table_like_count >= 2:
            blocks.append({"line_start": start + 1, "line_end": i, "markdown": "\n".join(block_lines)})
    return blocks


def markdown_render_issues(markdown: str, field_path: str, md: MarkdownIt) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for block in table_like_blocks(markdown):
        rendered = md.render(block["markdown"])
        if "<table" not in rendered:
            issues.append(
                {
                    "risk_code": "markdown_table_not_rendered",
                    "field_path": field_path,
                    "line_start": block["line_start"],
                    "line_end": block["line_end"],
                    "severity": "error",
                    "message": "Table-like Markdown did not render as an HTML table.",
                    "source_span": block["markdown"],
                }
            )
    return issues


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        return payload
    for key in ["records", "verified_records", "rendered_records"]:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def load_packets(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("refined_packets") or payload.get("packets") or payload.get("records") or []
    return {str(item.get("source_group_id") or ""): item for item in items if isinstance(item, dict)}


def load_schema_validator() -> Any | None:
    if Draft202012Validator is None:
        return None
    schema_path = workspace_path("schemas/rendered_question_record.schema.json")
    if not schema_path.exists():
        return None
    return Draft202012Validator(read_json(schema_path))


def standard_fields(packet: dict[str, Any]) -> dict[str, str]:
    q = packet.get("standard_question") or {}
    return {field: str(q.get(field) or "") for field in SOURCE_FIELDS}


def display_fields(record: dict[str, Any]) -> dict[str, str]:
    display = (record.get("rendered_record") or record).get("display_question") or {}
    return {field: str(display.get(field) or "") for field in DISPLAY_FIELDS}


def find_span(text: str, segment: str) -> tuple[int, int] | None:
    if not text or not segment:
        return None
    pos = text.find(segment)
    if pos >= 0:
        return pos, pos + len(segment)
    text_norm = normalize_text(text)
    seg_norm = normalize_text(segment)
    if not seg_norm or seg_norm not in text_norm:
        return None
    return None


def field_boundary_tasks(record: dict[str, Any], packet: dict[str, Any]) -> list[dict[str, Any]]:
    fields = standard_fields(packet)
    display = display_fields(record)
    stem = display.get("stem_markdown") or ""
    stem_source_norm = normalize_text(fields.get("stem") or "")
    tasks: list[dict[str, Any]] = []
    for source_field in ["context", "translation", "answer", "analysis"]:
        source_text = fields.get(source_field) or ""
        if not source_text.strip():
            continue
        for segment in split_segments(source_text):
            seg_norm = normalize_text(segment)
            if not seg_norm or seg_norm in stem_source_norm:
                continue
            span = find_span(stem, segment)
            if not span:
                continue
            start, end = span
            if source_field == "context":
                risk_code = "context_in_stem"
                target_field = "display_question.context_markdown"
                severity = "warning"
            elif source_field == "translation":
                risk_code = "translation_in_stem"
                target_field = "display_question.translation_markdown"
                severity = "error"
            elif source_field == "answer":
                risk_code = "answer_contaminates_stem"
                target_field = "display_question.answer_markdown"
                severity = "error"
            else:
                risk_code = "analysis_in_stem"
                target_field = "display_question.analysis_markdown"
                severity = "error"
            tasks.append(
                {
                    "risk_code": risk_code,
                    "severity": severity,
                    "field_path": "display_question.stem_markdown",
                    "char_start": start,
                    "char_end": end,
                    "source_span": stem[start:end],
                    "source_standard_field": f"standard_question.{source_field}",
                    "suggested_target_field": target_field,
                    "suggested_action": "move_or_remove_from_stem",
                    "message": f"Text from standard_question.{source_field} appears in display stem.",
                }
            )
    tasks.sort(key=lambda item: (int(item["char_start"]), -int(item["char_end"])))
    deduped: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for task in tasks:
        start, end = int(task["char_start"]), int(task["char_end"])
        if any(not (end <= a or start >= b) for a, b in occupied):
            continue
        occupied.append((start, end))
        task["task_id"] = f"ep_{len(deduped) + 1:04d}"
        deduped.append(task)
    return deduped


def line_safe_boundary_repairs(record: dict[str, Any], tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rendered = record.get("rendered_record") or record
    display = rendered.setdefault("display_question", {})
    stem = str(display.get("stem_markdown") or "")
    lines = stem.splitlines(keepends=True)
    line_offsets: list[tuple[int, int, str]] = []
    pos = 0
    for line in lines:
        line_offsets.append((pos, pos + len(line), line))
        pos += len(line)
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    remove_ranges: list[tuple[int, int, dict[str, Any]]] = []
    for task in tasks:
        start, end = int(task["char_start"]), int(task["char_end"])
        matching_line = None
        for line_start, line_end, line in line_offsets:
            stripped = line.strip()
            if start >= line_start and end <= line_end and stripped == str(task.get("source_span") or "").strip():
                matching_line = (line_start, line_end, line)
                break
        if matching_line is None:
            rejected.append({**task, "reason": "not_line_exact_safe"})
            continue
        remove_ranges.append((matching_line[0], matching_line[1], task))
    if not remove_ranges:
        return applied, rejected
    remove_ranges.sort(key=lambda item: item[0], reverse=True)
    current = stem
    for start, end, task in remove_ranges:
        if current[start:end].strip() != str(task.get("source_span") or "").strip():
            rejected.append({**task, "reason": "offset_mismatch_after_previous_patch"})
            continue
        current = current[:start] + current[end:]
        applied.append(
            {
                "task_id": task["task_id"],
                "risk_code": task["risk_code"],
                "field_path": task["field_path"],
                "char_start": start,
                "char_end": end,
                "action": "remove_exact_line_from_stem",
            }
        )
    display["stem_markdown"] = current.strip()
    return applied, rejected


def normalize_non_direct_material_display(rendered_record: dict[str, Any]) -> list[dict[str, Any]]:
    admission = rendered_record.get("admission_profile") or {}
    if str(admission.get("builder_action") or "") != "do_not_build_direct_packet":
        return []
    display = rendered_record.setdefault("display_question", {})
    repairs: list[dict[str, Any]] = []
    if display.get("items"):
        display["items"] = []
        repairs.append(
            {
                "risk_code": "non_direct_material_had_items",
                "action": "clear_non_direct_items",
                "message": "Cleared display_question.items because this record is non-direct material.",
            }
        )
    for field in ["answer_markdown", "analysis_markdown", "translation_markdown"]:
        if str(display.get(field) or "").strip():
            display[field] = ""
            repairs.append(
                {
                    "risk_code": "non_direct_material_field_cleanup",
                    "action": f"clear_{field}",
                    "field_path": f"display_question.{field}",
                    "message": f"Cleared {field} because this record is non-direct material.",
                }
            )
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    changed_blocks = [block for block in rendering_blocks if block != "question_items"]
    if "material_card" not in changed_blocks:
        changed_blocks.insert(0, "material_card")
    if changed_blocks != rendering_blocks:
        display["rendering_blocks"] = changed_blocks
        repairs.append(
            {
                "risk_code": "non_direct_material_rendering_block",
                "action": "set_material_card_rendering_block",
                "message": "Marked this record as a material card rather than a question item surface.",
            }
        )
    return repairs


def schema_issues(rendered_record: dict[str, Any], validator: Any | None) -> list[dict[str, Any]]:
    if validator is None:
        return []
    issues = []
    for err in sorted(validator.iter_errors(rendered_record), key=lambda e: list(e.path)):
        issues.append(
            {
                "risk_code": "rendered_record_schema_invalid",
                "path": "$" + "".join(f".{part}" for part in err.path),
                "message": err.message,
            }
        )
    return issues


def gate_one(item: dict[str, Any], packet: dict[str, Any], validator: Any | None, md: MarkdownIt, apply_repairs: bool) -> dict[str, Any]:
    repaired_item = copy.deepcopy(item)
    rendered_record = repaired_item.get("rendered_record") or repaired_item
    display = rendered_record.setdefault("display_question", {})
    render_md = MarkdownIt("default", {"html": True})
    issues: list[dict[str, Any]] = []
    repair_tasks: list[dict[str, Any]] = []
    applied_repairs: list[dict[str, Any]] = []
    rejected_repairs: list[dict[str, Any]] = []

    issues.extend(schema_issues(rendered_record, validator))
    admission = rendered_record.get("admission_profile") or {}
    builder_action = str(admission.get("builder_action") or "")
    direct_import_allowed = bool(admission.get("direct_import_allowed"))
    refine_status = str(packet.get("refine_status") or "")
    is_non_direct_material = builder_action == "do_not_build_direct_packet" or refine_status == "PRESERVED_NON_DIRECT"

    for field in DISPLAY_FIELDS:
        field_path = f"display_question.{field}"
        markdown = str(display.get(field) or "")
        if apply_repairs:
            repaired, table_repairs = repair_markdown_tables(markdown)
            if table_repairs:
                display[field] = repaired
                markdown = repaired
                for repair in table_repairs:
                    applied_repairs.append({**repair, "field_path": field_path, "action": "normalize_markdown_table"})
        issues.extend(markdown_parse_issues(markdown, field_path, md))
        for table_issue in markdown_table_issues(markdown):
            issues.append({**table_issue, "field_path": field_path})
        issues.extend(markdown_render_issues(markdown, field_path, render_md))

    boundary_tasks = [] if is_non_direct_material else field_boundary_tasks(repaired_item, packet)
    repair_tasks.extend(boundary_tasks)
    issues.extend({**task, "message": task["message"]} for task in boundary_tasks)
    repairable_boundary_tasks = [task for task in boundary_tasks if task.get("severity") == "error"]
    if apply_repairs and repairable_boundary_tasks:
        applied, rejected = line_safe_boundary_repairs(repaired_item, repairable_boundary_tasks)
        applied_repairs.extend(applied)
        rejected_repairs.extend(rejected)

    if builder_action == "do_not_build_direct_packet" or refine_status == "PRESERVED_NON_DIRECT":
        issues.append(
            {
                "risk_code": "non_direct_material_review_only",
                "severity": "info",
                "message": "This record is upstream-preserved non-direct material and must be reviewed/rendered as material, not as an importable standalone question.",
            }
        )
        if direct_import_allowed:
            issues.append(
                {
                    "risk_code": "non_direct_marked_importable",
                    "message": "Non-direct packet is marked direct_import_allowed.",
                }
            )
        admission["direct_import_allowed"] = False
        rendered_record["admission_profile"] = admission
        if apply_repairs:
            applied_repairs.extend(normalize_non_direct_material_display(rendered_record))

    format_valid = not any(str(issue.get("risk_code") or "").startswith("markdown_") for issue in issues)
    field_contract_valid = not any(
        issue.get("risk_code") in {"translation_in_stem", "answer_contaminates_stem", "analysis_in_stem"}
        and issue.get("severity") != "warning"
        for issue in issues
    )
    admission_contract_valid = not any(issue.get("risk_code") == "non_direct_marked_importable" for issue in issues)
    schema_valid = not any(issue.get("risk_code") == "rendered_record_schema_invalid" for issue in issues)

    if not schema_valid:
        gate_bucket = "schema_error"
    elif not format_valid:
        gate_bucket = "format_error"
    elif not field_contract_valid:
        gate_bucket = "field_contract_error"
    elif not admission_contract_valid:
        gate_bucket = "admission_contract_error"
    elif rendered_record.get("render_status") != "READY":
        gate_bucket = "review_required"
    elif bool((rendered_record.get("admission_profile") or {}).get("direct_import_allowed")):
        gate_bucket = "importable_question"
    elif (rendered_record.get("admission_profile") or {}).get("builder_action") in {
        "build_child_packet_with_parent_context",
        "build_packet_with_visual_parent_or_source_page",
        "build_example_child_under_parent",
    }:
        gate_bucket = "relation_or_surface_required"
    else:
        gate_bucket = "material_or_parent_only"

    rendered_record.setdefault("normalization_actions", [])
    for repair in applied_repairs:
        action = f"node6d:{repair.get('action') or repair.get('risk_code')}"
        if action not in rendered_record["normalization_actions"]:
            rendered_record["normalization_actions"].append(action)

    return {
        **repaired_item,
        "rendered_record": rendered_record,
        "node6d_gate": {
            "gate_version": GATE_VERSION,
            "format_valid": format_valid,
            "field_contract_valid": field_contract_valid,
            "admission_contract_valid": admission_contract_valid,
            "schema_valid": schema_valid,
            "gate_bucket": gate_bucket,
            "issues": issues,
            "point_repair_tasks": repair_tasks,
            "applied_repairs": applied_repairs,
            "rejected_repairs": rejected_repairs,
        },
    }


def markdown_to_html(markdown: str, md: MarkdownIt) -> str:
    text = str(markdown or "").strip()
    if not text:
        return "<span class='empty'>（空）</span>"
    try:
        return md.render(text)
    except Exception:
        escaped = html.escape(text)
        escaped = escaped.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
        return escaped.replace("\n", "<br>")


def compact_text(value: Any, limit: int = 260) -> str:
    text = str(value or "").replace("\r", "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_gate_panel(gate: dict[str, Any]) -> str:
    flags = [
        ("format_valid", "格式"),
        ("field_contract_valid", "字段契约"),
        ("admission_contract_valid", "准入契约"),
        ("schema_valid", "Schema"),
    ]
    flag_html = "".join(
        f"<span class='flag {str(bool(gate.get(key))).lower()}'>{html.escape(label)}={html.escape(str(gate.get(key)))}</span>"
        for key, label in flags
    )

    issues = gate.get("issues") or []
    issue_rows = []
    for issue in issues[:12]:
        issue_rows.append(
            "<li>"
            f"<b>{html.escape(str(issue.get('risk_code') or 'unknown'))}</b>"
            f" <span class='muted'>{html.escape(str(issue.get('severity') or ''))}</span>"
            f"<br>{html.escape(compact_text(issue.get('message') or issue.get('source_span') or issue))}"
            "</li>"
        )
    issue_html = "<ul>" + "".join(issue_rows) + "</ul>" if issue_rows else "<div class='empty'>无</div>"

    tasks = gate.get("point_repair_tasks") or []
    task_rows = []
    for task in tasks[:12]:
        task_rows.append(
            "<li>"
            f"<b>{html.escape(str(task.get('task_id') or ''))}</b> "
            f"{html.escape(str(task.get('risk_code') or ''))}"
            f" <span class='muted'>{html.escape(str(task.get('field_path') or ''))}</span>"
            f"<br><span class='source-span'>{html.escape(compact_text(task.get('source_span'), 360))}</span>"
            f"<br><span class='muted'>建议：{html.escape(str(task.get('suggested_action') or ''))}"
            f" → {html.escape(str(task.get('suggested_target_field') or ''))}</span>"
            "</li>"
        )
    task_html = "<ul>" + "".join(task_rows) + "</ul>" if task_rows else "<div class='empty'>无</div>"

    applied = gate.get("applied_repairs") or []
    applied_rows = []
    for repair in applied[:12]:
        applied_rows.append(
            "<li>"
            f"<b>{html.escape(str(repair.get('action') or repair.get('risk_code') or 'repair'))}</b>"
            f" <span class='muted'>{html.escape(str(repair.get('field_path') or ''))}</span>"
            f"<br>{html.escape(compact_text(repair.get('message') or repair))}"
            "</li>"
        )
    applied_html = "<ul>" + "".join(applied_rows) + "</ul>" if applied_rows else "<div class='empty'>无</div>"

    rejected = gate.get("rejected_repairs") or []
    rejected_rows = []
    for repair in rejected[:12]:
        rejected_rows.append(
            "<li>"
            f"<b>{html.escape(str(repair.get('reason') or repair.get('risk_code') or 'rejected'))}</b>"
            f" <span class='muted'>{html.escape(str(repair.get('field_path') or ''))}</span>"
            f"<br><span class='source-span'>{html.escape(compact_text(repair.get('source_span') or repair, 360))}</span>"
            "</li>"
        )
    rejected_html = "<ul>" + "".join(rejected_rows) + "</ul>" if rejected_rows else "<div class='empty'>无</div>"

    return f"""
<div class='gate-panel'>
  <div class='gate-head'><b>{html.escape(str(gate.get('gate_bucket') or ''))}</b>{flag_html}</div>
  <h4>发现的问题</h4>{issue_html}
  <h4>点状修复任务</h4>{task_html}
  <h4>已应用修复</h4>{applied_html}
  <h4>拒绝/未自动修复</h4>{rejected_html}
</div>
"""


def render_review(records: list[dict[str, Any]], title: str) -> str:
    md = MarkdownIt("default", {"html": True})
    rows = []
    for item in records:
        record = item.get("rendered_record") or {}
        display = record.get("display_question") or {}
        gate = item.get("node6d_gate") or {}
        admission = record.get("admission_profile") or {}
        gid = record.get("source_group_id") or item.get("source_group_id") or ""
        builder_action = str(admission.get("builder_action") or "")
        gate_bucket = str(gate.get("gate_bucket") or "")
        is_material = builder_action == "do_not_build_direct_packet" or gate_bucket == "material_or_parent_only"
        page_imgs = []
        for path in item.get("page_images") or []:
            p = workspace_path(path)
            if p.exists():
                page_imgs.append(f"<img src='{html.escape(p.resolve().as_uri())}' alt='{html.escape(p.name)}'>")
        if is_material:
            rendered_fields = (
                f"<td class='qfield material-card'><h4>材料/父节点内容</h4>{markdown_to_html(display.get('stem_markdown'), md)}"
                f"<h4>归属说明</h4><div class='note'>{html.escape(str(admission.get('reason') or '非直接题，不进入 standalone QuestionPacket。'))}</div>"
                f"<h4>答案</h4>{markdown_to_html(display.get('answer_markdown'), md)}"
                f"<h4>解析</h4>{markdown_to_html(display.get('analysis_markdown'), md)}</td>"
            )
        else:
            rendered_fields = (
                f"<td class='qfield'><h4>题干</h4>{markdown_to_html(display.get('stem_markdown'), md)}"
                f"<h4>答案</h4>{markdown_to_html(display.get('answer_markdown'), md)}"
                f"<h4>解析</h4>{markdown_to_html(display.get('analysis_markdown'), md)}"
                f"<h4>翻译/补充</h4>{markdown_to_html(display.get('translation_markdown'), md)}</td>"
            )
        rows.append(
            "<tr>"
            f"<td><b>{html.escape(str(gid))}</b><br>{html.escape(str(gate.get('gate_bucket') or ''))}</td>"
            f"<td class='pages'>{''.join(page_imgs) or '（无原页）'}</td>"
            f"{rendered_fields}"
            f"<td>{render_gate_panel(gate)}<details><summary>完整 6d JSON</summary><pre>{html.escape(json.dumps(gate, ensure_ascii=False, indent=2))}</pre></details></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f7f8fb;color:#202124}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #d8dde6;padding:10px;vertical-align:top}}th{{background:#f0f3f8}}
.pages img{{width:240px;display:block;margin-bottom:8px;border:1px solid #cfd6df}}pre{{white-space:pre-wrap;max-width:520px;font-size:12px}}h4{{margin:8px 0 4px}}
.qfield table{{width:auto;margin:8px 0;border-collapse:collapse}}.qfield th,.qfield td{{border:1px solid #cfd6df;padding:5px 8px}}
.gate-panel ul{{margin:6px 0 14px;padding-left:20px}}.gate-panel li{{margin:0 0 8px}}
.gate-head{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px}}
.flag{{font-size:12px;border:1px solid #cfd6df;border-radius:999px;padding:2px 7px;background:#f8fafc}}.flag.true{{color:#166534;background:#ecfdf3;border-color:#bbf7d0}}.flag.false{{color:#991b1b;background:#fef2f2;border-color:#fecaca}}
.muted{{color:#667085;font-size:12px}}.source-span{{display:inline-block;background:#fff8db;border:1px solid #f3d36b;border-radius:4px;padding:3px 5px;margin-top:3px}}
.material-card{{background:#fbfcff}}.note{{background:#f8fafc;border:1px solid #d8dde6;border-radius:6px;padding:8px;color:#475467}}
.empty{{color:#8a94a6}}
</style>
<h1>{html.escape(title)}</h1>
<table><thead><tr><th>题组</th><th>原页</th><th>最终展示字段</th><th>6d 检查</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    records_path = workspace_path(args.verified_rendered_records_json)
    packets_path = workspace_path(args.refined_packets_json)
    output_root = workspace_path(args.output_root)
    out_dir = output_root / args.run_id
    records = load_records(records_path)
    packets = load_packets(packets_path)
    validator = load_schema_validator()
    md = MarkdownIt("commonmark")

    gated: list[dict[str, Any]] = []
    for item in records:
        gid = str(item.get("source_group_id") or (item.get("rendered_record") or {}).get("source_group_id") or "")
        packet = packets.get(gid, {})
        gated.append(gate_one(item, packet, validator, md, not args.no_apply_safe_repairs))

    bucket_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for item in gated:
        gate = item.get("node6d_gate") or {}
        bucket = str(gate.get("gate_bucket") or "unknown")
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        for issue in gate.get("issues") or []:
            code = str(issue.get("risk_code") or "unknown")
            issue_counts[code] = issue_counts.get(code, 0) + 1

    point_tasks = [
        {
            "source_group_id": item.get("source_group_id"),
            "source_packet_id": item.get("source_packet_id"),
            "tasks": (item.get("node6d_gate") or {}).get("point_repair_tasks") or [],
        }
        for item in gated
        if (item.get("node6d_gate") or {}).get("point_repair_tasks")
    ]
    repair_report = [
        {
            "source_group_id": item.get("source_group_id"),
            "applied_repairs": (item.get("node6d_gate") or {}).get("applied_repairs") or [],
            "rejected_repairs": (item.get("node6d_gate") or {}).get("rejected_repairs") or [],
        }
        for item in gated
        if (item.get("node6d_gate") or {}).get("applied_repairs") or (item.get("node6d_gate") or {}).get("rejected_repairs")
    ]

    payload = {
        "schema": "english_render_gate_point_repair_batch_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gate_version": GATE_VERSION,
        "source_verified_rendered_records_json": rel_workspace(records_path),
        "source_refined_packets_json": rel_workspace(packets_path),
        "records": gated,
        "summary": {
            "record_count": len(gated),
            "bucket_counts": bucket_counts,
            "issue_counts": issue_counts,
            "point_repair_task_record_count": len(point_tasks),
            "repair_record_count": len(repair_report),
            "model_call_enabled": False,
            "database_write_enabled": False,
        },
    }
    write_json(out_dir / "gated_rendered_records.json", payload)
    write_json(out_dir / "render_gate_report.json", payload["summary"] | {"issue_counts": issue_counts})
    write_json(out_dir / "point_repair_tasks.json", {"schema": "english_point_repair_tasks_v0.1", "tasks_by_record": point_tasks})
    write_json(out_dir / "repair_application_report.json", {"schema": "english_point_repair_application_v0.1", "records": repair_report})

    for bucket in sorted(bucket_counts):
        subset = [item for item in gated if (item.get("node6d_gate") or {}).get("gate_bucket") == bucket]
        write_text(out_dir / f"{bucket}.html", render_review(subset, f"{args.run_id} / {bucket}"))
    write_text(out_dir / "review_after_gate.html", render_review(gated, f"{args.run_id} / all gated records"))
    return {
        "run_id": args.run_id,
        "output_dir": rel_workspace(out_dir),
        "summary": payload["summary"],
        "artifacts": {
            "gated_rendered_records_json": rel_workspace(out_dir / "gated_rendered_records.json"),
            "render_gate_report_json": rel_workspace(out_dir / "render_gate_report.json"),
            "point_repair_tasks_json": rel_workspace(out_dir / "point_repair_tasks.json"),
            "repair_application_report_json": rel_workspace(out_dir / "repair_application_report.json"),
            "review_after_gate_html": rel_workspace(out_dir / "review_after_gate.html"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="English text-first Node6d render gate and point repair.")
    parser.add_argument("--verified-rendered-records-json", required=True)
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--output-root",
        default="outputs/english_text_first_pipeline_v02_spec_20260715/controlled_runs",
    )
    parser.add_argument("--no-apply-safe-repairs", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
