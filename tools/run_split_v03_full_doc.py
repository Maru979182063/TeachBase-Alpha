from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
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
from tools.split_v03_refine_review_nodes import refine_nodes
from tools.run_semantic_role_adapter_shadow import run_shadow


def _page_count(pdf_path: Path) -> int:
    with fitz.open(pdf_path) as doc:
        return int(doc.page_count)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _count_visual_page_failures(raw_dir: Path) -> int:
    count = 0
    for meta_path in raw_dir.glob("p*.meta.json"):
        try:
            meta = _read_json(meta_path)
        except Exception:
            continue
        reason = str(((meta.get("coverage") or {}).get("reason") or ""))
        if reason == "visual_page_call_failed" or meta.get("error"):
            count += 1
    return count


def _write_stage_outputs(out_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    nodes = result["nodes"]
    crop_records = result["crop_records"]
    audit_records = result["audit_records"]
    bridge = build_legacy_bridge(nodes, crop_records)
    repair_pool = build_review_repair_pool(nodes, crop_records, audit_records)
    write_json(out_dir / "legacy_bridge_questions.json", bridge)
    write_json(out_dir / "review_repair_pool.json", repair_pool)
    return {"bridge": bridge, "repair_pool": repair_pool}


def run(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not pdf_path.exists():
        raise SystemExit(f"pdf_not_found: {pdf_path}")
    if args.provider == "visual" and not str(args.api_key or "").strip():
        raise SystemExit("missing_api_key_for_visual_provider")

    page_total = _page_count(pdf_path)
    pages = list(range(1, page_total + 1))
    max_vlm_calls = int(args.max_vlm_calls or max(page_total * 4, page_total))

    result = run_split_v03_for_doc(
        str(pdf_path),
        str(args.doc_key),
        pages,
        out_dir,
        provider=str(args.provider),
        api_key=str(args.api_key or ""),
        model=str(args.model or ""),
        max_vlm_calls=max_vlm_calls,
    )
    stage = _write_stage_outputs(out_dir, result)
    semantic_shadow_summary: dict[str, Any] | None = None
    shadow_enabled = bool(args.semantic_role_shadow or str(os.environ.get("SEMANTIC_ROLE_ADAPTER_SHADOW", "")).strip() == "1")
    if shadow_enabled:
        doc_dir = out_dir / "docs" / str(args.doc_key)
        semantic_shadow_summary = run_shadow(
            doc_dir=doc_dir,
            out_dir=out_dir / "semantic_role_shadow",
            pdf_path=str(pdf_path),
            doc_key=str(args.doc_key),
            provider=str(args.semantic_role_provider or "mock"),
            api_key=str(args.api_key or ""),
            model=str(args.semantic_role_model or args.model or ""),
            batch_size=int(args.semantic_role_batch_size),
            max_calls=int(args.semantic_role_max_calls),
            baseline_files=[
                doc_dir / "semantic_nodes.json",
                out_dir / "legacy_bridge_questions.json",
                out_dir / "review_repair_pool.json",
            ],
        )
    initial_summary = {
        "node_summary": summarize_nodes(result["nodes"]),
        "ready_bridge_count": len(stage["bridge"].get("questions", [])),
        "repair_pool_count": len(stage["repair_pool"].get("items", [])),
        "visual_page_call_failed_count": _count_visual_page_failures(out_dir / "debug" / "blocks_overlay" / str(args.doc_key) / "raw_model_responses"),
    }

    refined_report: dict[str, Any] | None = None
    refined_summary: dict[str, Any] | None = None
    if args.refine:
        doc_dir = out_dir / "docs" / str(args.doc_key)
        refined_out = out_dir / "refined"
        refined_report = refine_nodes(
            doc_dir=doc_dir,
            semantic_nodes_path=doc_dir / "semantic_nodes.json",
            audit_path=doc_dir / "audit_report.json",
            out_dir=refined_out,
            api_key=str(args.api_key or ""),
            model=str(args.model or ""),
            max_nodes=int(args.max_refine_nodes),
        )
        refined_nodes_path = refined_out / "semantic_nodes_refined.json"
        refined_audit_path = refined_out / "audit_report_refined.json"
        if refined_nodes_path.exists() and refined_audit_path.exists():
            refined_nodes = _read_json(refined_nodes_path).get("nodes", [])
            refined_bridge = _read_json(refined_out / "legacy_bridge_questions_refined.json")
            refined_pool = _read_json(refined_out / "review_repair_pool_refined.json")
            refined_summary = {
                "node_summary": summarize_nodes(refined_nodes),
                "ready_bridge_count": len(refined_bridge.get("questions", [])),
                "repair_pool_count": len(refined_pool.get("items", [])),
                "actual_vlm_calls": refined_report.get("actual_vlm_calls", 0),
                "vlm_calls_by_stage": refined_report.get("vlm_calls_by_stage", {}),
            }

    summary = {
        "schema": "split_v03_full_doc_run_v0.1",
        "entry": "tools/run_split_v03_full_doc.py",
        "pdf": str(pdf_path),
        "doc_key": str(args.doc_key),
        "page_count": page_total,
        "pages_requested": len(pages),
        "provider": str(args.provider),
        "model": str(args.model or ""),
        "max_vlm_calls": max_vlm_calls,
        "initial": initial_summary,
        "refine_enabled": bool(args.refine),
        "refined": refined_summary,
        "semantic_role_shadow_enabled": shadow_enabled,
        "semantic_role_shadow": semantic_shadow_summary,
        "artifacts": {
            "doc_dir": str(out_dir / "docs" / str(args.doc_key)),
            "page_manifests": str(out_dir / "docs" / str(args.doc_key) / "page_manifests.json"),
            "semantic_nodes": str(out_dir / "docs" / str(args.doc_key) / "semantic_nodes.json"),
            "audit_report": str(out_dir / "docs" / str(args.doc_key) / "audit_report.json"),
            "legacy_bridge_questions": str(out_dir / "legacy_bridge_questions.json"),
            "review_repair_pool": str(out_dir / "review_repair_pool.json"),
            "refined_dir": str(out_dir / "refined") if args.refine else "",
            "run_summary": str(out_dir / "full_doc_run_summary.json"),
            "semantic_role_shadow_dir": str(out_dir / "semantic_role_shadow") if shadow_enabled else "",
        },
    }
    write_json(out_dir / "full_doc_run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run split_v03 on every page of one handout PDF.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--doc-key", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", default="visual", choices=["mock", "visual"])
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--max-vlm-calls", type=int, default=0)
    parser.add_argument("--refine", action="store_true")
    parser.add_argument("--max-refine-nodes", type=int, default=80)
    parser.add_argument("--semantic-role-shadow", action="store_true")
    parser.add_argument("--semantic-role-provider", default="mock", choices=["mock", "visual"])
    parser.add_argument("--semantic-role-model", default="")
    parser.add_argument("--semantic-role-batch-size", type=int, default=8)
    parser.add_argument("--semantic-role-max-calls", type=int, default=12)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
