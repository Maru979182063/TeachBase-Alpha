from __future__ import annotations

import argparse
import copy
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


VERIFIER_VERSION = "english_render_verifier_repair_v0.1_source_surface_contract_20260722"


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def normalize_for_support(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = lowered.replace("&nbsp;", " ")
    return re.sub(r"[\s`*_#|:：,，.。;；!！?？()（）\\/\-—–]+", "", lowered)


def significant_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("|") or stripped.startswith("- "):
        return False
    if set(stripped) <= {"_", "-"}:
        return False
    return len(normalize_for_support(stripped)) >= 12


def is_heading(line: str) -> bool:
    return line.strip().startswith("#")


def is_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    return bool(stripped) and all(ch in {"-", ":", "|", " "} for ch in stripped)


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def repair_markdown_tables(markdown: str) -> tuple[str, list[str]]:
    lines = str(markdown or "").splitlines()
    out: list[str] = []
    actions: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            header = split_table_row(line)
            width = max(1, len(header))
            table_lines = [render_table_row(header), render_table_row(["----"] * width)]
            i += 2
            changed = table_lines[0] != line or table_lines[1] != lines[i - 1]
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_table_row(lines[i])
                original = cells[:]
                if len(cells) > width:
                    cells = cells[: width - 1] + [" ".join(cell for cell in cells[width - 1 :] if cell).strip()]
                if len(cells) < width:
                    cells.extend([""] * (width - len(cells)))
                table_lines.append(render_table_row(cells))
                changed = changed or cells != original or table_lines[-1] != lines[i]
                i += 1
            out.extend(table_lines)
            if changed:
                actions.append("repair:markdown_table_cell_count_normalized")
            continue
        out.append(line)
        i += 1
    return "\n".join(out), actions


def source_corpus(packet: dict[str, Any], record_item: dict[str, Any]) -> str:
    q = packet.get("standard_question") or {}
    fields = [
        q.get("title"),
        q.get("passage"),
        q.get("stem"),
        q.get("options"),
        q.get("answer"),
        q.get("analysis"),
        q.get("translation"),
        q.get("context"),
        q.get("examples"),
        q.get("rubric"),
        packet.get("final_markdown"),
        record_item.get("source_stem"),
        record_item.get("source_final_markdown"),
    ]
    return "\n".join(str(field or "") for field in fields)


def line_is_source_supported(line: str, source_norm: str) -> bool:
    stripped = line.strip().strip("#").strip()
    if not significant_line(stripped):
        return True
    norm = normalize_for_support(stripped)
    return bool(norm and norm in source_norm)


def remove_unsupported_wrapper_headings(markdown: str, source_text: str) -> tuple[str, list[str], list[str]]:
    """Remove only unsupported display wrapper headings.

    Node6c is deterministic and does not re-transcribe page images, so it must
    not delete body text merely because Node5 did not carry that text forward.
    """
    source_norm = normalize_for_support(source_text)
    kept: list[str] = []
    removed: list[str] = []
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if line_is_source_supported(stripped, source_norm):
            kept.append(line)
            continue
        if is_heading(stripped):
            removed.append(stripped)
            continue
        kept.append(line)
    actions = ["repair:removed_source_unsupported_wrapper_headings"] if removed else []
    return "\n".join(kept).strip(), actions, removed


def is_label_only_stem(text: str) -> bool:
    norm = normalize_for_support(text)
    return bool(norm) and len(norm) <= 10


def build_standard_text_only_stem(packet: dict[str, Any]) -> str:
    q = packet.get("standard_question") or {}
    parts: list[str] = []
    context = str(q.get("context") or "").strip()
    examples = str(q.get("examples") or "").strip()
    stem = str(q.get("stem") or "").strip()
    if context and context not in stem:
        parts.append(f"### {context}")
    if examples and examples not in stem:
        parts.append(examples)
    if stem:
        parts.append(stem)
    return "\n\n".join(parts).strip()


def should_reset_writing_text_only_stem(packet: dict[str, Any], display: dict[str, Any]) -> bool:
    if str(packet.get("packet_family") or "").lower() != "writing":
        return False
    asset_refs = packet.get("asset_refs") or {}
    if asset_refs.get("visual_refs"):
        return False
    rendering_blocks = {
        str(block).strip().lower()
        for block in display.get("rendering_blocks") or []
        if str(block).strip()
    }
    complex_surface_blocks = {
        "markdown_table",
        "table",
        "checklist_table",
        "email_template",
        "writing_paper",
        "response_paper",
        "rubric_table",
    }
    if rendering_blocks & complex_surface_blocks:
        return False
    q = packet.get("standard_question") or {}
    standard_stem = build_standard_text_only_stem(packet)
    if not standard_stem or is_label_only_stem(str(q.get("stem") or "")):
        return False
    standard_norm = normalize_for_support(standard_stem)
    current = str(display.get("stem_markdown") or "")
    for line in current.splitlines():
        stripped = line.strip().strip("#").strip()
        if not significant_line(stripped):
            continue
        if normalize_for_support(stripped) not in standard_norm:
            return True
    return False


def remove_leading_answer_contamination(packet: dict[str, Any], display: dict[str, Any]) -> tuple[bool, list[str]]:
    stem = str(display.get("stem_markdown") or "")
    answer = str(display.get("answer_markdown") or "")
    if not stem.strip() or not answer.strip():
        return False, []
    q = packet.get("standard_question") or {}
    stem_norm = normalize_for_support(str(q.get("stem") or ""))
    answer_line_norms = {
        normalize_for_support(line)
        for line in answer.splitlines()
        if significant_line(line)
    }
    lines = stem.splitlines()
    removed: list[str] = []
    while lines:
        first = lines[0].strip()
        if not first:
            lines.pop(0)
            removed.append("")
            continue
        first_norm = normalize_for_support(first)
        if first_norm and first_norm in answer_line_norms and first_norm not in stem_norm:
            removed.append(lines.pop(0))
            continue
        break
    if removed:
        display["stem_markdown"] = "\n".join(lines).strip()
        return True, [line for line in removed if line.strip()]
    return False, []


def strip_wrapping_parentheses(text: str) -> str:
    value = str(text or "").strip()
    if len(value) >= 2 and value[0] == "(" and value[-1] == ")":
        return value[1:-1].strip()
    return value


def underline_grammar_answer_spans(packet: dict[str, Any], display: dict[str, Any]) -> tuple[bool, list[str]]:
    if str(packet.get("packet_family") or "").lower() != "grammar":
        return False, []
    answer = str(display.get("answer_markdown") or "")
    if not answer.strip():
        return False, []
    spans: list[str] = []
    for item in display.get("items") or []:
        if not isinstance(item, dict):
            continue
        answer_span = str(item.get("answer_span") or "").strip()
        span = strip_wrapping_parentheses(answer_span)
        if len(span) >= 8 and span not in spans:
            spans.append(span)
    if not spans:
        return False, []
    repaired = answer
    applied: list[str] = []
    for span in sorted(spans, key=len, reverse=True):
        if f"<u>{span}</u>" in repaired or f"<u>({span})</u>" in repaired:
            continue
        replaced = False
        for target, replacement in [
            (f"({span})", f"(<u>{span}</u>)"),
            (span, f"<u>{span}</u>"),
        ]:
            if target in repaired:
                repaired = repaired.replace(target, replacement, 1)
                applied.append(span)
                replaced = True
                break
        if not replaced:
            continue
    if applied:
        display["answer_markdown"] = repaired
        blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
        if "grammar_marking" not in blocks:
            blocks.append("grammar_marking")
            display["rendering_blocks"] = blocks
        return True, applied
    return False, []


def verify_and_repair(item: dict[str, Any], packet_by_group: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = copy.deepcopy(item.get("rendered_record") or {})
    display = record.setdefault("display_question", {})
    group_id = record.get("source_group_id") or item.get("source_group_id")
    packet = packet_by_group.get(str(group_id), {})
    actions: list[str] = list(record.get("normalization_actions") or [])
    node6c_actions: list[str] = []
    issues: list[str] = list(record.get("unresolved_issues") or [])
    checks: dict[str, str] = {}

    for field in ["stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown"]:
        repaired, table_actions = repair_markdown_tables(str(display.get(field) or ""))
        if table_actions:
            display[field] = repaired
            actions.extend(table_actions)
            node6c_actions.extend(table_actions)
            checks["table_contract_status"] = "REPAIRED"

    source_text = source_corpus(packet, item)
    packet_family = str(packet.get("packet_family") or "").lower()
    if packet_family == "writing":
        repaired_stem, source_actions, removed = remove_unsupported_wrapper_headings(
            str(display.get("stem_markdown") or ""),
            source_text,
        )
        if source_actions and repaired_stem:
            display["stem_markdown"] = repaired_stem
            actions.extend(source_actions)
            node6c_actions.extend(source_actions)
            issues.append(
                "Node6c removed unsupported wrapper headings only. Removed: "
                + " | ".join(removed[:8])
            )
            checks["source_support_status"] = "REPAIRED"

    admission = record.setdefault("admission_profile", {})
    direct_import_allowed = bool(admission.get("direct_import_allowed"))
    refine_status = str(packet.get("refine_status") or "")
    source_stem = str((packet.get("standard_question") or {}).get("stem") or "")
    source_answer = str((packet.get("standard_question") or {}).get("answer") or "")
    if refine_status == "PRESERVED_NON_DIRECT":
        admission["direct_import_allowed"] = False
        admission.setdefault("admission_mode", "SPLIT_OR_PARENT_CLUSTER_REQUIRED")
        admission.setdefault("builder_action", "do_not_build_direct_packet")
        checks["admission_consistency_status"] = "REPAIRED_NON_DIRECT"
    if is_label_only_stem(source_stem) and len(normalize_for_support(source_answer)) > 80:
        admission["direct_import_allowed"] = False
        admission["source_review_required"] = True
        admission["builder_action"] = "attach_as_answer_or_example_material"
        issues.append("Source stem is label-only while answer/example content is substantial; do not reconstruct a missing prompt from the answer.")
        checks["source_prompt_contract_status"] = "ANSWER_ONLY_OR_LABEL_ONLY"

    if should_reset_writing_text_only_stem(packet, display):
        display["stem_markdown"] = build_standard_text_only_stem(packet)
        action = "repair:writing_text_only_stem_reset_to_standard_fields"
        actions.append(action)
        node6c_actions.append(action)
        issues.append("Writing text-only stem contained source-unsupported task wrapper text; reset stem_markdown to standard_question.context + standard_question.stem.")
        checks["source_support_status"] = "REPAIRED"

    contamination_repaired, removed_answer_lines = remove_leading_answer_contamination(packet, display)
    if contamination_repaired:
        action = "repair:leading_answer_contamination_removed_from_stem"
        actions.append(action)
        node6c_actions.append(action)
        issues.append(
            "Removed leading answer-like line(s) from stem_markdown because they duplicated answer_markdown and were not part of standard_question stem/context. Removed: "
            + " | ".join(removed_answer_lines[:5])
        )
        checks["field_boundary_status"] = "REPAIRED"

    grammar_marking_repaired, grammar_spans = underline_grammar_answer_spans(packet, display)
    if grammar_marking_repaired:
        action = "repair:grammar_answer_spans_underlined"
        actions.append(action)
        node6c_actions.append(action)
        issues.append("Rendered grammar answer_span values with underline markup for clause-marking tasks. Spans: " + " | ".join(grammar_spans[:10]))
        checks["grammar_marking_status"] = "REPAIRED"

    asset_refs = packet.get("asset_refs") or {}
    rendering_blocks = display.get("rendering_blocks") if isinstance(display.get("rendering_blocks"), list) else []
    if asset_refs.get("writing_surface_refs") and "writing_surface" not in rendering_blocks:
        rendering_blocks.append("writing_surface")
        display["rendering_blocks"] = rendering_blocks
        action = "repair:writing_surface_rendering_block_added_from_asset_refs"
        actions.append(action)
        node6c_actions.append(action)
        checks["surface_contract_status"] = "REPAIRED"

    record["normalization_actions"] = sorted(set(str(action) for action in actions if str(action).strip()))
    record["unresolved_issues"] = [str(issue) for issue in issues if str(issue).strip()]
    admission = record.get("admission_profile") or {}
    if record.get("render_status") != "READY":
        bucket = "review_required"
    elif bool(admission.get("direct_import_allowed")):
        bucket = "importable_question"
    elif admission.get("builder_action") in {"build_child_packet_with_parent_context", "build_packet_with_visual_parent_or_source_page", "build_example_child_under_parent"}:
        bucket = "relation_or_surface_required"
    else:
        bucket = "material_or_parent_only"

    checks.setdefault("table_contract_status", "UNCHANGED")
    checks.setdefault("source_support_status", "UNCHANGED")
    checks.setdefault("surface_contract_status", "UNCHANGED")
    checks.setdefault("admission_consistency_status", "UNCHANGED")
    checks.setdefault("grammar_marking_status", "UNCHANGED")
    return {
        **item,
        "rendered_record": record,
        "node6c_verification": {
            "verifier_version": VERIFIER_VERSION,
            "bucket": bucket,
            "checks": checks,
            "node6c_repairs_applied": sorted(set(str(action) for action in node6c_actions if str(action).strip())),
            "all_normalization_actions": record["normalization_actions"],
            "issues": record["unresolved_issues"],
        },
    }


def inline_markdown(text: str) -> str:
    escaped = html.escape(str(text or "")).replace("&nbsp;", " ")
    return (
        escaped
        .replace("&lt;u&gt;", "<u>")
        .replace("&lt;/u&gt;", "</u>")
    )


def markdown_table_to_html(lines: list[str]) -> str:
    rows = [split_table_row(line) for line in lines]
    if len(rows) < 2:
        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    width = max(len(rows[0]), 1)
    header = rows[0]
    body = rows[2:]
    head_html = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in header)
    body_html = ""
    for row in body:
        cells = row[: width - 1] + [" ".join(row[width - 1 :]).strip()] if len(row) > width else row
        cells.extend([""] * (width - len(cells)))
        body_html += "<tr>" + "".join(f"<td>{inline_markdown(cell)}</td>" for cell in cells) + "</tr>"
    return f"<table class='md-table'><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def markdown_to_html(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + "<br>".join(inline_markdown(line) for line in paragraph) + "</p>")
            paragraph = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1]):
            flush_paragraph()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(markdown_table_to_html(table_lines))
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            level = min(4, max(2, len(stripped) - len(stripped.lstrip("#")) + 1))
            text = stripped.lstrip("#").strip()
            out.append(f"<h{level}>{inline_markdown(text)}</h{level}>")
            i += 1
            continue
        if set(stripped) <= {"_", "-"} and len(stripped) >= 8:
            flush_paragraph()
            out.append("<div class='write-line'></div>")
            i += 1
            continue
        paragraph.append(line)
        i += 1
    flush_paragraph()
    return "".join(out) or "<div class='empty'>（空）</div>"


