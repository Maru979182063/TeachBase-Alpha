from __future__ import annotations

import argparse
import html
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import read_json, rel_workspace, workspace_path, write_json, write_text


REPAIR_VERSION = "english_candidate_continuation_repair_v0.1_source_backed_20260727"
MANIFEST_PATH = Path("config/english_text_first_graph_first/active_manifest.json")
CONTENT_FIELDS = [
    "instruction",
    "stem",
    "options",
    "passage",
    "answer",
    "analysis",
    "translation",
    "context",
    "examples",
    "rubric",
]
CONTINUATION_FIELD_PRIORITY = ["analysis", "answer", "translation", "stem", "passage", "context", "examples", "rubric"]
CONTINUATION_LABELS = {"unknown_text", "analysis_text", "answer_text", "translation_text", "example_text"}
SKIP_LABELS = {"header_footer"}


def parse_ref(ref: str) -> tuple[str, int, str] | None:
    match = re.match(r"^(?P<doc>.+)_p(?P<page>\d{3})_b(?P<block>\d+)$", ref)
    if not match:
        return None
    return match.group("doc"), int(match.group("page")), f"b{int(match.group('block'))}"


def block_ref(doc_id: str, page: int, block_id: str) -> str:
    block_num = int(str(block_id).lstrip("b"))
    return f"{doc_id}_p{page:03d}_b{block_num}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def is_short_residual(block: dict[str, Any]) -> bool:
    text = clean_text(block.get("text"))
    if not text:
        return False
    if "\n" in text:
        return False
    if len(text) > 16:
        return False
    label = str(block.get("label") or "")
    if label not in CONTINUATION_LABELS:
        return False
    if text.startswith(("【", "A.", "B.", "C.", "D.", "1.", "2.", "3.", "4.", "5.")):
        return False
    return True


def build_doc_source_index(manifest: dict[str, Any], family: str, packet_doc_id: str) -> dict[str, Any]:
    document = (manifest.get("documents") or {}).get(family)
    if not document:
        raise KeyError(f"family not found in manifest: {family}")
    node1 = ((document.get("runs") or {}).get("node1_vlm_transcriber") or {})
    primary = workspace_path(node1.get("primary_artifact") or "")
    if not primary.exists():
        raise FileNotFoundError(primary)

    by_ref: dict[str, dict[str, Any]] = {}
    pages: dict[int, dict[str, Any]] = {}
    for path in sorted(primary.glob("page_*/vlm_page_transcription.json")):
        page_payload = read_json(path)
        page = int(page_payload.get("page") or 0)
        if not page:
            continue
        pages[page] = page_payload
        for block in page_payload.get("blocks") or []:
            ref = block_ref(packet_doc_id, page, str(block.get("block_id") or ""))
            by_ref[ref] = {
                "ref": ref,
                "page": page,
                "block_id": str(block.get("block_id") or ""),
                "label": str(block.get("label") or ""),
                "text": str(block.get("text") or ""),
                "is_complete": bool(block.get("is_complete", True)),
                "bbox_hint": str(block.get("bbox_hint") or ""),
                "page_start": page_payload.get("page_start") or {},
                "page_end": page_payload.get("page_end") or {},
            }
    return {"by_ref": by_ref, "pages": pages, "primary_artifact": primary}


def first_content_blocks_on_page(index: dict[str, Any], packet_doc_id: str, page: int) -> list[dict[str, Any]]:
    page_payload = (index.get("pages") or {}).get(page) or {}
    result: list[dict[str, Any]] = []
    for block in page_payload.get("blocks") or []:
        if str(block.get("label") or "") in SKIP_LABELS:
            continue
        ref = block_ref(packet_doc_id, page, str(block.get("block_id") or ""))
        result.append(
            {
                "ref": ref,
                "page": page,
                "block_id": str(block.get("block_id") or ""),
                "label": str(block.get("label") or ""),
                "text": str(block.get("text") or ""),
                "is_complete": bool(block.get("is_complete", True)),
                "bbox_hint": str(block.get("bbox_hint") or ""),
                "page_start": page_payload.get("page_start") or {},
                "page_end": page_payload.get("page_end") or {},
            }
        )
    return result


