from __future__ import annotations

from typing import Any


def run_semantic_role_adapter_shadow(
    *,
    semantic_nodes: dict[str, Any],
    audit_report: dict[str, Any],
    document_profile: dict[str, Any],
) -> dict[str, Any]:
    """Produce deterministic shadow-only role observations without changing the source nodes."""
    reasons_by_node = {
        str(record.get("node_id")): list(record.get("reasons") or [])
        for record in audit_report.get("records", [])
    }
    observations = []
    for node in semantic_nodes.get("nodes", []) or []:
        node_id = str(node.get("node_id") or "")
        current_type = str(node.get("node_type") or "")
        current_status = str(node.get("review_status") or "")
        observations.append(
            {
                "node_id": node_id,
                "current_node_type": current_type,
                "current_review_status": current_status,
                "shadow_role": current_type,
                "shadow_decision": "observe_only",
                "review_reasons": reasons_by_node.get(node_id, []),
                "would_mutate_pipeline": False,
            }
        )
    return {
        "schema_version": "semantic_role_adapter_results_shadow.v0.1",
        "adapter_mode": "deterministic_sidecar",
        "model_invoked": False,
        "prompt_content_changed": False,
        "document_profile_node_count": document_profile.get("node_count", 0),
        "observations": observations,
    }


def build_adapter_diff_report(*, semantic_nodes: dict[str, Any], adapter_results: dict[str, Any]) -> dict[str, Any]:
    by_node = {str(row.get("node_id")): row for row in adapter_results.get("observations", [])}
    diffs = []
    for node in semantic_nodes.get("nodes", []) or []:
        node_id = str(node.get("node_id") or "")
        row = by_node.get(node_id, {})
        current_type = str(node.get("node_type") or "")
        shadow_role = str(row.get("shadow_role") or "")
        if current_type != shadow_role:
            diffs.append(
                {
                    "node_id": node_id,
                    "current_node_type": current_type,
                    "shadow_role": shadow_role,
                    "business_mutation_allowed": False,
                }
            )
    return {
        "schema_version": "semantic_role_adapter_diff_report_shadow.v0.1",
        "diff_count": len(diffs),
        "business_mutation_allowed": False,
        "diffs": diffs,
    }
