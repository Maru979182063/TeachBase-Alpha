from __future__ import annotations

from pathlib import Path


REQUIRED_FIELDS = [
    "case_id",
    "subject",
    "document_type",
    "source_document_ref",
    "source_document_sha256",
    "page_range",
    "node_id",
    "source_artifact_ref",
    "source_image_ref",
    "source_text_stub",
    "current_node_type",
    "current_review_status",
    "current_review_reasons",
    "expected_semantic_role",
    "expected_presentation_kind",
    "expected_disposition",
    "expected_route_candidate",
    "expected_relations",
    "expected_needs_role_review",
    "evaluation_tier",
    "gold_status",
    "gold_source",
    "gold_evidence",
    "difficulty_tags",
    "notes",
]

GOLD_STATUSES = {"VERIFIED", "REVIEW_REQUIRED", "UNVERIFIED"}
EVALUATION_TIERS = {"CONTRACT_FIXTURE", "VERIFIED_REAL_GOLD", "CANDIDATE_REVIEW"}
REAL_GOLD_SOURCES = {"existing_manual_audit", "human_review"}
GOLD_SOURCES = REAL_GOLD_SOURCES | {"fixture_contract", "candidate_discovery", "unverified"}

OUTPUT_FILES = [
    "evaluation_manifest.json",
    "verified_cases_snapshot.json",
    "predictions.json",
    "case_level_results.json",
    "metrics_summary.json",
    "per_role_metrics.json",
    "per_subject_metrics.json",
    "confusion_matrix.json",
    "critical_misroutes.json",
    "false_safe_cases.json",
    "review_capture_report.json",
    "confidence_calibration.json",
    "bad_cases.json",
    "dataset_coverage.json",
    "contract_fixture_snapshot.json",
    "real_gold_snapshot.json",
    "run_summary.json",
]


def default_cases_path(workspace_root: Path) -> Path:
    return workspace_root / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "fixture_cases.json"


def schema_path(workspace_root: Path) -> Path:
    return workspace_root / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "schema.json"
