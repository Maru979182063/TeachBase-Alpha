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
from tools.semantic_block_assembler_v03 import mock_semantic_assignments_v03, write_assignments


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


def build_legacy_bridge(nodes: list[dict], crop_records: dict) -> dict:
    questions = []
    for node in nodes:
        if node.get("node_type") != "question":
            continue
        if node.get("review_status") != "AUDITED_READY":
            continue
        crop_record = crop_records.get(node["node_id"], {}) or {}
        composite = crop_record.get("question_composite") or crop_record.get("review_canvas", "")
        fragment_records = crop_record.get("fragment_records", []) or []
        staged_assets = []
        for idx, fragment in enumerate(node.get("fragments", []) or [], start=1):
            crop_fragment = fragment_records[idx - 1] if idx - 1 < len(fragment_records) else {}
            staged_assets.append(
                {
                    "asset_id": f"{node['node_id']}_fragment_{idx:02d}",
                    "asset_role": "question_fragment_evidence",
                    "attach_status": "evidence_only",
                    "role": fragment.get("role", crop_fragment.get("role", "fragment")),
                    "page": fragment.get("page", crop_fragment.get("page")),
                    "bbox_px": fragment.get("bbox_px", crop_fragment.get("bbox_px", [])),
                    "asset_path": crop_fragment.get("path", ""),
                    "source_block_ids": fragment.get("block_ids", []),
                    "flags": fragment.get("flags", []),
                }
            )
        questions.append({
            "question_id": node["node_id"],
            "question_uid": node["node_id"],
            "node_id": node["node_id"],
            "node_type": "question",
            "source": "semantic_v03",
            "fragments": node.get("fragments", []),
            "question_image": composite,
            "stem_image": composite,
            "analysis_image": "",
            "review_canvas": crop_record.get("review_canvas", composite),
            "question_composite": composite,
            "staged_visual_assets": staged_assets,
            "gating_result": {
                "decision": "allow",
                "image_input_policy": "composite_first",
                "fragment_policy": "evidence_only",
                "requires_visual_transcription": True,
            },
            "review_status": "AUDITED_READY",
        })
    return {"schema": "legacy_bridge_questions_v0.4_composite_first", "questions": questions}


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
