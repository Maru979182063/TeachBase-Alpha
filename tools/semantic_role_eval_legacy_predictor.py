from __future__ import annotations

from pathlib import Path
from typing import Any

from teachbase.semantic_role.evaluator import case_to_node

try:
    from .document_profile_resolver import resolve_document_profile
    from .semantic_role_adapter import run_semantic_role_adapter_shadow
except ImportError:
    from document_profile_resolver import resolve_document_profile
    from semantic_role_adapter import run_semantic_role_adapter_shadow


def predict_case(case: dict[str, Any], run_id: str, workspace_root: Path) -> dict[str, Any]:
    node = case_to_node(case)
    semantic_nodes = {"schema": "semantic_nodes_eval_v0.1", "nodes": [node]}
    audit_report = {
        "schema": "audit_report_eval_v0.1",
        "records": [
            {
                "node_id": case["node_id"],
                "status": case["current_review_status"],
                "reasons": list(case.get("current_review_reasons") or []),
            }
        ],
    }
    profile = resolve_document_profile(
        doc_root=workspace_root / "tests" / "fixtures" / "semantic_role_effectiveness_v01",
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
        doc_key=str(case.get("subject") or "unknown"),
        source_run_id=run_id,
    )
    adapter_results = run_semantic_role_adapter_shadow(
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
        document_profile=profile,
    )
    observation = dict((adapter_results.get("observations") or [{}])[0])
    return {
        "case_id": case["case_id"],
        "node_id": case["node_id"],
        "semantic_role": observation.get("shadow_role", ""),
        "presentation_kind": observation.get("presentation_kind", ""),
        "disposition": observation.get("disposition_candidate", ""),
        "route_candidate": observation.get("route_candidate", ""),
        "effective_route_candidate": observation.get("effective_route_candidate", ""),
        "confidence": observation.get("confidence", 0.0),
        "needs_role_review": bool(observation.get("needs_role_review", False)),
        "relations": observation.get("relations", []),
        "hard_constraints_passed": bool(observation.get("hard_constraints_passed", False)),
        "review_reasons": observation.get("review_reasons", []),
        "evidence": observation.get("evidence", []),
        "model_invoked": False,
        "paid_model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
    }
