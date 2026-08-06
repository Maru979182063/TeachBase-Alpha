from __future__ import annotations

from pathlib import Path
from typing import Any

from .control import ChainRunRequest, FinalChainDefinition, build_portable_plan_snapshot, build_request_snapshot

FINAL_CHAIN_JOB_STATUSES = (
    "queued",
    "running",
    "waiting_review",
    "failed_retryable",
    "failed_final",
    "completed",
)

STANDARD_EXECUTION_ARGS = (
    "--chain-id",
    "--input",
    "--output-root",
    "--job-id",
    "--attempt",
    "--resume-from-checkpoint",
    "--emit-job-result",
)


def build_execution_preflight(
    *,
    chain: FinalChainDefinition,
    request: ChainRunRequest,
    plan: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    standard_cli_contract = _standard_cli_contract(chain)
    blocked_reasons = _preflight_blocked_reasons(plan, standard_cli_contract)
    status = "execution_preflight_ready" if not blocked_reasons else "execution_preflight_blocked"
    return {
        "schema_version": "final_chain_execution_preflight.v0.1",
        "chain_id": chain.chain_id,
        "status": status,
        "blocked_reasons": blocked_reasons,
        "adapter_api_version": "final_chain_adapter.v0.2",
        "supported_job_statuses": list(FINAL_CHAIN_JOB_STATUSES),
        "input_contract": {
            "input_path_arg": "--input",
            "output_root_arg": "--output-root",
            "job_id_arg": "--job-id",
            "requires_existing_input_file": True,
            "workspace_contract": "relative_git_paths_only",
            "absolute_paths_as_reproducible_inputs": False,
        },
        "command_contract": _command_contract(chain, standard_cli_contract),
        "result_contract": _result_contract(),
        "plan": build_portable_plan_snapshot(plan, workspace_root=workspace_root),
        "request_snapshot": build_request_snapshot(request, workspace_root=workspace_root),
        "execution_contract": _no_side_effect_contract(),
        "adapter_invoked_entrypoint": False,
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def _standard_cli_contract(chain: FinalChainDefinition) -> dict[str, Any]:
    raw_contract = chain.raw.get("standard_cli_contract")
    return raw_contract if isinstance(raw_contract, dict) else {}


def _preflight_blocked_reasons(plan: dict[str, Any], standard_cli_contract: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if plan.get("status") != "ready":
        for reason in plan.get("blocked_reasons") or []:
            reasons.append(f"plan:{reason}")
    accepted_args = standard_cli_contract.get("accepted_args")
    if not isinstance(accepted_args, list):
        reasons.append("standard_cli_contract_missing")
    else:
        missing_args = [arg for arg in STANDARD_EXECUTION_ARGS if arg not in accepted_args]
        reasons.extend(f"standard_cli_arg_missing:{arg}" for arg in missing_args)
    if standard_cli_contract.get("emits_job_result") is not True:
        reasons.append("job_result_emission_contract_missing")
    if standard_cli_contract.get("resume_from_checkpoint") is not True:
        reasons.append("checkpoint_resume_contract_missing")
    return sorted(dict.fromkeys(reasons))


def _command_contract(chain: FinalChainDefinition, standard_cli_contract: dict[str, Any]) -> dict[str, Any]:
    accepted_args = standard_cli_contract.get("accepted_args")
    return {
        "mode": "subprocess_cli",
        "canonical_entrypoint": chain.canonical_entrypoint,
        "standard_args_required": list(STANDARD_EXECUTION_ARGS),
        "standard_args_supported": isinstance(accepted_args, list)
        and all(arg in accepted_args for arg in STANDARD_EXECUTION_ARGS),
        "accepted_args": accepted_args if isinstance(accepted_args, list) else [],
        "emits_job_result": standard_cli_contract.get("emits_job_result") is True,
        "resume_from_checkpoint": standard_cli_contract.get("resume_from_checkpoint") is True,
        "execute_now": False,
    }


def _result_contract() -> dict[str, Any]:
    return {
        "schema_version": "final_chain_job_result.v0.1",
        "required_fields": [
            "schema_version",
            "chain_id",
            "job_id",
            "status",
            "attempt",
            "started_at",
            "finished_at",
            "input",
            "artifacts",
            "error",
            "checkpoints",
        ],
        "status_enum": list(FINAL_CHAIN_JOB_STATUSES),
        "artifact_path_policy": {
            "relative_git_paths_only": True,
            "writes_under_outputs": True,
            "atomic_json_required": True,
        },
        "error_contract": {
            "required_fields": ["code", "message", "retryable", "node_id", "evidence"],
            "retryable_maps_to_status": "failed_retryable",
            "non_retryable_maps_to_status": "failed_final",
        },
    }


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
