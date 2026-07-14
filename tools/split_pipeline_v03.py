from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tools.coordinate_audit_v03 import write_coordinate_audit_v03, write_nodes_overlay
from tools.crop_executor_v03 import execute_crops_v03
from tools.cross_page_node_accumulator_v03 import accumulate_nodes_v03, write_nodes, write_trace
from tools.layout_block_extractor_v03 import extract_block_candidates_v03, write_blocks
from tools.page_render_adapter_v03 import render_pdf_pages_v03, write_page_manifests
from tools.pdf_preflight_v03 import classify_pdf_v03
from tools.question_slice_auditor_v03 import audit_nodes_v03, write_audit_report
from tools.reading_block_builder_v03 import build_reading_blocks_v03, write_block_overlay, write_reading_blocks
from tools.semantic_block_assembler_v03 import mock_semantic_assignments_v03, visual_semantic_assignments_v03, write_assignments


def _portable_path(raw_path: str) -> str:
    if not raw_path:
        return ""
    path = Path(str(raw_path))
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())).replace("/", "\\")
    except Exception:
        return str(raw_path)


def run_split_v03_for_doc(
    pdf_path: str,
    doc_key: str,
    pages: list[int],
    out_dir: Path,
    provider: str = "mock",
    api_key: str = "",
    model: str = "doubao-seed-2-0-lite-260428",
    max_vlm_calls: int = 0,
) -> dict:
    doc_out = out_dir / "docs" / doc_key
    render_out = out_dir / "page_images"
    manifests = render_pdf_pages_v03(pdf_path, render_out, doc_key, pages=pages, provider="doubao")
    preflight = classify_pdf_v03(doc_key, pdf_path)
    blocks = extract_block_candidates_v03(
        pdf_path,
        manifests,
        doc_key,
        out_dir / "debug" / "blocks_overlay" / doc_key,
        provider=provider,
        api_key=api_key,
        model=model,
        max_vlm_calls=max_vlm_calls,
    )
    reading_blocks = build_reading_blocks_v03(blocks, manifests, doc_key)
    if provider == "visual":
        assignments = visual_semantic_assignments_v03(reading_blocks, doc_key=doc_key, api_key=api_key, model=model)
    else:
        assignments = mock_semantic_assignments_v03(reading_blocks)
    nodes, trace = accumulate_nodes_v03(reading_blocks, assignments)
    crop_records = execute_crops_v03(nodes, manifests, doc_out)
    audit_records = audit_nodes_v03(nodes)

    doc_out.mkdir(parents=True, exist_ok=True)
    write_page_manifests(doc_out / "page_manifests.json", manifests)
    write_blocks(doc_out / "blocks.json", blocks)
    write_reading_blocks(doc_out / "reading_blocks.json", reading_blocks)
    write_assignments(doc_out / "assignments.json", assignments)
    write_nodes(doc_out / "semantic_nodes.json", nodes)
    write_trace(doc_out / "open_node_trace.json", trace)
    write_audit_report(doc_out / "audit_report.json", audit_records)
    for manifest in manifests:
        write_block_overlay(
            out_dir / "debug" / "blocks_overlay" / doc_key / f"p{manifest.page:03d}_raw_blocks_overlay.png",
            manifest,
            blocks,
            f"{doc_key} p{manifest.page:03d} raw blocks",
        )
        write_block_overlay(
            out_dir / "debug" / "blocks_overlay" / doc_key / f"p{manifest.page:03d}_reading_blocks_overlay.png",
            manifest,
            reading_blocks,
            f"{doc_key} p{manifest.page:03d} reading blocks",
        )
        write_nodes_overlay(
            out_dir / "debug" / "nodes_overlay" / doc_key / f"p{manifest.page:03d}_semantic_nodes_overlay.png",
            manifest,
            nodes,
            f"{doc_key} p{manifest.page:03d} semantic nodes",
        )
    write_coordinate_audit_v03(out_dir, doc_key, manifests, blocks, reading_blocks, nodes)
    return {
        "doc_key": doc_key,
        "pdf_path": pdf_path,
        "preflight": asdict(preflight),
        "page_manifests": [asdict(m) for m in manifests],
        "blocks": [asdict(b) for b in blocks],
        "reading_blocks": [asdict(b) for b in reading_blocks],
        "assignments": [asdict(a) for a in assignments],
        "nodes": [asdict(n) for n in nodes],
        "audit_records": [asdict(r) for r in audit_records],
        "crop_records": crop_records,
        "trace": trace,
    }


def _audit_reason_map(audit_records: list[dict] | None = None) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    for record in audit_records or []:
        node_id = str(record.get("node_id", ""))
        if not node_id:
            continue
        reasons[node_id] = list(record.get("reasons", []) or [])
    return reasons


