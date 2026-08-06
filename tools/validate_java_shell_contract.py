from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "java_shell_contract_v01.json"
REPORT_JSON = ROOT / "docs" / "reports" / "java_shell_contract_validation_20260806.json"
REPORT_MD = ROOT / "docs" / "reports" / "java_shell_contract_validation_20260806.md"

EXPECTED_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
EXPECTED_STATUSES = [
    "queued",
    "running",
    "waiting_review",
    "failed_retryable",
    "failed_final",
    "completed",
]
EXPECTED_TABLES = {
    "source_files",
    "tasks",
    "node_runs",
    "artifacts",
    "questions",
    "reviews",
    "version_sources",
}
NO_SIDE_EFFECTS = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}
ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/Users/|\\\\)")


def load_contract(path: Path = CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {"not_object": True}


def build_report(path: Path = CONTRACT) -> dict[str, Any]:
    contract = load_contract(path)
    checks = _build_checks(contract)
    return {
        "schema_version": "java_shell_contract_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "contract_path": "config/java_shell_contract_v01.json",
        "checks": checks,
        "execution_contract": NO_SIDE_EFFECTS,
    }


def _build_checks(contract: dict[str, Any]) -> list[dict[str, Any]]:
    state_machine = contract.get("task_state_machine") if isinstance(contract.get("task_state_machine"), dict) else {}
    database = contract.get("database_contract") if isinstance(contract.get("database_contract"), dict) else {}
    worker = contract.get("worker_contract") if isinstance(contract.get("worker_contract"), dict) else {}
    ui = contract.get("ui_contract") if isinstance(contract.get("ui_contract"), dict) else {}
    safety = (
        contract.get("execution_safety_contract")
        if isinstance(contract.get("execution_safety_contract"), dict)
        else {}
    )
    return [
        {
            "name": "schema_and_workspace_contract_match",
            "ok": contract.get("schema_version") == "teachbase_java_shell_contract.v0.1"
            and contract.get("workspace_contract") == "relative_git_paths_only"
            and contract.get("absolute_paths_as_inputs") is False,
            "value": {
                "schema_version": contract.get("schema_version"),
                "workspace_contract": contract.get("workspace_contract"),
                "absolute_paths_as_inputs": contract.get("absolute_paths_as_inputs"),
            },
        },
        {
            "name": "four_protected_chain_ids_declared",
            "ok": contract.get("protected_chain_ids") == EXPECTED_CHAIN_IDS,
            "value": contract.get("protected_chain_ids"),
        },
        {
            "name": "task_state_machine_declares_required_statuses",
            "ok": state_machine.get("statuses") == EXPECTED_STATUSES
            and state_machine.get("initial_status") == "queued"
            and state_machine.get("terminal_statuses") == ["failed_final", "completed"],
            "value": {
                "statuses": state_machine.get("statuses"),
                "initial": state_machine.get("initial_status"),
                "terminal": state_machine.get("terminal_statuses"),
            },
        },
        {
            "name": "task_state_machine_transitions_are_closed",
            "ok": _transitions_ok(state_machine),
            "value": state_machine.get("allowed_transitions"),
        },
        {
            "name": "checkpoint_and_failure_contract_are_structured",
            "ok": _checkpoint_and_failure_ok(state_machine),
            "value": {
                "checkpoint": state_machine.get("checkpoint_policy"),
                "failure": state_machine.get("failure_contract"),
            },
        },
        {
            "name": "database_contract_declares_required_tables",
            "ok": _database_tables_ok(database),
            "value": [table.get("name") for table in database.get("tables", []) if isinstance(table, dict)],
        },
        {
            "name": "worker_contract_has_lock_heartbeat_timeout_retry_and_dedupe",
            "ok": _worker_contract_ok(worker),
            "value": worker,
        },
        {
            "name": "ui_contract_hides_internal_nodes",
            "ok": ui.get("ui_knows_internal_nodes") is False
            and "node_id" in (ui.get("ui_hidden_fields") or [])
            and {"upload_source_file", "create_task", "get_task_status", "get_question_package"}.issubset(
                set(ui.get("allowed_user_operations") or [])
            ),
            "value": ui,
        },
        {
            "name": "contract_validation_has_no_runtime_side_effects",
            "ok": safety.get("model_invoked_by_contract_validation") is False
            and safety.get("database_written_by_contract_validation") is False
            and safety.get("runtime_imported_by_contract_validation") is False
            and safety.get("business_secrets_read_by_contract_validation") is False,
            "value": safety,
        },
        {
            "name": "contract_contains_no_absolute_paths",
            "ok": not _contains_absolute_path(contract),
            "value": "relative_only" if not _contains_absolute_path(contract) else "absolute_path_found",
        },
    ]


def _transitions_ok(state_machine: dict[str, Any]) -> bool:
    transitions = state_machine.get("allowed_transitions")
    if not isinstance(transitions, dict):
        return False
    if set(transitions) != set(EXPECTED_STATUSES):
        return False
    for source, targets in transitions.items():
        if not isinstance(targets, list):
            return False
        if any(target not in EXPECTED_STATUSES for target in targets):
            return False
        if source in {"failed_final", "completed"} and targets:
            return False
    return (
        "running" in transitions.get("queued", [])
        and "failed_retryable" in transitions.get("running", [])
        and "waiting_review" in transitions.get("running", [])
        and "completed" in transitions.get("waiting_review", [])
        and "queued" in transitions.get("failed_retryable", [])
    )


def _checkpoint_and_failure_ok(state_machine: dict[str, Any]) -> bool:
    checkpoint = state_machine.get("checkpoint_policy")
    failure = state_machine.get("failure_contract")
    if not isinstance(checkpoint, dict) or not isinstance(failure, dict):
        return False
    required_failure_fields = {"code", "message", "retryable", "chain_id", "task_id", "node_id", "attempt", "evidence"}
    return (
        checkpoint.get("checkpoint_per_node_required") is True
        and checkpoint.get("resume_from_last_successful_node") is True
        and checkpoint.get("checkpoint_path_policy") == "relative_outputs_path_only"
        and failure.get("structured_failure_required") is True
        and required_failure_fields.issubset(set(failure.get("required_fields") or []))
        and failure.get("retryable_true_maps_to") == "failed_retryable"
        and failure.get("retryable_false_maps_to") == "failed_final"
    )


def _database_tables_ok(database: dict[str, Any]) -> bool:
    tables = database.get("tables")
    if database.get("engine") != "postgres" or not isinstance(tables, list):
        return False
    by_name = {table.get("name"): table for table in tables if isinstance(table, dict)}
    if set(by_name) != EXPECTED_TABLES:
        return False
    required_columns = {
        "tasks": {"id", "chain_id", "source_file_id", "status", "dedupe_key", "locked_by", "heartbeat_at"},
        "node_runs": {"id", "task_id", "node_id", "checkpoint_artifact_id", "error_json"},
        "artifacts": {"id", "task_id", "artifact_kind", "storage_uri", "sha256"},
        "questions": {"id", "task_id", "payload_json", "source_trace_json", "version_id"},
        "reviews": {"id", "task_id", "question_id", "review_status"},
        "version_sources": {"id", "chain_id", "pipeline_version", "config_digest", "source_commit"},
        "source_files": {"id", "sha256", "storage_uri", "created_at"},
    }
    for table_name, columns in required_columns.items():
        declared = set(by_name[table_name].get("required_columns") or [])
        if not columns.issubset(declared):
            return False
    return True


def _worker_contract_ok(worker: dict[str, Any]) -> bool:
    retry = worker.get("retry_policy") if isinstance(worker.get("retry_policy"), dict) else {}
    subprocess_execution = (
        worker.get("subprocess_execution") if isinstance(worker.get("subprocess_execution"), dict) else {}
    )
    return (
        worker.get("worker_lock_required") is True
        and worker.get("heartbeat_required") is True
        and worker.get("timeout_recovery_required") is True
        and worker.get("idempotency_required") is True
        and {"source_file_sha256", "chain_id", "pipeline_version"}.issubset(set(worker.get("dedupe_key_fields") or []))
        and retry.get("max_attempts_default") == 3
        and retry.get("retry_only_when_status") == "failed_retryable"
        and retry.get("retry_resumes_from_checkpoint") is True
        and subprocess_execution.get("python_entrypoints_called_by_worker") is True
        and subprocess_execution.get("standard_cli_contract_required") is True
        and subprocess_execution.get("runtime_import_default_enabled") is False
        and subprocess_execution.get("database_write_by_python_chain_default_enabled") is False
    )


def _contains_absolute_path(value: Any) -> bool:
    return ABSOLUTE_PATH_PATTERN.search(json.dumps(value, ensure_ascii=False)) is not None


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Java Shell Contract Validation 2026-08-06",
        "",
        f"Status: `{report['status']}`",
        f"Contract: `{report['contract_path']}`",
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
    report = build_report()
    from teachbase.infrastructure.artifact_store import write_json, write_text

    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    raise SystemExit(main())
