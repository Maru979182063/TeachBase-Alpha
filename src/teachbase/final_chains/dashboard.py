from __future__ import annotations

from typing import Any

from .control import FinalChainRegistry
from .environment import inspect_adapter_contracts
from .jobs import ALLOWED_TRANSITIONS, TERMINAL_STATUSES
from .readiness import build_readiness_matrix


def build_final_chain_control_dashboard(
    registry: FinalChainRegistry,
    *,
    workspace_root,
    sample_inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    readiness = build_readiness_matrix(registry, workspace_root=workspace_root, sample_inputs=sample_inputs)
    contracts = inspect_adapter_contracts(registry)
    rows = []
    for row in readiness["rows"]:
        rows.append(
            {
                "chain_id": row["chain_id"],
                "display_name": row["display_name"],
                "input_format": row["input_format"],
                "subject": row["subject"],
                "lane": _lane_for_tier(row["readiness_tier"]),
                "readiness_tier": row["readiness_tier"],
                "environment_status": row["environment_status"],
                "adapter_dry_run_status": row["adapter_dry_run_status"],
                "blocked_reasons": row["blocked_reasons"],
                "recommended_actions": row["recommended_actions"],
                "scheduler_entrypoint": "tools/final_chain_control.py schedule",
                "adapter_dry_run_entrypoint": "tools/final_chain_control.py adapter-dry-run",
                "job_record_contract": "final_chain_job_record.v0.1",
            }
        )
    lane_counts: dict[str, int] = {}
    for row in rows:
        lane_counts[row["lane"]] = lane_counts.get(row["lane"], 0) + 1
    return {
        "schema_version": "final_chain_control_dashboard.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_count": readiness["chain_count"],
        "lane_counts": lane_counts,
        "contract_ok": contracts["ok"],
        "readiness_tier_counts": readiness["tier_counts"],
        "job_lifecycle_policy": {
            "schema_version": "final_chain_job_lifecycle.v0.1",
            "terminal_statuses": sorted(TERMINAL_STATUSES),
            "allowed_transitions": {key: list(value) for key, value in sorted(ALLOWED_TRANSITIONS.items())},
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
        "rows": rows,
    }


def _lane_for_tier(tier: str) -> str:
    if tier == "ready_for_adapter_dry_run":
        return "adapter_dry_run_ready"
    if tier == "environment_ready_input_needed":
        return "needs_sample_input"
    if tier == "restore_or_rerun_required":
        return "needs_artifact_restore_or_smoke"
    if tier == "cleanroom_import_required":
        return "needs_cleanroom_import"
    return "needs_manual_review"