def _build_question_bridge_packet(node: dict, crop_records: dict, review_reasons: list[str] | None = None) -> dict:
    crop_record = crop_records.get(node["node_id"], {}) or {}
    composite = crop_record.get("question_composite") or crop_record.get("review_canvas", "")
    fragment_records = crop_record.get("fragment_records", []) or []
    bridge_fragments = []
    for idx, fragment in enumerate(node.get("fragments", []) or [], start=1):
        crop_fragment = fragment_records[idx - 1] if idx - 1 < len(fragment_records) else {}
        bridge_fragments.append(
            {
                "fragment_id": f"{node['node_id']}_fragment_{idx:02d}",
                "role": fragment.get("role", crop_fragment.get("role", "fragment")),
                "page": fragment.get("page", crop_fragment.get("page")),
                "bbox_px": fragment.get("bbox_px", crop_fragment.get("bbox_px", [])),
                "fragment_image": _portable_path(crop_fragment.get("path", "")),
                "coordinate_space": "page_master_px",
                "source_image_role": "source_page",
                "placement_scope": "evidence_only",
                "asset_role": "question_fragment_evidence",
                "source_block_ids": fragment.get("block_ids", []),
                "flags": fragment.get("flags", []),
            }
        )
    return {
        "question_id": node["node_id"],
        "question_uid": node["node_id"],
        "node_id": node["node_id"],
        "node_type": "question",
        "source": "semantic_v03",
        "text_stub": node.get("text_stub", ""),
        "fragments": node.get("fragments", []),
        "bridge_contract": {
            "version": "semantic_v03_bridge_v0.5",
            "transcription_input": "question_composite",
            "asset_source": "bridge_fragments",
            "coordinate_policy": "fragments_keep_page_master_px; composite_has_own_canvas_space",
            "option_prepare_policy": "do_not_detect_on_composite",
        },
        "question_image": _portable_path(composite),
        "stem_image": _portable_path(composite),
        "analysis_image": "",
        "transcription_image": _portable_path(composite),
        "review_canvas": _portable_path(crop_record.get("review_canvas", composite)),
        "question_composite": _portable_path(composite),
        "bridge_fragments": bridge_fragments,
        "staged_visual_assets": [],
        "gating_result": {
            "decision": "allow" if node.get("review_status") == "AUDITED_READY" else "review_required",
            "image_input_policy": "composite_first",
            "asset_detection_source": "bridge_fragments",
            "fragment_policy": "bridge_fragments_evidence_only",
            "requires_visual_transcription": True,
        },
        "review_status": node.get("review_status", ""),
        "review_reasons": list(review_reasons or []),
    }


def build_legacy_bridge(nodes: list[dict], crop_records: dict) -> dict:
    questions = []
    for node in nodes:
        if node.get("node_type") != "question":
            continue
        if node.get("review_status") != "AUDITED_READY":
            continue
        questions.append(_build_question_bridge_packet(node, crop_records))
    return {"schema": "legacy_bridge_questions_v0.5_composite_plus_fragments", "questions": questions}


def build_review_repair_pool(nodes: list[dict], crop_records: dict, audit_records: list[dict] | None = None) -> dict:
    """Preserve non-ready semantic nodes for repair instead of silently dropping content."""
    reasons_by_node = _audit_reason_map(audit_records)
    items = []
    for node in nodes:
        status = node.get("review_status", "")
        if status == "AUDITED_READY":
            continue
        reasons = reasons_by_node.get(node.get("node_id", ""), [])
        if node.get("node_type") == "question":
            packet = _build_question_bridge_packet(node, crop_records, reasons)
            packet["pool_item_type"] = "question_needs_repair"
            packet["allowed_next_actions"] = ["visual_refine", "manual_review", "rerun_split"]
            packet["auto_ingest_allowed"] = False
            items.append(packet)
            continue
        items.append(
            {
                "node_id": node.get("node_id", ""),
                "node_type": node.get("node_type", ""),
                "source": node.get("source", "semantic_v03"),
                "text_stub": node.get("text_stub", ""),
                "fragments": node.get("fragments", []),
                "review_status": status,
                "review_reasons": reasons,
                "pool_item_type": "non_question_needs_review",
                "allowed_next_actions": ["manual_review", "rerun_split"],
                "auto_ingest_allowed": False,
            }
        )
    return {"schema": "semantic_v03_review_repair_pool_v0.1", "items": items}


def summarize_nodes(all_nodes: list[dict]) -> dict:
    def page_set(node: dict) -> set[int]:
        return {int(fragment.get("page", 0) or 0) for fragment in node.get("fragments", [])}

    return {
        "ready": sum(1 for n in all_nodes if n.get("review_status") == "AUDITED_READY"),
        "needs_review": sum(1 for n in all_nodes if n.get("review_status") == "NEEDS_REVIEW"),
        "quarantined": sum(1 for n in all_nodes if n.get("review_status") == "QUARANTINED"),
        "question_nodes": sum(1 for n in all_nodes if n.get("node_type") == "question"),
        "knowledge_nodes": sum(1 for n in all_nodes if "knowledge" in str(n.get("node_type", ""))),
        "multi_fragment_nodes": sum(1 for n in all_nodes if len(n.get("fragments", [])) > 1),
        "cross_page_nodes": sum(1 for n in all_nodes if len(page_set(n)) > 1),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
