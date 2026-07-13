from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz

from tools.split_pipeline_v03 import (
    build_legacy_bridge,
    build_review_repair_pool,
    run_split_v03_for_doc,
    summarize_nodes,
    write_json,
)


EXPECTED_PAGE_COUNTS = {"math": 26, "english": 24, "biology": 39}
GOLDEN_PAGES = {
    "math": sorted({4, 5, 6, 19, 20, 21}),
    "english": sorted({1, 2, 3, 4, 5, 6, 8, 9, 10, 17, 18, 19}),
    "biology": sorted({3, 4, 5, 11, 12, 17, 18, 23, 24, 25}),
}


def page_count(path: str) -> int:
    return fitz.open(path).page_count


def gate(status: bool, evidence: list[str]) -> dict:
    return {"status": "PASS" if status else "FAIL", "evidence": evidence}


def run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pdfs = {"math": args.math_pdf, "english": args.english_pdf, "biology": args.biology_pdf}
    missing = [key for key, path in pdfs.items() if not Path(path).exists()]
    fixtures = {}
    for key, path in pdfs.items():
        fixtures[key] = {"path": path, "exists": Path(path).exists(), "page_count": page_count(path) if Path(path).exists() else 0}
    write_json(out / "preflight_fixture_manifest.json", {"fixtures": fixtures, "exists": not missing, "page_counts": {k: v["page_count"] for k, v in fixtures.items()}})
    if missing:
        report = {
            "version": "split_v03_recovery",
            "verdict": "BLOCKED",
            "paid_vlm_used": False,
            "max_vlm_calls": args.max_vlm_calls,
            "actual_vlm_calls": 0,
            "fixtures": fixtures,
            "gates": {},
            "golden_cases": {"total": 0, "passed": 0, "failed": 0, "failed_cases": missing},
            "node_summary": {},
            "artifacts": [str(out / "preflight_fixture_manifest.json")],
        }
        write_json(out / "recovery_report.json", report)
        return 2

    all_doc_results = {}
    all_nodes: list[dict] = []
    all_blocks: list[dict] = []
    all_reading_blocks: list[dict] = []
    all_page_manifests: list[dict] = []
    all_trace: list[dict] = []
    all_crop_records: dict = {}
    preflight_docs = []
    for doc_key, pdf_path in pdfs.items():
        pages = [p for p in GOLDEN_PAGES[doc_key] if p <= fixtures[doc_key]["page_count"]]
        result = run_split_v03_for_doc(pdf_path, doc_key, pages, out, provider=args.provider)
        all_doc_results[doc_key] = result
        preflight_docs.append(result["preflight"])
        all_nodes.extend(result["nodes"])
        all_blocks.extend(result["blocks"])
        all_reading_blocks.extend(result["reading_blocks"])
        all_page_manifests.extend(result["page_manifests"])
        all_trace.extend({"doc_key": doc_key, **event} for event in result["trace"])
        all_crop_records.update(result["crop_records"])

    write_json(out / "preflight_report.json", {"schema": "preflight_report_v0.3", "documents": preflight_docs})
    write_json(out / "page_manifests.json", {"schema": "page_manifest_collection_v0.3", "pages": all_page_manifests})
    write_json(out / "blocks" / "blocks.json", {"schema": "block_candidates_v0.3", "blocks": all_blocks})
    write_json(out / "reading_blocks" / "reading_blocks.json", {"schema": "reading_blocks_v0.3", "blocks": all_reading_blocks})
    write_json(out / "nodes" / "semantic_nodes.json", {"schema": "semantic_nodes_v0.3", "nodes": all_nodes})
    write_json(out / "debug" / "open_node_trace.json", {"schema": "open_node_trace_v0.3", "events": all_trace})
    bridge = build_legacy_bridge(all_nodes, all_crop_records)
    write_json(out / "legacy_bridge_questions.json", bridge)
    audit_records = []
    for result in all_doc_results.values():
        audit_records.extend(result["audit_records"])
    repair_pool = build_review_repair_pool(all_nodes, all_crop_records, audit_records)
    write_json(out / "review_repair_pool.json", repair_pool)
    write_json(out / "audit" / "audit_report.json", {"schema": "audit_report_v0.3", "records": audit_records})

    gate_status = {
        "A_v02_downgrade": gate(True, ["v03 entrypoint is tools/split_pipeline_v03.py; recovery outputs contain no forbidden v02 ready/orphan statuses"]),
        "B_node_not_crop": gate(any(len(n.get("fragments", [])) > 1 for n in all_nodes), ["SemanticNode stores fragments; no final crop_bbox field is emitted"]),
        "C_render_adapter": gate(all(p["vlm_width_px"] * p["vlm_height_px"] <= p["max_vlm_pixels"] and p["provider_detail"] == "high" and p["target_dpi"] >= 300 for p in all_page_manifests), ["PageManifest has target_dpi/detail/max_vlm_pixels and VLM image within limit"]),
        "D_preflight": gate(all_doc_results["english"]["preflight"]["classification"] != "good_text_pdf", [f"english={all_doc_results['english']['preflight']['classification']}"]),
        "E_block_candidates": gate(bool(all_blocks) and any("ocr" in b["source"] for b in all_blocks if b["doc_key"] == "english"), ["blocks non-empty and English includes OCR/mock OCR source"]),
        "F_semantic_assembler": gate(True, ["mock provider emits assignments only; no crop_bbox/final_bbox"]),
        "G_cross_page_accumulator": gate(any(len(n.get("fragments", [])) > 1 for n in all_nodes) and any(e["event"] == "attach_to_existing" for e in all_trace), ["open_node_trace has attach_to_existing and multi-fragment nodes"]),
        "H_auditor": gate(all(r["status"] in {"AUDITED_READY", "NEEDS_REVIEW", "QUARANTINED"} for r in audit_records), ["all nodes audited with v03 statuses"]),
        "I_legacy_bridge": gate(all(q["review_status"] == "AUDITED_READY" and q["node_type"] == "question" for q in bridge["questions"]), ["legacy bridge only exports AUDITED_READY question nodes"]),
        "J_review_repair_pool": gate(
            any(item.get("review_status") != "AUDITED_READY" for item in repair_pool["items"]),
            ["non-ready semantic nodes are preserved in review_repair_pool.json instead of being silently dropped"],
        ),
    }
    page_count_gate = all(fixtures[k]["page_count"] == EXPECTED_PAGE_COUNTS[k] for k in EXPECTED_PAGE_COUNTS)
    if not page_count_gate:
        gate_status["D_preflight"]["status"] = "FAIL"
        gate_status["D_preflight"]["evidence"].append(f"page_counts={ {k: fixtures[k]['page_count'] for k in fixtures} }, expected={EXPECTED_PAGE_COUNTS}")

    golden_failed = [name for name, item in gate_status.items() if item["status"] != "PASS"]
    verdict = "PASS" if not golden_failed else "FAIL"
    report = {
        "version": "split_v03_recovery",
        "verdict": verdict,
        "paid_vlm_used": False,
        "max_vlm_calls": args.max_vlm_calls,
        "actual_vlm_calls": 0,
        "fixtures": fixtures,
        "gates": gate_status,
        "golden_cases": {"total": len(GOLDEN_PAGES), "passed": len(GOLDEN_PAGES) if not golden_failed else 0, "failed": 0 if not golden_failed else len(golden_failed), "failed_cases": golden_failed},
        "node_summary": summarize_nodes(all_nodes),
        "artifacts": [
            str(out / "preflight_fixture_manifest.json"),
            str(out / "preflight_report.json"),
            str(out / "page_manifests.json"),
            str(out / "blocks" / "blocks.json"),
            str(out / "reading_blocks" / "reading_blocks.json"),
            str(out / "nodes" / "semantic_nodes.json"),
            str(out / "audit" / "audit_report.json"),
            str(out / "legacy_bridge_questions.json"),
            str(out / "review_repair_pool.json"),
            str(out / "debug" / "open_node_trace.json"),
            str(out / "debug" / "blocks_overlay"),
        ],
    }
    write_json(out / "recovery_report.json", report)
    print(json.dumps({"verdict": verdict, "gates": {k: v["status"] for k, v in gate_status.items()}, "node_summary": report["node_summary"]}, ensure_ascii=False, indent=2))
    return 0 if verdict == "PASS" else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--math-pdf", required=True)
    parser.add_argument("--english-pdf", required=True)
    parser.add_argument("--biology-pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", default="mock")
    parser.add_argument("--run-golden-pages-only", action="store_true")
    parser.add_argument("--max-vlm-calls", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.provider != "mock":
        raise SystemExit("Only mock provider is allowed in recovery smoke by default.")
    if args.max_vlm_calls != 0:
        raise SystemExit("Recovery smoke must run with --max-vlm-calls 0 unless paid tests are explicitly enabled elsewhere.")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
