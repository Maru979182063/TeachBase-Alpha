from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import build_final_chain_adapters
from .control import ChainRunRequest, FinalChainRegistry
from .environment import inspect_chain_environment


def _readiness_tier(env_status: str, dry_run_status: str, smoke_status: str) -> str:
    if env_status == "ready" and dry_run_status == "dry_run_ready":
        return "ready_for_adapter_dry_run"
    if env_status == "ready":
        return "environment_ready_input_needed"
    if smoke_status == "partial":
        return "restore_or_rerun_required"
    return "cleanroom_import_required"


def _recommended_actions(tier: str, blocked_reasons: list[str]) -> list[str]:
    actions: list[str] = []
    if "required_paths_present" in blocked_reasons:
        actions.append("import_or_restore_canonical_entrypoint_and_configs")
    if "smoke_status_not_partial" in blocked_reasons:
        actions.append("promote_full_raw_pdf_graph_first_smoke_before_ready_claim")
    if tier == "restore_or_rerun_required":
        actions.append("restore_active_manifest_or_rerun_smoke_artifacts")
    if tier == "environment_ready_input_needed":
        actions.append("provide_existing_input_file_for_adapter_dry_run")
    if tier == "ready_for_adapter_dry_run":
        actions.append("wire_real_adapter_dry_run_without_model_or_database_side_effects")
    if not actions:
        actions.append("inspect_blocked_reasons_before_execution")
    return actions


def build_readiness_matrix(
    registry: FinalChainRegistry,
    *,
    workspace_root: Path,
    sample_inputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    sample_inputs = sample_inputs or {}
    adapters = build_final_chain_adapters(registry, workspace_root=workspace_root)
    rows: list[dict[str, Any]] = []
    for chain in registry.chains:
        env = inspect_chain_environment(chain, workspace_root=workspace_root)
        sample_input = sample_inputs.get(chain.chain_id, f"missing.{chain.input_format}")
        request = ChainRunRequest(chain_id=chain.chain_id, input_path=sample_input, output_root="outputs/final_chain_runs")
        dry_run = adapters[chain.chain_id].dry_run(request)
        blocked_reasons = sorted(set(env["blocked_reasons"]) | set(dry_run["plan"].get("blocked_reasons", [])))
        tier = _readiness_tier(env["status"], dry_run["status"], chain.smoke_status)
        rows.append(
            {
                "chain_id": chain.chain_id,
                "display_name": chain.display_name,
                "input_format": chain.input_format,
                "subject": chain.subject,
                "registry_readiness": chain.registry_readiness,
                "smoke_status": chain.smoke_status,
                "environment_status": env["status"],
                "adapter_dry_run_status": dry_run["status"],
                "readiness_tier": tier,
                "blocked_reasons": blocked_reasons,
                "required_path_count": len(env["required_paths"]),
                "required_path_missing_count": sum(1 for item in env["required_paths"] if not item["exists"]),
                "optional_path_missing_count": env["optional_path_summary"]["missing"],
                "recommended_actions": _recommended_actions(tier, blocked_reasons),
                "execution_contract": dry_run["execution_contract"],
            }
        )
    tier_counts: dict[str, int] = {}
    for row in rows:
        tier_counts[row["readiness_tier"]] = tier_counts.get(row["readiness_tier"], 0) + 1
    return {
        "schema_version": "final_chain_readiness_matrix.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_count": len(rows),
        "tier_counts": tier_counts,
        "ready_for_adapter_dry_run_count": tier_counts.get("ready_for_adapter_dry_run", 0),
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
        "rows": rows,
    }
