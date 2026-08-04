from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.final_chains import (
    build_environment_interaction_contract,
    build_final_chain_control_contract,
    load_final_chain_registry,
)
from teachbase.infrastructure.artifact_store import read_json, write_json, write_text

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_orchestrator_handshake_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_orchestrator_handshake_20260804.md"
BATCH_QUEUE_VALIDATION = ROOT / "docs" / "reports" / "final_chain_batch_queue_validation_20260804.json"

EXPECTED_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
REQUIRED_COMMANDS = {
    "contract",
    "env_contract",
    "plan",
    "schedule",
    "queue",
    "adapter_dry_run",
    "job_inspect",
    "job_validate",
    "job_transition",
}
REQUIRED_HANDSHAKE_STEPS = ["env-contract", "contract", "plan", "schedule", "queue", "job-validate", "adapter-dry-run"]
NO_SIDE_EFFECT_CONTRACT = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    control_contract = build_final_chain_control_contract(registry)
    environment_contract = build_environment_interaction_contract(registry, workspace_root=ROOT)
    batch_queue_validation = _read_json(BATCH_QUEUE_VALIDATION)
    checks = _build_checks(control_contract, environment_contract, batch_queue_validation)
    return {
        "schema_version": "final_chain_orchestrator_handshake.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "consumer_role": "external_orchestrator_or_java_backbone",
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "chain_ids": EXPECTED_CHAIN_IDS,
        "ready_chain_ids": environment_contract.get("ready_chain_ids", []),
        "blocked_chain_ids": environment_contract.get("blocked_chain_ids", []),
        "required_command_sequence": REQUIRED_HANDSHAKE_STEPS,
        "commands": {name: control_contract["commands"][name] for name in sorted(REQUIRED_COMMANDS)},
        "filesystem_contract": environment_contract.get("filesystem_contract", {}),
        "job_lifecycle_policy": control_contract.get("job_lifecycle_policy", {}),
        "required_job_record_sections": control_contract.get("required_job_record_sections", []),
        "blocked_chain_policy": {
            "pdf_english": {
                "expected_status": "scheduled_blocked",
                "environment_gate": "fail_closed",
                "start_forbidden": True,
                "ready_claim_forbidden_until_manifest_recovered": True,
            }
        },
        "source_reports": {
            "control_contract": "docs/reports/final_chain_control_contract_20260804.json",
            "environment_contract": "docs/reports/final_chain_environment_contract_20260804.json",
            "batch_queue_validation": "docs/reports/final_chain_batch_queue_validation_20260804.json",
        },
        "checks": checks,
        "execution_contract": NO_SIDE_EFFECT_CONTRACT,
    }


def _build_checks(
    control_contract: dict[str, Any],
    environment_contract: dict[str, Any],
    batch_queue_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    commands = control_contract.get("commands") if isinstance(control_contract.get("commands"), dict) else {}
    lifecycle = control_contract.get("job_lifecycle_policy") if isinstance(control_contract.get("job_lifecycle_policy"), dict) else {}
    allowed_transitions = lifecycle.get("allowed_transitions") if isinstance(lifecycle.get("allowed_transitions"), dict) else {}
    filesystem_contract = (
        environment_contract.get("filesystem_contract")
        if isinstance(environment_contract.get("filesystem_contract"), dict)
        else {}
    )
    forbidden_side_effects = (
        control_contract.get("forbidden_side_effects")
        if isinstance(control_contract.get("forbidden_side_effects"), dict)
        else {}
    )
    return [
        {
            "name": "control_and_environment_contracts_target_external_orchestrator",
            "ok": control_contract.get("consumer_role") == "external_orchestrator_or_java_backbone"
            and environment_contract.get("consumer_role") == "external_orchestrator_or_java_backbone",
            "value": {
                "control": control_contract.get("consumer_role"),
                "environment": environment_contract.get("consumer_role"),
            },
        },
        {
            "name": "four_final_chains_declared",
            "ok": control_contract.get("chain_ids") == EXPECTED_CHAIN_IDS
            and environment_contract.get("chain_count") == 4,
            "value": {
                "control": control_contract.get("chain_ids"),
                "environment_count": environment_contract.get("chain_count"),
            },
        },
        {
            "name": "environment_ready_blocked_split_is_explicit",
            "ok": environment_contract.get("ready_chain_ids") == ["doc_math", "doc_english", "pdf_math"]
            and environment_contract.get("blocked_chain_ids") == ["pdf_english"],
            "value": {
                "ready": environment_contract.get("ready_chain_ids"),
                "blocked": environment_contract.get("blocked_chain_ids"),
            },
        },
        {
            "name": "required_commands_are_declared",
            "ok": REQUIRED_COMMANDS.issubset(commands.keys()),
            "value": sorted(commands.keys()),
        },
        {
            "name": "required_handshake_sequence_declared",
            "ok": environment_contract.get("external_handshake") == REQUIRED_HANDSHAKE_STEPS,
            "value": environment_contract.get("external_handshake"),
        },
        {
            "name": "control_plane_is_dry_run_only",
            "ok": _control_plane_is_dry_run_only(control_contract),
            "value": control_contract.get("control_plane_contract"),
        },
        {
            "name": "forbidden_side_effects_are_closed",
            "ok": all(forbidden_side_effects.get(name) is True for name in forbidden_side_effects)
            and control_contract.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT
            and environment_contract.get("execution_contract") == NO_SIDE_EFFECT_CONTRACT,
            "value": forbidden_side_effects,
        },
        {
            "name": "filesystem_contract_is_outputs_only",
            "ok": filesystem_contract.get("write_scope") == ["outputs/"]
            and filesystem_contract.get("read_scope") == "registered_relative_paths_only"
            and filesystem_contract.get("absolute_paths_as_reproducible_inputs") is False,
            "value": filesystem_contract,
        },
        {
            "name": "job_lifecycle_blocks_scheduled_blocked_start",
            "ok": allowed_transitions.get("scheduled_blocked") == []
            and allowed_transitions.get("scheduled_ready") == ["dry_run_started", "cancelled"],
            "value": {
                "scheduled_ready": allowed_transitions.get("scheduled_ready"),
                "scheduled_blocked": allowed_transitions.get("scheduled_blocked"),
            },
        },
        {
            "name": "required_job_record_sections_declared",
            "ok": control_contract.get("required_job_record_sections")
            == ["plan", "request_snapshot", "environment_snapshot", "lifecycle", "execution_contract"],
            "value": control_contract.get("required_job_record_sections"),
        },
        {
            "name": "batch_queue_validation_passes",
            "ok": batch_queue_validation.get("status") == "pass"
            and batch_queue_validation.get("schema_version") == "final_chain_batch_queue_validation.v0.1",
            "value": {
                "schema_version": batch_queue_validation.get("schema_version"),
                "status": batch_queue_validation.get("status"),
            },
        },
    ]


def _control_plane_is_dry_run_only(control_contract: dict[str, Any]) -> bool:
    contract = control_contract.get("control_plane_contract")
    if not isinstance(contract, dict):
        return False
    return (
        contract.get("dry_run_only") is True
        and contract.get("execute_intent_blocked") is True
        and contract.get("scheduler_writes_only_under") == "outputs/"
        and contract.get("adapter_dry_run_invokes_entrypoint") is False
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return {"missing": True}
    return payload if isinstance(payload, dict) else {"not_object": True}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Orchestrator Handshake 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Consumer: `{report['consumer_role']}`",
        "",
        "## Command Sequence",
        "",
    ]
    for step in report["required_command_sequence"]:
        lines.append(f"- `{step}`")
    lines.extend(["", "## Checks", ""])
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