def render_section(title: str, records: list[dict[str, Any]], summary_note: str) -> str:
    cards: list[str] = []
    for index, item in enumerate(records, start=1):
        record = item.get("rendered_record") or {}
        display = record.get("display_question") or {}
        verification = item.get("node6c_verification") or {}
        admission = record.get("admission_profile") or {}
        page_figs = []
        for path in item.get("page_images") or []:
            abs_path = workspace_path(path)
            if not abs_path.exists():
                continue
            url = abs_path.resolve().as_uri()
            page_figs.append(
                f"<figure><a href='{html.escape(url)}' target='_blank'><img src='{html.escape(url)}'></a>"
                f"<figcaption>{html.escape(Path(path).name)}</figcaption></figure>"
            )
        cards.append(
            f"""
<section class="card">
  <div class="card-head"><strong>#{index} {html.escape(record.get('source_group_id') or '')}</strong>
  <span>{html.escape(str(verification.get('bucket') or ''))}</span></div>
  <div class="grid">
    <div><h3>原页</h3><div class="pages">{''.join(page_figs) or '<div class="empty">无原页图片</div>'}</div></div>
    <div>
      <div class="admission"><b>入库模式：</b>{html.escape(str(admission.get('admission_mode') or ''))}<br>
      <b>Builder 动作：</b>{html.escape(str(admission.get('builder_action') or ''))}<br>
      <b>直入：</b>{html.escape(str(admission.get('direct_import_allowed')))}</div>
      <h3>最终题干</h3><div class="rendered">{markdown_to_html(display.get('stem_markdown') or '')}</div>
      <h3>最终答案</h3><div class="rendered">{markdown_to_html(display.get('answer_markdown') or '')}</div>
      <h3>最终解析</h3><div class="rendered">{markdown_to_html(display.get('analysis_markdown') or '')}</div>
      <h3>翻译/补充</h3><div class="rendered">{markdown_to_html(display.get('translation_markdown') or '')}</div>
      <details><summary>6c 校验与修复</summary><pre>{html.escape(json.dumps(verification, ensure_ascii=False, indent=2))}</pre></details>
    </div>
  </div>
</section>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:0;background:#f5f6f8;color:#202124;line-height:1.5}}
header{{position:sticky;top:0;background:white;border-bottom:1px solid #d8dde6;padding:14px 20px;z-index:2}}
h1{{font-size:20px;margin:0 0 6px}} .summary{{font-size:13px;color:#5f6368}}
.card{{margin:18px auto;padding:14px 16px;background:white;border:1px solid #d8dde6;border-radius:8px;max-width:1500px}}
.card-head{{display:flex;justify-content:space-between;border-bottom:1px solid #eef1f5;padding-bottom:10px;margin-bottom:12px}}
.grid{{display:grid;grid-template-columns:minmax(360px,42%) 1fr;gap:18px;align-items:start}}
.pages{{display:flex;gap:12px;flex-wrap:wrap}} figure{{margin:0 0 12px;max-width:320px}} img{{width:310px;border:1px solid #cfd6df;background:white}} figcaption{{font-size:12px;color:#6b7280;word-break:break-all}}
.rendered{{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:10px;margin:0 0 12px}} .rendered p{{margin:0 0 8px}}
.admission{{background:#f8fafc;border:1px solid #d8dde6;border-radius:6px;padding:10px;margin:0 0 12px;font-size:13px}}
.md-table{{border-collapse:collapse;width:100%;margin:8px 0 12px;font-size:14px}} .md-table th,.md-table td{{border:1px solid #cfd6df;padding:7px 9px;vertical-align:top}} .md-table th{{background:#f3f6fa;text-align:left}}
.write-line{{height:18px;border-bottom:1px solid #4b5563;margin:8px 0}} pre{{white-space:pre-wrap;word-break:break-word;background:#fafafa;border:1px solid #e5e7eb;border-radius:6px;padding:10px}}
.empty{{color:#9aa0a6;background:#fafafa;border:1px dashed #d8dde6;padding:10px;border-radius:6px}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}} figure,img{{max-width:100%;width:100%}}}}
</style>
<header><h1>{html.escape(title)}</h1><div class="summary">{html.escape(summary_note)}</div></header>
<main>{''.join(cards) or '<section class="card">无记录</section>'}</main>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    rendered_payload = read_json(workspace_path(args.rendered_records_json))
    refined_payload = read_json(workspace_path(args.refined_packets_json))
    packet_by_group = {
        str(packet.get("source_group_id")): packet
        for packet in refined_payload.get("refined_packets") or []
        if packet.get("source_group_id")
    }
    records = [
        verify_and_repair(item, packet_by_group)
        for item in rendered_payload.get("records") or []
    ]
    bucket_counts = {
        bucket: sum(1 for item in records if (item.get("node6c_verification") or {}).get("bucket") == bucket)
        for bucket in sorted({(item.get("node6c_verification") or {}).get("bucket") for item in records})
        if bucket
    }
    repaired_count = sum(
        1
        for item in records
        if (item.get("node6c_verification") or {}).get("node6c_repairs_applied")
    )
    out_root = workspace_path(args.output_root or "outputs/english_text_first_pipeline_v02_spec_20260715/controlled_runs") / args.run_id
    payload = {
        "schema": "verified_rendered_question_records_batch_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "verifier_version": VERIFIER_VERSION,
        "source_rendered_records_json": rel_workspace(workspace_path(args.rendered_records_json)),
        "source_refined_packets_json": rel_workspace(workspace_path(args.refined_packets_json)),
        "doc_id": rendered_payload.get("doc_id") or refined_payload.get("doc_id"),
        "records": records,
        "summary": {
            "record_count": len(records),
            "bucket_counts": bucket_counts,
            "repaired_record_count": repaired_count,
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        },
    }
    importable = [item for item in records if (item.get("node6c_verification") or {}).get("bucket") == "importable_question"]
    relation = [item for item in records if (item.get("node6c_verification") or {}).get("bucket") == "relation_or_surface_required"]
    review = [item for item in records if (item.get("node6c_verification") or {}).get("bucket") == "review_required"]
    material = [item for item in records if (item.get("node6c_verification") or {}).get("bucket") == "material_or_parent_only"]
    summary_note = f"records={len(records)} | buckets={bucket_counts} | repaired={repaired_count}"
    write_json(out_root / "verified_rendered_records.json", payload)
    write_json(
        out_root / "run_summary.json",
        {
            "schema": "english_render_verifier_repair.run_summary",
            "generated_at": payload["generated_at"],
            "verifier_version": VERIFIER_VERSION,
            "out_dir": rel_workspace(out_root),
            **payload["summary"],
            "verified_rendered_records_json": rel_workspace(out_root / "verified_rendered_records.json"),
            "importable_review_html": rel_workspace(out_root / "importable_review.html"),
            "relation_or_surface_review_html": rel_workspace(out_root / "relation_or_surface_review.html"),
            "material_review_html": rel_workspace(out_root / "material_review.html"),
            "repair_report_html": rel_workspace(out_root / "repair_report.html"),
        },
    )
    write_text(out_root / "importable_review.html", render_section("Node6c 可直入题目", importable, summary_note))
    write_text(out_root / "relation_or_surface_review.html", render_section("Node6c 需父级/视觉关系题目", relation, summary_note))
    write_text(out_root / "material_review.html", render_section("Node6c 保留材料/父级材料", material, summary_note))
    write_text(out_root / "repair_report.html", render_section("Node6c 修复与检查报告", records, summary_note))
    return read_json(out_root / "run_summary.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rendered-records-json", required=True)
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default="")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