def text_has_field_tail(field_text: str, block_text: str) -> bool:
    if not field_text or not block_text:
        return False
    stripped_field = field_text.rstrip()
    stripped_block = block_text.rstrip()
    if stripped_field.endswith(stripped_block):
        return True
    # The incomplete source block can sit in the middle of a field because later same-field
    # source blocks were already appended. It is still source-backed if the exact incomplete
    # block text, or a long enough tail anchor from that block, appears in the field. The tail
    # anchor handles harmless punctuation normalization between Node1 and later nodes.
    if stripped_block in field_text:
        return True
    tail_anchor = stripped_block[-16:]
    return len(tail_anchor) >= 8 and tail_anchor in field_text


def append_after_block_text(field_text: str, block_text: str, append_text: str) -> tuple[str, bool]:
    if not (field_text and block_text and append_text):
        return field_text, False
    if block_text + append_text in field_text:
        return field_text, False
    replacement = block_text + append_text
    if block_text in field_text:
        return field_text.replace(block_text, replacement, 1), True
    tail_anchor = block_text.rstrip()[-16:]
    if len(tail_anchor) >= 8 and tail_anchor in field_text:
        return field_text.replace(tail_anchor, tail_anchor + append_text, 1), True
    return field_text, False


def add_unique(values: list[str], value: str) -> list[str]:
    if value not in values:
        values.append(value)
    return values


def candidate_family(packet: dict[str, Any]) -> str:
    family = str(packet.get("packet_family") or "").lower()
    if family in {"reading", "grammar", "writing"}:
        return family
    doc_id = str(packet.get("doc_id") or "").lower()
    if "reading" in doc_id:
        return "reading"
    if "grammar" in doc_id or "clause" in doc_id:
        return "grammar"
    if "writing" in doc_id or "invitation" in doc_id:
        return "writing"
    return family


def find_continuation(
    *,
    index: dict[str, Any],
    packet: dict[str, Any],
    source_ref: str,
    block: dict[str, Any],
) -> dict[str, Any] | None:
    parsed = parse_ref(source_ref)
    if not parsed:
        return None
    packet_doc_id, page, _block_id = parsed
    next_page = page + 1
    source_refs = set((packet.get("evidence") or {}).get("source_refs") or [])
    current_page_payload = (index.get("pages") or {}).get(page) or {}
    page_end = current_page_payload.get("page_end") or {}
    if page_end.get("tail_cutoff") is not True:
        return None
    for next_block in first_content_blocks_on_page(index, packet_doc_id, next_page)[:3]:
        if next_block["ref"] not in source_refs:
            continue
        if not is_short_residual(next_block):
            continue
        return next_block
    return None


