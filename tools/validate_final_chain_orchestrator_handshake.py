from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import read_json, write_json, write_text

HANDSHAKE_PATH = ROOT / "docs" / "reports" / "final_chain_orchestrator_handshake_20260804.json"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_orchestrator_handshake_validation_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_orchestrator_handshake_validation_20260804.md"

EXPECTED_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
EXPECTED_SEQUENCE = [
    "env-contract",
    "contract",
    "plan",
    "schedule",
    "queue",
    "job-validate",
    "adapter-dry-run",
    "adapter-execution-preflight",
]
ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/Users/|\\\\)")


def load_handshake() -> dict[str, Any]:
    try:
        payload = read_json(HANDSHAKE_PATH)
    except FileNotFoundError:
        return {"missing": True}
    return payload if isinstance(payload, dict) else {"not_object": True}


def build_validation_report() -> dict[str, Any]:
    handshake = load_handshake()
    checks = _build_checks(handshake)
    return {
        "schema_version": "final_chain_orchestrator_handshake_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "handshake_path": "docs/reports/final_chain_orchestrator_handshake_20260804.json",
        "checks": checks,
        "execution_contract": _no_side_effect_contract(),
    }


def _build_checks(handshake: dict[str, Any]) -> list[dict[str, Any]]:
    source_reports = handshake.get("source_reports") if isinstance(handshake.get("source_reports"), dict) else {}
    command_map = handshake.get("commands") if isinstance(handshake.get("commands"), dict) else {}
    checks = _report_check_statuses(handshake.get("checks"))
    return [
        {
            "name": "handshake_file_is_present_object",
            "ok": not handshake.get("missing") and not handshake.get("not_object"),
            "value": "present" if not handshake.get("missing") else "missing",
        },
        {
            "name": "handshake_schema_contract_matches",
            "ok": handshake.get("schema_version") == "final_chain_orchestrator_handshake.v0.1"
            and handshake.get("workspace_contract") == "relative_git_paths_only"
            and handshake.get("absolute_paths_as_inputs") is False,
            "value": {
                "schema_version": handshake.get("schema_version"),
                "workspace_contract": handshake.get("workspace_contract"),
                "absolute_paths_as_inputs": handshake.get("absolute_paths_as_inputs"),
            },
        },
        {
            "name": "handshake_status_passes",
            "ok": handshake.get("status") == "pass",
            "value": handshake.get("status"),
        },
        {
            "name": "external_orchestrator_role_is_explicit",
            "ok": handshake.get("consumer_role") == "external_orchestrator_or_java_backbone",
            "value": handshake.get("consumer_role"),
        },
        {
            "name": "chain_split_matches_final_chain_contract",
            "ok": handshake.get("chain_ids") == EXPECTED_CHAIN_IDS
            and handshake.get("ready_chain_ids") == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
            and handshake.get("blocked_chain_ids") == [],
            "value": {
                "chains": handshake.get("chain_ids"),
                "ready": handshake.get("ready_chain_ids"),
                "blocked": handshake.get("blocked_chain_ids"),
            },
        },
        {
            "name": "required_command_sequence_is_stable",
            "ok": handshake.get("required_command_sequence") == EXPECTED_SEQUENCE,
            "value": handshake.get("required_command_sequence"),
        },
        {
            "name": "command_map_uses_legacy_cli_only",
            "ok": _command_map_ok(command_map),
            "value": command_map,
        },
        {
            "name": "admission_policy_keeps_pdf_english_non_executing",
            "ok": _admission_policy_ok(handshake.get("admission_policy")),
            "value": handshake.get("admission_policy"),
        },
        {
            "name": "filesystem_contract_limits_writes_to_outputs",
            "ok": _filesystem_contract_ok(handshake.get("filesystem_contract")),
            "value": handshake.get("filesystem_contract"),
        },
        {
            "name": "job_lifecycle_policy_blocks_scheduled_blocked_start",
            "ok": _lifecycle_ok(handshake.get("job_lifecycle_policy")),
            "value": handshake.get("job_lifecycle_policy"),
        },
        {
            "name": "source_reports_are_relative_and_present",
            "ok": _source_reports_present(source_reports),
            "value": source_reports,
        },
        {
            "name": "handshake_internal_checks_pass",
            "ok": checks and all(value is True for value in checks.values()),
            "value": checks,
        },
        {
            "name": "execution_contract_has_no_runtime_side_effects",
            "ok": handshake.get("execution_contract") == _no_side_effect_contract(),
            "value": handshake.get("execution_contract"),
        },
        {
            "name": "handshake_contains_no_absolute_paths",
            "ok": not _contains_absolute_path(handshake),
            "value": "relative_only" if not _contains_absolute_path(handshake) else "absolute_path_found",
        },
    ]


