from __future__ import annotations

import argparse
import html
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import group_ref_list, read_json, rel_workspace, workspace_path, write_json, write_text
from english_text_first_normalizer.evidence_text import meaningful_content_lines, normalize_evidence_text


FINAL_FIELDS = ["stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown"]
QUESTION_FIELDS = ["passage", "stem", "options", "answer", "analysis", "translation", "context", "examples", "rubric"]


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(text_of(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(text_of(v) for v in value)
    return str(value)


def contains_line(corpus: str, line: str) -> bool:
    norm = normalize_evidence_text(line)
    corpus_norm = normalize_evidence_text(corpus)
    if not norm:
        return False
    if norm in corpus_norm:
        return True
    if len(norm) > 100:
        return norm[:80] in corpus_norm or norm[-80:] in corpus_norm
    return False


def collect_block_index(node2_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    block_index: dict[str, dict[str, Any]] = {}
    for path in sorted((node2_run / doc_id).glob("page_*/window_input.json")):
        payload = read_json(path)
        for key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks"):
            for block in payload.get(key) or []:
                ref = block.get("block_ref")
                if ref:
                    block_index[str(ref)] = block
    return block_index


def load_node2_group(node2d_run: Path, group_id: str) -> dict[str, Any] | None:
    path = node2d_run / "document_groups.json"
    if not path.exists():
        return None
    payload = read_json(path)
    for group in payload.get("document_groups") or []:
        if group.get("document_group_id") == group_id:
            return group
    return None


def load_node3_record(node3_run: Path, doc_id: str, group_id: str) -> dict[str, Any] | None:
    path = node3_run / doc_id / group_id / "normalized_group_record.json"
    return read_json(path) if path.exists() else None


def load_node4_draft(node4_run: Path, group_id: str) -> dict[str, Any] | None:
    path = node4_run / "draft_items.json"
    if not path.exists():
        return None
    payload = read_json(path)
    for item in payload.get("draft_items") or []:
        if item.get("source_group_id") == group_id:
            return item
    return None


def load_node5_packet(node5_run: Path, group_id: str) -> dict[str, Any] | None:
    path = node5_run / "question_packet_candidates.json"
    if not path.exists():
        return None
    payload = read_json(path)
    for item in payload.get("packet_candidates") or []:
        if item.get("source_group_id") == group_id:
            return item
    return None


def load_node5b_packet(node5b_run: Path, packet_id: str, group_id: str) -> dict[str, Any] | None:
    candidates = [
        node5b_run / "packets" / str(packet_id) / "refined_question_packet.json",
        node5b_run / "packets" / f"packet_{group_id}" / "refined_question_packet.json",
    ]
    for path in candidates:
        if path.exists():
            return read_json(path)
    for path in (node5b_run / "packets").glob("*/refined_question_packet.json"):
        payload = read_json(path)
        if payload.get("source_group_id") == group_id or payload.get("source_packet_id") == packet_id:
            return payload
    return None


def load_final_records(final_run: Path) -> list[dict[str, Any]]:
    gated_path = final_run / "gated_rendered_records.json"
    if gated_path.exists():
        payload = read_json(gated_path)
        records = []
        for item in payload.get("records") or []:
            if isinstance(item.get("rendered_record"), dict):
                records.append(item["rendered_record"])
            elif isinstance(item, dict):
                records.append(item)
        if records:
            return records
    path = final_run / "rendered_question_records.json"
    if path.exists():
        payload = read_json(path)
        records = []
        for item in payload.get("records") or []:
            if isinstance(item.get("rendered_record"), dict):
                records.append(item["rendered_record"])
            elif isinstance(item, dict):
                records.append(item)
        if records:
            return records
    records = []
    for path in (final_run / "records").glob("*/rendered_question_record.json"):
        records.append(read_json(path))
    return records


def field_corpus_node5(packet: dict[str, Any] | None, field: str) -> str:
    if not packet:
        return ""
    field_map = {
        "stem_markdown": ["stem", "instruction", "options"],
        "answer_markdown": ["answer"],
        "analysis_markdown": ["analysis"],
        "translation_markdown": ["translation"],
    }
    parts = []
    for key in field_map.get(field, []):
        value = ((packet.get("content") or {}).get(key) or {})
        parts.append(text_of(value.get("text") if isinstance(value, dict) else value))
    return "\n".join(parts)


def field_corpus_node5b(packet: dict[str, Any] | None, field: str) -> str:
    if not packet:
        return ""
    q = packet.get("standard_question") or {}
    field_map = {
        "stem_markdown": ["stem", "options", "passage", "context", "examples", "rubric"],
        "answer_markdown": ["answer"],
        "analysis_markdown": ["analysis"],
        "translation_markdown": ["translation"],
    }
    return "\n".join(text_of(q.get(key)) for key in field_map.get(field, [])) + "\n" + str(packet.get("final_markdown") or "")


def refs_for_node3_field(record: dict[str, Any] | None, field: str) -> list[str]:
    if not record:
        return []
    refs = record.get("field_refs") or {}
    mapping = {
        "stem_markdown": ["stem_refs", "option_refs", "instruction_refs"],
        "answer_markdown": ["answer_refs"],
        "analysis_markdown": ["analysis_refs"],
        "translation_markdown": ["translation_refs"],
    }
    out: list[str] = []
    for key in mapping.get(field, []):
        out.extend(refs.get(key) or [])
    return out


def block_text_for_refs(refs: list[str], block_index: dict[str, dict[str, Any]]) -> str:
    return "\n".join(str((block_index.get(ref) or {}).get("text") or "") for ref in refs)


def classify_line(
    *,
    line: str,
    final_field: str,
    source_blocks_corpus: str,
    node2_group_corpus: str,
    node3_field_corpus: str,
    node4_corpus: str,
    node5_field_corpus: str,
    node5b_field_corpus: str,
) -> dict[str, Any]:
    in_source_blocks = contains_line(source_blocks_corpus, line)
    in_node2_group = contains_line(node2_group_corpus, line)
    in_node3_field = contains_line(node3_field_corpus, line)
    in_node4 = contains_line(node4_corpus, line)
    in_node5_field = contains_line(node5_field_corpus, line)
    in_node5b_field = contains_line(node5b_field_corpus, line)

    if in_node5b_field:
        first_field_stage = "node5b_or_earlier"
    elif in_node5_field:
        first_field_stage = "node5_candidate"
    elif in_node3_field:
        first_field_stage = "node3_field_assignment"
    elif in_node2_group:
        first_field_stage = "node2_group_only"
    elif in_source_blocks:
        first_field_stage = "node1_source_only"
    else:
        first_field_stage = "node6b_or_later_added"

    if not in_source_blocks:
        diagnosis = "not_found_in_source_blocks"
    elif in_node5b_field:
        diagnosis = "present_before_final_render"
    elif in_node5_field or in_node3_field:
        diagnosis = "field_assignment_before_5b"
    elif in_node2_group:
        diagnosis = "group_contains_text_but_field_not_confirmed"
    else:
        diagnosis = "source_text_not_assigned_before_final"

    return {
        "field": final_field,
        "line": line,
        "first_field_stage": first_field_stage,
        "diagnosis": diagnosis,
        "presence": {
            "node1_source_blocks": in_source_blocks,
            "node2_group": in_node2_group,
            "node3_same_field_refs": in_node3_field,
            "node4_draft_any_field": in_node4,
            "node5_candidate_same_field": in_node5_field,
            "node5b_same_field_or_final_markdown": in_node5b_field,
        },
    }


def audit_record(args: argparse.Namespace, record: dict[str, Any], block_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    group_id = str(record.get("source_group_id") or "")
    packet_id = str(record.get("source_packet_id") or "")
    node2_group = load_node2_group(workspace_path(args.node2d_run_dir), group_id)
    node3_record = load_node3_record(workspace_path(args.node3_run_dir), args.doc_id, group_id)
    node4_draft = load_node4_draft(workspace_path(args.node4_run_dir), group_id)
    node5_packet = load_node5_packet(workspace_path(args.node5_run_dir), group_id)
    node5b_packet = load_node5b_packet(workspace_path(args.node5b_run_dir), packet_id, group_id)

    group_refs = group_ref_list(node2_group or {})
    source_blocks_corpus = "\n".join(str(block.get("text") or "") for block in block_index.values())
    node2_group_corpus = block_text_for_refs(group_refs, block_index)
    node4_corpus = text_of(node4_draft)

    display = record.get("display_question") or {}
    fields = []
    for field in FINAL_FIELDS:
        text = str(display.get(field) or "")
        lines = meaningful_content_lines(text, min_normalized_chars=6)
        node3_field_corpus = block_text_for_refs(refs_for_node3_field(node3_record, field), block_index)
        node5_field = field_corpus_node5(node5_packet, field)
        node5b_field = field_corpus_node5b(node5b_packet, field)
        line_reports = [
            classify_line(
                line=line,
                final_field=field,
                source_blocks_corpus=source_blocks_corpus,
                node2_group_corpus=node2_group_corpus,
                node3_field_corpus=node3_field_corpus,
                node4_corpus=node4_corpus,
                node5_field_corpus=node5_field,
                node5b_field_corpus=node5b_field,
            )
            for line in lines
        ]
        fields.append({"field": field, "line_count": len(lines), "lines": line_reports})

    return {
        "source_group_id": group_id,
        "source_packet_id": packet_id,
        "render_status": record.get("render_status"),
        "field_reports": fields,
    }


def render_html(report: dict[str, Any]) -> str:
    cards = []
    for record in report["records"]:
        field_html = []
        for field in record["field_reports"]:
            rows = []
            for line in field["lines"]:
                cls = "bad" if line["first_field_stage"] == "node6b_or_later_added" else "warn" if line["diagnosis"] != "present_before_final_render" else "ok"
                rows.append(
                    f"<tr class='{cls}'><td>{html.escape(line['first_field_stage'])}</td><td>{html.escape(line['diagnosis'])}</td><td>{html.escape(line['line'])}</td></tr>"
                )
            if rows:
                field_html.append(
                    f"<h3>{html.escape(field['field'])}</h3><table><tr><th>首发/归属阶段</th><th>诊断</th><th>最终行</th></tr>{''.join(rows)}</table>"
                )
        cards.append(
            f"<section><h2>{html.escape(record['source_group_id'])} / {html.escape(record['source_packet_id'])} / {html.escape(str(record.get('render_status') or ''))}</h2>{''.join(field_html)}</section>"
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Lineage Diff</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #172033; }}
section {{ border: 1px solid #d8e0ea; padding: 14px; margin: 16px 0; border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
td, th {{ border: 1px solid #d8e0ea; padding: 8px; vertical-align: top; word-wrap: break-word; }}
.ok td {{ background: #f1faf6; }}
.warn td {{ background: #fff8e8; }}
.bad td {{ background: #fff0f0; }}
</style></head><body>
<h1>English Text-First Lineage Diff</h1>
<p>generated_at={html.escape(report['generated_at'])}</p>
{''.join(cards)}
</body></html>"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    block_index = collect_block_index(workspace_path(args.node2_run_dir), args.doc_id)
    records = load_final_records(workspace_path(args.final_run_dir))
    selected = set(args.group_ids or [])
    if selected:
        records = [r for r in records if r.get("source_group_id") in selected or r.get("source_packet_id") in selected]
    audited = [audit_record(args, record, block_index) for record in records]
    report = {
        "schema": "english_text_first_lineage_diff_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": args.doc_id,
        "records": audited,
    }
    out_dir = workspace_path(args.out_dir)
    write_json(out_dir / "lineage_diff_report.json", report)
    write_text(out_dir / "lineage_diff_report.html", render_html(report))
    write_json(out_dir / "run_summary.json", {
        "schema": "english_text_first_lineage_diff.run_summary",
        "generated_at": report["generated_at"],
        "doc_id": args.doc_id,
        "record_count": len(audited),
        "out_dir": rel_workspace(out_dir),
        "html": rel_workspace(out_dir / "lineage_diff_report.html"),
        "json": rel_workspace(out_dir / "lineage_diff_report.json"),
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--node2-run-dir", required=True)
    parser.add_argument("--node2d-run-dir", required=True)
    parser.add_argument("--node3-run-dir", required=True)
    parser.add_argument("--node4-run-dir", required=True)
    parser.add_argument("--node5-run-dir", required=True)
    parser.add_argument("--node5b-run-dir", required=True)
    parser.add_argument("--final-run-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    args = parser.parse_args()
    report = run(args)
    print({"record_count": len(report["records"])})


if __name__ == "__main__":
    main()
