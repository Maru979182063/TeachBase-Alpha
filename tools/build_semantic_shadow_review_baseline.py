from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.semantic_shadow_compare import canonical_hash
from tools.split_pipeline_v03 import build_legacy_bridge, build_review_repair_pool, summarize_nodes


CORE_ARTIFACTS = [
    "docs/synthetic_review/assignments.json",
    "docs/synthetic_review/semantic_nodes.json",
    "docs/synthetic_review/audit_report.json",
    "legacy_bridge_questions.json",
    "review_repair_pool.json",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_fixture() -> dict[str, Any]:
    assignments = [
        {
            "block_id": "synthetic_rb0001",
            "node_id": "synthetic_ready_q_001",
            "role": "question_body",
            "confidence": 1.0,
            "provider": "deterministic_fixture",
        },
        {
            "block_id": "synthetic_rb0002",
            "node_id": "synthetic_ready_q_001",
            "role": "answer_block",
            "confidence": 1.0,
            "provider": "deterministic_fixture",
        },
        {
            "block_id": "synthetic_rb0003",
            "node_id": "synthetic_review_q_002",
            "role": "question_body",
            "confidence": 1.0,
            "provider": "deterministic_fixture",
        },
        {
            "block_id": "synthetic_rb0004",
            "node_id": "synthetic_orphan_003",
            "role": "orphan_block",
            "confidence": 1.0,
            "provider": "deterministic_fixture",
        },
    ]
    nodes = [
        {
            "node_id": "synthetic_ready_q_001",
            "node_type": "question",
            "source": "semantic_v03",
            "fragments": [
                {
                    "page": 1,
                    "bbox_px": [120, 140, 880, 360],
                    "role": "question_body",
                    "block_ids": ["synthetic_rb0001"],
                    "flags": ["possible_question_start", "reading_block"],
                },
                {
                    "page": 1,
                    "bbox_px": [120, 370, 520, 450],
                    "role": "answer_block",
                    "block_ids": ["synthetic_rb0002"],
                    "flags": ["answer_like", "reading_block"],
                },
            ],
            "review_status": "AUDITED_READY",
            "text_stub": "Synthetic deterministic ready question with answer evidence.",
        },
        {
            "node_id": "synthetic_review_q_002",
            "node_type": "question",
            "source": "semantic_v03",
            "fragments": [
                {
                    "page": 1,
                    "bbox_px": [120, 900, 900, 1180],
                    "role": "question_body",
                    "block_ids": ["synthetic_rb0003"],
                    "flags": ["possible_question_start", "reading_block", "near_page_bottom"],
                }
            ],
            "review_status": "NEEDS_REVIEW",
            "text_stub": "Synthetic review question intentionally near page bottom.",
        },
        {
            "node_id": "synthetic_orphan_003",
            "node_type": "quarantined_orphan",
            "source": "semantic_v03",
            "fragments": [
                {
                    "page": 2,
                    "bbox_px": [90, 120, 760, 260],
                    "role": "orphan_block",
                    "block_ids": ["synthetic_rb0004"],
                    "flags": ["orphan_candidate", "reading_block"],
                }
            ],
            "review_status": "QUARANTINED",
            "text_stub": "Synthetic orphan block without a resolved owning question.",
        },
    ]
    audit_records = [
        {"node_id": "synthetic_ready_q_001", "status": "AUDITED_READY", "reasons": []},
        {"node_id": "synthetic_review_q_002", "status": "NEEDS_REVIEW", "reasons": ["page_bottom_may_continue"]},
        {"node_id": "synthetic_orphan_003", "status": "QUARANTINED", "reasons": ["orphan_unresolved"]},
    ]
    crop_records = {
        "synthetic_ready_q_001": {
            "question_composite": "fixtures/semantic_shadow_review_path/assets/synthetic_ready_q_001_review_canvas.png",
            "review_canvas": "fixtures/semantic_shadow_review_path/assets/synthetic_ready_q_001_review_canvas.png",
            "fragment_records": [
                {
                    "path": "fixtures/semantic_shadow_review_path/assets/synthetic_ready_q_001_fragment_01.png",
                    "role": "question_body",
                    "page": 1,
                    "bbox_px": [120, 140, 880, 360],
                },
                {
                    "path": "fixtures/semantic_shadow_review_path/assets/synthetic_ready_q_001_fragment_02.png",
                    "role": "answer_block",
                    "page": 1,
                    "bbox_px": [120, 370, 520, 450],
                },
            ],
        },
        "synthetic_review_q_002": {
            "question_composite": "fixtures/semantic_shadow_review_path/assets/synthetic_review_q_002_review_canvas.png",
            "review_canvas": "fixtures/semantic_shadow_review_path/assets/synthetic_review_q_002_review_canvas.png",
            "fragment_records": [
                {
                    "path": "fixtures/semantic_shadow_review_path/assets/synthetic_review_q_002_fragment_01.png",
                    "role": "question_body",
                    "page": 1,
                    "bbox_px": [120, 900, 900, 1180],
                }
            ],
        },
    }
    return {
        "schema_version": "semantic_shadow_review_path_fixture.v0.1",
        "description": "Deterministic synthetic review/quarantine baseline. No paid model call and no restricted source text.",
        "assignments": assignments,
        "nodes": nodes,
        "audit_records": audit_records,
        "crop_records": crop_records,
    }


def build_baseline(out_root: Path) -> dict[str, Any]:
    fixture = build_fixture()
    nodes = fixture["nodes"]
    assignments = fixture["assignments"]
    audit_records = fixture["audit_records"]
    crop_records = fixture["crop_records"]

    docs_root = out_root / "docs" / "synthetic_review"
    _write_json(out_root / "input" / "synthetic_review_path_fixture.json", fixture)
    _write_json(docs_root / "assignments.json", {"schema": "semantic_assignments_v0.3", "assignments": assignments})
    _write_json(docs_root / "semantic_nodes.json", {"schema": "semantic_nodes_v0.3", "nodes": nodes})
    _write_json(docs_root / "audit_report.json", {"schema": "audit_report_v0.3", "records": audit_records})
    _write_json(out_root / "legacy_bridge_questions.json", build_legacy_bridge(nodes, crop_records))
    _write_json(out_root / "review_repair_pool.json", build_review_repair_pool(nodes, crop_records, audit_records))

    artifact_hashes: dict[str, Any] = {
        "schema_version": "pipeline_baseline_artifact_hashes.v0.1",
        "artifacts": [],
    }
    canonical_hashes: dict[str, str] = {}
    ignored_counts: dict[str, int] = {}
    for rel in CORE_ARTIFACTS:
        path = out_root / rel
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        c_hash, ignored = canonical_hash(payload, roots=[Path.cwd(), out_root])
        canonical_hashes[rel] = c_hash
        ignored_counts[rel] = ignored
        artifact_hashes["artifacts"].append(
            {
                "artifact": rel,
                "path": str(path),
                "sha256": _sha256_file(path),
                "canonical_sha256": c_hash,
                "ignored_field_count": ignored,
            }
        )
    _write_json(out_root / "artifact_hashes.json", artifact_hashes)

    node_summary = summarize_nodes(nodes)
    review_repair_pool = json.loads((out_root / "review_repair_pool.json").read_text(encoding="utf-8-sig"))
    legacy_bridge = json.loads((out_root / "legacy_bridge_questions.json").read_text(encoding="utf-8-sig"))
    review_reasons = [
        reason
        for record in audit_records
        for reason in (record.get("reasons") or [])
    ]
    metrics = {
        "schema_version": "pipeline_baseline_metrics.v0.3",
        "metrics": {
            "nodes": len(nodes),
            "legacy_bridge_ready_count": len(legacy_bridge.get("questions", [])),
            "review_repair_pool_count": len(review_repair_pool.get("items", [])),
            "review_status": {
                "AUDITED_READY": node_summary["ready"],
                "NEEDS_REVIEW": node_summary["needs_review"],
                "QUARANTINED": node_summary["quarantined"],
            },
            "review_reasons": review_reasons,
            "node_summary": node_summary,
        },
    }
    _write_json(out_root / "metrics.json", metrics)

    command = f"python tools/build_semantic_shadow_review_baseline.py --out {out_root.as_posix()}"
    manifest = {
        "schema_version": "pipeline_baseline_manifest.v0.3",
        "baseline_id": "semantic_shadow_review_path_20260714_v01",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_type": "deterministic",
        "baseline_scope": "review/quarantine non-interference path for Semantic Role Shadow isolation",
        "entrypoint": "tools/build_semantic_shadow_review_baseline.py",
        "command": command,
        "input": {
            "path": str(out_root / "input" / "synthetic_review_path_fixture.json"),
            "exists": True,
            "sha256": _sha256_file(out_root / "input" / "synthetic_review_path_fixture.json"),
            "restricted_business_text": False,
            "external_absolute_path_required": False,
        },
        "provider": "deterministic_fixture",
        "model": "",
        "paid_vlm_used": False,
        "actual_vlm_calls": 0,
        "core_artifacts": CORE_ARTIFACTS,
        "canonical_hashes": canonical_hashes,
        "ignored_field_counts": ignored_counts,
        "metrics": metrics["metrics"],
        "required_core_artifacts_present": all((out_root / rel).exists() for rel in CORE_ARTIFACTS),
        "canonical_normalization_policy": {
            "ignored_non_business_fields": [
                "absolute_path_prefix",
                "created_at",
                "started_at",
                "finished_at",
                "run_id",
                "temporary_output_directory",
                "request_id_when_explicitly_random",
            ],
            "strict_business_fields": [
                "node_count",
                "node_type",
                "fragment_page_and_bbox",
                "review_status",
                "audit_reasons",
                "legacy_bridge_question_count",
                "repair_pool_content",
                "asset_count_and_ownership",
                "release_decision",
                "runtime_import_payload_business_fields",
            ],
        },
    }
    _write_json(out_root / "baseline_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Semantic Shadow review-path baseline artifacts.")
    parser.add_argument("--out", default="outputs/pipeline_baseline_snapshot/semantic_shadow_review_path_20260714_v01")
    args = parser.parse_args()
    out_root = Path(args.out)
    manifest = build_baseline(out_root)
    print(json.dumps({"ok": True, "baseline_id": manifest["baseline_id"], "out": str(out_root)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