def _command_map_ok(command_map: dict[str, Any]) -> bool:
    required = {
        "contract",
        "env_contract",
        "plan",
        "schedule",
        "queue",
        "adapter_dry_run",
        "adapter_execution_preflight",
        "job_inspect",
        "job_validate",
        "job_recovery_plan",
        "job_schedule_replacement",
        "job_transition",
    }
    return required.issubset(command_map.keys()) and all(
        isinstance(command_map[name], str) and command_map[name].startswith("tools/final_chain_control.py ")
        for name in required
    )


def _admission_policy_ok(policy: Any) -> bool:
    if not isinstance(policy, dict):
        return False
    pdf_english = policy.get("pdf_english")
    if not isinstance(pdf_english, dict):
        return False
    return (
        pdf_english.get("expected_status") == "scheduled_ready"
        and pdf_english.get("environment_gate") == "ready_for_control_plane"
        and pdf_english.get("java_shell_admission") == "allowed_after_raw_pdf_promotion"
        and pdf_english.get("model_execution_default_enabled") is False
        and pdf_english.get("runtime_import_default_enabled") is False
        and pdf_english.get("database_write_default_enabled") is False
    )


def _filesystem_contract_ok(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("write_scope") == ["outputs/"]
        and value.get("read_scope") == "registered_relative_paths_only"
        and value.get("absolute_paths_as_reproducible_inputs") is False
    )


def _lifecycle_ok(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    transitions = value.get("allowed_transitions")
    if not isinstance(transitions, dict):
        return False
    guard = value.get("transition_guard")
    if not isinstance(guard, dict):
        return False
    recovery = value.get("recovery_plan")
    if not isinstance(recovery, dict):
        return False
    return (
        transitions.get("scheduled_ready") == ["dry_run_started", "cancelled"]
        and transitions.get("scheduled_blocked") == []
        and guard.get("same_directory_lock") is True
        and guard.get("expected_status_supported") is True
        and guard.get("expected_state_version_supported") is True
        and guard.get("stale_transition_error") == "final_chain_job_stale_transition"
        and recovery.get("schema_version") == "final_chain_job_recovery_plan.v0.1"
        and recovery.get("non_executing") is True
        and recovery.get("replacement_job_required_for_retry") is True
        and recovery.get("replacement_inherits_request_snapshot") is True
        and recovery.get("replacement_records_parent_job") is True
        and recovery.get("retry_budget_default_max_attempts") == 3
        and recovery.get("retryable_failure_checkpoint_key") == "retryable"
    )


def _source_reports_present(source_reports: dict[str, Any]) -> bool:
    required = {"control_contract", "environment_contract", "batch_queue_validation"}
    if not required.issubset(source_reports.keys()):
        return False
    for key in required:
        path_value = source_reports[key]
        if not isinstance(path_value, str) or Path(path_value).is_absolute() or _contains_absolute_path(path_value):
            return False
        if not (ROOT / path_value).is_file():
            return False
    return True


def _report_check_statuses(checks: Any) -> dict[str, bool | None]:
    statuses: dict[str, bool | None] = {}
    if not isinstance(checks, list):
        return statuses
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("name"), str):
            statuses[check["name"]] = check.get("ok") if isinstance(check.get("ok"), bool) else None
    return statuses


def _contains_absolute_path(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False)
    return ABSOLUTE_PATH_PATTERN.search(serialized) is not None


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Orchestrator Handshake Validation 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Handshake: `{report['handshake_path']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_validation_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