def repair_packet(packet: dict[str, Any], index: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repaired = deepcopy(packet)
    repairs: list[dict[str, Any]] = []
    content = repaired.get("content") or {}
    evidence = repaired.setdefault("evidence", {})
    field_ref_map = evidence.setdefault("field_ref_map", {})

    for field_name in CONTINUATION_FIELD_PRIORITY:
        field = content.get(field_name)
        if not isinstance(field, dict):
            continue
        field_text = str(field.get("text") or "")
        refs = [str(ref) for ref in field.get("refs") or []]
        for ref in list(refs):
            block = (index.get("by_ref") or {}).get(ref)
            if not block or block.get("is_complete", True):
                continue
            block_text = str(block.get("text") or "")
            if not text_has_field_tail(field_text, block_text):
                continue
            continuation = find_continuation(index=index, packet=repaired, source_ref=ref, block=block)
            if not continuation:
                continue
            new_text, changed = append_after_block_text(field_text, block_text, continuation["text"])
            if not changed:
                continue
            field["text"] = new_text
            field["refs"] = add_unique([str(item) for item in field.get("refs") or []], continuation["ref"])
            field_ref_map[field_name] = add_unique([str(item) for item in field_ref_map.get(field_name) or []], continuation["ref"])
            warning = {
                "code": "source_continuation_repair_applied",
                "message": "Rejoined an incomplete source-backed field using the next-page residual block already present in packet source_refs.",
                "field": field_name,
                "source_ref": ref,
                "append_ref": continuation["ref"],
                "before_tail": block_text,
                "append_text": continuation["text"],
            }
            repaired.setdefault("builder_warnings", []).append(warning)
            repairs.append(warning)
            field_text = new_text
    return repaired, repairs


def render_review(records: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    rows = []
    for record in records:
        repairs = record.get("repairs") or []
        repair_html = html.escape(json.dumps(repairs, ensure_ascii=False, indent=2))
        rows.append(
            "<tr>"
            f"<td>{html.escape(record.get('packet_id', ''))}</td>"
            f"<td>{html.escape(record.get('source_group_id', ''))}</td>"
            f"<td>{len(repairs)}</td>"
            f"<td><pre>{repair_html}</pre></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>English Candidate Continuation Repair</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f7f8fb;color:#172033}}
table{{border-collapse:collapse;width:100%;background:white}}
td,th{{border:1px solid #ccd3df;padding:8px;vertical-align:top}}
th{{background:#eef2f7}}
pre{{white-space:pre-wrap;margin:0}}
code{{background:#eef0f3;border-radius:4px;padding:1px 4px}}
</style>
<h1>Node5a Continuation Repair</h1>
<p>version=<code>{html.escape(summary.get('repair_version',''))}</code>, packets=<code>{summary.get('packet_count')}</code>, repaired=<code>{summary.get('repaired_packet_count')}</code>, repairs=<code>{summary.get('repair_count')}</code></p>
<table>
<thead><tr><th>packet</th><th>group</th><th>repair_count</th><th>repairs</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_json(workspace_path(args.manifest))
    source_path = workspace_path(args.question_packet_candidates_json)
    payload = read_json(source_path)
    packet_candidates = payload.get("packet_candidates") or []
    selected_ids = set(args.packet_ids or [])
    if selected_ids:
        packet_candidates = [
            packet
            for packet in packet_candidates
            if packet.get("packet_id") in selected_ids or packet.get("source_group_id") in selected_ids
        ]

    out_root = workspace_path(args.output_root) / args.run_id
    index_by_family: dict[tuple[str, str], dict[str, Any]] = {}
    repaired_packets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for packet in packet_candidates:
        family = args.family or candidate_family(packet)
        packet_doc_id = str(packet.get("doc_id") or "")
        key = (family, packet_doc_id)
        if key not in index_by_family:
            index_by_family[key] = build_doc_source_index(manifest, family, packet_doc_id)
        repaired, repairs = repair_packet(packet, index_by_family[key])
        repaired_packets.append(repaired)
        records.append(
            {
                "packet_id": repaired.get("packet_id", ""),
                "source_group_id": repaired.get("source_group_id", ""),
                "packet_family": repaired.get("packet_family", ""),
                "repair_count": len(repairs),
                "repairs": repairs,
            }
        )

    repaired_payload = deepcopy(payload)
    repaired_payload["packet_candidates"] = repaired_packets
    repaired_payload.setdefault("summary", {})
    repaired_payload["summary"]["continuation_repair_version"] = REPAIR_VERSION
    repaired_payload["summary"]["continuation_repair_count"] = sum(record["repair_count"] for record in records)
    repaired_payload["summary"]["continuation_repaired_packet_count"] = sum(1 for record in records if record["repair_count"])
    summary = {
        "schema": "english_candidate_continuation_repair.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node5a_continuation_repair",
        "repair_version": REPAIR_VERSION,
        "source_question_packet_candidates_json": rel_workspace(source_path),
        "out_dir": rel_workspace(out_root),
        "packet_count": len(repaired_packets),
        "repaired_packet_count": sum(1 for record in records if record["repair_count"]),
        "repair_count": sum(record["repair_count"] for record in records),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "model_call_enabled": False,
        "repaired_question_packet_candidates_json": rel_workspace(out_root / "question_packet_candidates.repaired.json"),
        "repair_report_json": rel_workspace(out_root / "continuation_repair_report.json"),
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "question_packet_candidates.repaired.json", repaired_payload)
    write_json(out_root / "continuation_repair_report.json", {"schema": "english_candidate_continuation_repair.report_v0.1", "records": records, "summary": summary})
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(records, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-packet-candidates-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--packet-ids", nargs="*", default=[])
    parser.add_argument("--family", default="")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--output-root", default="outputs/english_text_first_pipeline_v02_spec_20260715/controlled_runs")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
