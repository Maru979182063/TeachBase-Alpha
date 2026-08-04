from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

BATCH_REPORT_PATH = ROOT / "docs" / "reports" / "final_chain_batch_queue_20260804.json"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_batch_queue_validation_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_batch_queue_validation_20260804.md"

EXPECTED_CHAIN_IDS = ["doc_math", "doc_english", "pdf_math", "pdf_english"]
EXPECTED_RECORD_PATH = "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json"
EXPECTED_READY = {"doc_math", "doc_english", "pdf_math"}
EXPECTED_BLOCKED = {"pdf_english"}
ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/Users/|\\\\)")


def load_batch_report() -> dict[str, Any]:
    if not BATCH_REPORT_PATH.is_file():
        return {"missing": True}
    payload = json.loads(BATCH_REPORT_PATH.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {"not_object": True}


def build_validation_report() -> dict[str, Any]:
    batch_report = load_batch_report()
    checks = _build_checks(batch_report)
    return {
        "schema_version": "final_chain_batch_queue_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "batch_report_path": "docs/reports/final_chain_batch_queue_20260804.json",
        "checks": checks,
        "execution_contract": _no_side_effect_contract(),
    }


def _build_checks(batch_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _rows(batch_report)
    by_id = {str(row.get("chain_id") or ""): row for row in rows}
    statuses = {chain_id: str(row.get("schedule_status") or "") for chain_id, row in by_id.items()}
    report_checks = _report_check_statuses(batch_report.get("checks"))
    return [
        {
            "name": "batch_report_file_is_present_object",
            "ok": not batch_report.get("missing") and not batch_report.get("not_object"),
            "value": "present" if not batch_report.get("missing") else "missing",
        },
        {
            "name": "batch_report_schema_contract_matches",
            "ok": batch_report.get("schema_version") == "final_chain_batch_queue_report.v0.1"
            and batch_report.get("workspace_contract") == "relative_git_paths_only"
            and batch_report.get("absolute_paths_as_inputs") is False,
            "value": {
                "schema_version": batch_report.get("schema_version"),
                "workspace_contract": batch_report.get("workspace_contract"),
                "absolute_paths_as_inputs": batch_report.get("absolute_paths_as_inputs"),
            },
        },
        {
            "name": "batch_report_status_passes",
            "ok": batch_report.get("status") == "pass",
            "value": batch_report.get("status"),
        },
        {
            "name": "batch_report_covers_exact_four_final_chains",
            "ok": [row.get("chain_id") for row in rows] == EXPECTED_CHAIN_IDS and batch_report.get("chain_count") == 4,
            "value": [row.get("chain_id") for row in rows],
        },
        {
            "name": "batch_queue_status_split_is_expected",
            "ok": _status_split_ok(batch_report, statuses),
            "value": {
                "scheduled_ready_count": batch_report.get("scheduled_ready_count"),
                "scheduled_blocked_count": batch_report.get("scheduled_blocked_count"),
                "rejected_count": batch_report.get("rejected_count"),
                "statuses": statuses,
            },
        },
        {
            "name": "pdf_english_fails_closed_with_blockers",
            "ok": _pdf_english_blocker_ok(by_id.get("pdf_english")),
            "value": by_id.get("pdf_english", {}).get("blocked_reasons"),
        },
        {
            "name": "job_record_contract_paths_are_stable_and_under_outputs",
            "ok": all(row.get("record_path") == EXPECTED_RECORD_PATH for row in rows)
            and all(row.get("record_path_contract") == EXPECTED_RECORD_PATH for row in rows),
            "value": [row.get("record_path") for row in rows],
        },
        {
            "name": "job_record_validations_are_clean",
            "ok": all(
                row.get("record_validation_ok") is True
                and row.get("record_validation_error_count") == 0
                and row.get("self_validation_ok") is True
                and row.get("self_validation_error_count") == 0
                for row in rows
            ),
            "value": {
                "external": [row.get("record_validation_error_count") for row in rows],
                "self": [row.get("self_validation_error_count") for row in rows],
            },
        },
        {
            "name": "batch_report_checks_pass",
            "ok": _required_report_checks_pass(report_checks),
            "value": report_checks,
        },
        {
            "name": "execution_contract_has_no_runtime_side_effects",
            "ok": batch_report.get("execution_contract") == _no_side_effect_contract()
            and all(row.get("execution_contract") == _no_side_effect_contract() for row in rows),
            "value": batch_report.get("execution_contract"),
        },
        {
            "name": "batch_report_contains_no_absolute_paths",
            "ok": not _contains_absolute_path(batch_report),
            "value": "relative_only" if not _contains_absolute_path(batch_report) else "absolute_path_found",
        },
    ]


def _rows(batch_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = batch_report.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _status_split_ok(batch_report: dict[str, Any], statuses: dict[str, str]) -> bool:
    ready = {chain_id for chain_id, status in statuses.items() if status == "scheduled_ready"}
    blocked = {chain_id for chain_id, status in statuses.items() if status == "scheduled_blocked"}
    rejected = {chain_id for chain_id, status in statuses.items() if status == "rejected"}
    return (
        ready == EXPECTED_READY
        and blocked == EXPECTED_BLOCKED
        and not rejected
        and batch_report.get("scheduled_ready_count") == 3
        and batch_report.get("scheduled_blocked_count") == 1
        and batch_report.get("rejected_count") == 0
    )


def _pdf_english_blocker_ok(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    blocked_reasons = row.get("blocked_reasons")
    return (
        row.get("schedule_status") == "scheduled_blocked"
        and row.get("plan_status") == "blocked"
        and isinstance(blocked_reasons, list)
        and "canonical_entrypoint_present" in blocked_reasons
    )


def _report_check_statuses(checks: Any) -> dict[str, bool | None]:
    statuses: dict[str, bool | None] = {}
    if not isinstance(checks, list):
        return statuses
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("name"), str):
            statuses[check["name"]] = check.get("ok") if isinstance(check.get("ok"), bool) else None
    return statuses


def _required_report_checks_pass(checks: dict[str, bool | None]) -> bool:
    required = {
        "batch_covers_four_registered_chains",
        "three_ready_jobs_scheduled",
        "pdf_english_is_scheduled_blocked",
        "no_rejected_jobs",
        "all_job_records_validate",
        "all_job_records_written_under_outputs",
        "no_runtime_side_effects_reported",
    }
    return required.issubset(checks.keys()) and all(checks[name] is True for name in required)


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
        "# Final Chain Batch Queue Validation 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Batch report: `{report['batch_report_path']}`",
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
