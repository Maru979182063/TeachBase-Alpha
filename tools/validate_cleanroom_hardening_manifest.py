from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

MANIFEST_PATH = ROOT / "docs" / "reports" / "cleanroom_hardening_manifest_20260804.json"
REPORT_JSON = ROOT / "docs" / "reports" / "cleanroom_hardening_manifest_validation_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "cleanroom_hardening_manifest_validation_20260804.md"

REQUIRED_SCOPES = {
    "foundation_artifact_atomicity_and_model_checkpoint_guard",
    "final_chain_registry_control_contract_environment_contract_and_scheduler",
    "precleanup_archive_safety_and_worktree_compartment_guard",
}

REQUIRED_REPLAY_COMMANDS = {
    "npm run test:foundation-hardening",
    "npm run test:precleanup-safety",
    "npm run test:final-chain-ops",
    "npm run test:cleanroom-hardening-status",
}

REQUIRED_REPORTS = {
    "foundation_hardening",
    "precleanup_safety",
    "final_chain_ops",
    "final_chain_control_contract",
    "final_chain_environment_contract",
    "final_chain_ready_samples",
    "final_chain_batch_queue",
    "final_chain_batch_queue_validation",
    "final_chain_orchestrator_handshake",
    "final_chain_orchestrator_handshake_validation",
    "final_chain_ops_health",
    "pdf_english_recovery_validation",
    "pdf_english_recovery_source_audit",
    "pdf_english_recovery_intake_validation",
    "pdf_english_rebuild_decision",
}

REQUIRED_MANIFEST_CHECKS = {
    "required_reports_present",
    "all_status_reports_pass_or_expected_blocked",
    "final_chain_ops_covers_four_chains",
    "final_chain_job_records_self_and_external_validated",
    "pdf_english_is_explicit_fail_closed_blocker",
    "pdf_english_recovery_intake_gate_is_sealed",
    "pdf_english_rebuild_track_is_explicit",
    "final_chain_ops_health_is_sealed",
    "no_report_declares_runtime_side_effects",
}

EXPECTED_BLOCKER = {
    "chain_id": "pdf_english",
    "status": "blocked_missing_manifest_and_smoke_artifacts",
    "guard": "pdf_english_recovery_requires_four_branch_manifest",
    "allowed_behavior": "fail_closed",
    "legacy_artifact_wait_required": False,
    "safe_rebuild_boundary": "pdf_english_rebuild_decision_requires_fresh_manifest_and_smoke_before_ready_claim",
}

ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/Users/|\\\\)")


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"missing": True}
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {"not_object": True}


def build_validation_report() -> dict[str, Any]:
    manifest = load_manifest()
    checks = _build_checks(manifest)
    return {
        "schema_version": "cleanroom_hardening_manifest_validation.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "manifest_path": "docs/reports/cleanroom_hardening_manifest_20260804.json",
        "checks": checks,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _build_checks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    report_records = manifest.get("reports")
    checks = [
        {
            "name": "manifest_file_is_present_object",
            "ok": not manifest.get("missing") and not manifest.get("not_object"),
            "value": "present" if not manifest.get("missing") else "missing",
        },
        {
            "name": "manifest_schema_contract_matches",
            "ok": manifest.get("schema_version") == "cleanroom_hardening_manifest.v0.1"
            and manifest.get("workspace_contract") == "relative_git_paths_only"
            and manifest.get("absolute_paths_as_inputs") is False,
            "value": {
                "schema_version": manifest.get("schema_version"),
                "workspace_contract": manifest.get("workspace_contract"),
                "absolute_paths_as_inputs": manifest.get("absolute_paths_as_inputs"),
            },
        },
        {
            "name": "manifest_status_passes",
            "ok": manifest.get("status") == "pass",
            "value": manifest.get("status"),
        },
        {
            "name": "sealed_scopes_complete",
            "ok": REQUIRED_SCOPES.issubset(set(_string_list(manifest.get("sealed_scopes")))),
            "value": _string_list(manifest.get("sealed_scopes")),
        },
        {
            "name": "replay_commands_complete",
            "ok": REQUIRED_REPLAY_COMMANDS.issubset(set(_string_list(manifest.get("replay_commands")))),
            "value": _string_list(manifest.get("replay_commands")),
        },
        {
            "name": "required_report_records_present",
            "ok": _report_records_present(report_records),
            "value": sorted(report_records.keys()) if isinstance(report_records, dict) else [],
        },
        {
            "name": "report_paths_are_relative_and_existing",
            "ok": _report_paths_are_relative_and_existing(report_records),
            "value": _report_paths(report_records),
        },
        {
            "name": "required_manifest_checks_pass",
            "ok": _required_manifest_checks_pass(manifest.get("checks")),
            "value": _manifest_check_statuses(manifest.get("checks")),
        },
        {
            "name": "known_pdf_english_blocker_is_fail_closed",
            "ok": EXPECTED_BLOCKER in _dict_list(manifest.get("known_blockers")),
            "value": manifest.get("known_blockers"),
        },
        {
            "name": "execution_contract_has_no_runtime_side_effects",
            "ok": _execution_contract_empty(manifest.get("execution_contract")),
            "value": manifest.get("execution_contract"),
        },
        {
            "name": "manifest_contains_no_absolute_paths",
            "ok": not _contains_absolute_path(manifest),
            "value": "relative_only" if not _contains_absolute_path(manifest) else "absolute_path_found",
        },
    ]
    return checks


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _report_records_present(report_records: Any) -> bool:
    if not isinstance(report_records, dict):
        return False
    if not REQUIRED_REPORTS.issubset(report_records.keys()):
        return False
    return all(isinstance(report_records[name], dict) and report_records[name].get("exists") is True for name in REQUIRED_REPORTS)


def _report_paths(report_records: Any) -> dict[str, str | None]:
    if not isinstance(report_records, dict):
        return {}
    return {
        name: record.get("path") if isinstance(record, dict) and isinstance(record.get("path"), str) else None
        for name, record in report_records.items()
    }


def _report_paths_are_relative_and_existing(report_records: Any) -> bool:
    paths = _report_paths(report_records)
    if not REQUIRED_REPORTS.issubset(paths.keys()):
        return False
    for name in REQUIRED_REPORTS:
        relative_path = paths[name]
        if not relative_path:
            return False
        path = Path(relative_path)
        if path.is_absolute() or _contains_absolute_path(relative_path):
            return False
        if not (ROOT / path).is_file():
            return False
    return True


def _required_manifest_checks_pass(checks: Any) -> bool:
    statuses = _manifest_check_statuses(checks)
    return REQUIRED_MANIFEST_CHECKS.issubset(statuses.keys()) and all(statuses[name] is True for name in REQUIRED_MANIFEST_CHECKS)


def _manifest_check_statuses(checks: Any) -> dict[str, bool | None]:
    statuses: dict[str, bool | None] = {}
    if not isinstance(checks, list):
        return statuses
    for check in checks:
        if isinstance(check, dict) and isinstance(check.get("name"), str):
            statuses[check["name"]] = check.get("ok") if isinstance(check.get("ok"), bool) else None
    return statuses


def _execution_contract_empty(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        value.get(flag) is False
        for flag in ("model_invoked", "database_written", "runtime_imported", "business_secrets_read")
    )


def _contains_absolute_path(value: Any) -> bool:
    serialized = json.dumps(value, ensure_ascii=False)
    return ABSOLUTE_PATH_PATTERN.search(serialized) is not None


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cleanroom Hardening Manifest Validation 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Manifest: `{report['manifest_path']}`",
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
