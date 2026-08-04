from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

REPORT_JSON = ROOT / "docs" / "reports" / "cleanroom_hardening_manifest_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "cleanroom_hardening_manifest_20260804.md"

REQUIRED_REPORTS = {
    "foundation_hardening": "docs/reports/foundation_hardening_test_report_20260803.json",
    "precleanup_safety": "docs/reports/precleanup_safety_gate_20260804.json",
    "final_chain_ops": "docs/reports/final_chain_ops_gate_20260804.json",
    "final_chain_control_contract": "docs/reports/final_chain_control_contract_20260804.json",
    "final_chain_environment_contract": "docs/reports/final_chain_environment_contract_20260804.json",
    "final_chain_ready_samples": "docs/reports/final_chain_ready_sample_dry_run_20260804.json",
    "final_chain_batch_queue": "docs/reports/final_chain_batch_queue_20260804.json",
    "final_chain_batch_queue_validation": "docs/reports/final_chain_batch_queue_validation_20260804.json",
    "final_chain_orchestrator_handshake": "docs/reports/final_chain_orchestrator_handshake_20260804.json",
    "final_chain_orchestrator_handshake_validation": "docs/reports/final_chain_orchestrator_handshake_validation_20260804.json",
    "final_chain_ops_health": "docs/reports/final_chain_ops_health_20260804.json",
    "pdf_english_recovery_validation": "docs/reports/pdf_english_recovery_validation_20260804.json",
    "pdf_english_recovery_source_audit": "docs/reports/pdf_english_manifest_recovery_audit_20260804.json",
    "pdf_english_recovery_intake_validation": "docs/reports/pdf_english_recovery_intake_validation_20260804.json",
}


def build_report() -> dict[str, Any]:
    reports = {name: _report_record(name, path) for name, path in REQUIRED_REPORTS.items()}
    checks = [
        {
            "name": "required_reports_present",
            "ok": all(item["exists"] for item in reports.values()),
            "value": {name: item["exists"] for name, item in reports.items()},
        },
        {
            "name": "all_status_reports_pass_or_expected_blocked",
            "ok": _status_reports_ok(reports),
            "value": {name: item["status"] for name, item in reports.items()},
        },
        {
            "name": "final_chain_ops_covers_four_chains",
            "ok": _json_value(reports, "final_chain_ops", ["environment_ready_chain_ids"]) == [
                "doc_math",
                "doc_english",
                "pdf_math",
            ]
            and _json_value(reports, "final_chain_ops", ["environment_blocked_chain_ids"]) == ["pdf_english"],
            "value": {
                "ready": _json_value(reports, "final_chain_ops", ["environment_ready_chain_ids"]),
                "blocked": _json_value(reports, "final_chain_ops", ["environment_blocked_chain_ids"]),
            },
        },
        {
            "name": "final_chain_job_records_self_and_external_validated",
            "ok": _ready_sample_validation_ok(reports),
            "value": _json_value(reports, "final_chain_ops", ["checks"]),
        },
        {
            "name": "pdf_english_is_explicit_fail_closed_blocker",
            "ok": _json_value(reports, "pdf_english_recovery_validation", ["status"])
            == "blocked_missing_or_invalid_manifest"
            and _json_value(reports, "pdf_english_recovery_source_audit", ["source_audit_status"])
            == "no_importable_source_found"
            and _json_value(reports, "pdf_english_recovery_intake_validation", ["status"])
            == "blocked_missing_or_invalid_recovery_candidate",
            "value": {
                "validation": _json_value(reports, "pdf_english_recovery_validation", ["status"]),
                "source_audit": _json_value(reports, "pdf_english_recovery_source_audit", ["source_audit_status"]),
                "intake": _json_value(reports, "pdf_english_recovery_intake_validation", ["status"]),
            },
        },
        {
            "name": "pdf_english_recovery_intake_gate_is_sealed",
            "ok": _json_value(reports, "pdf_english_recovery_intake_validation", ["schema_version"])
            == "pdf_english_recovery_intake_validation.v0.1"
            and _json_value(reports, "pdf_english_recovery_intake_validation", ["candidate_root_contract", "path_recording"])
            == "label_or_workspace_relative_only",
            "value": {
                "schema_version": _json_value(reports, "pdf_english_recovery_intake_validation", ["schema_version"]),
                "path_recording": _json_value(
                    reports,
                    "pdf_english_recovery_intake_validation",
                    ["candidate_root_contract", "path_recording"],
                ),
            },
        },
        {
            "name": "final_chain_ops_health_is_sealed",
            "ok": _json_value(reports, "final_chain_ops_health", ["status"]) == "pass"
            and _json_value(reports, "final_chain_ops_health", ["missing_npm_scripts"]) == [],
            "value": {
                "status": _json_value(reports, "final_chain_ops_health", ["status"]),
                "missing_npm_scripts": _json_value(reports, "final_chain_ops_health", ["missing_npm_scripts"]),
            },
        },
        {
            "name": "no_report_declares_runtime_side_effects",
            "ok": all(_execution_contract_ok(item.get("payload")) for item in reports.values()),
            "value": {name: _execution_contract(item.get("payload")) for name, item in reports.items()},
        },
    ]
    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": "cleanroom_hardening_manifest.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass" if not failed else "fail",
        "terror_index_estimate": "3.0_to_3.2",
        "sealed_scopes": [
            "foundation_artifact_atomicity_and_model_checkpoint_guard",
            "final_chain_registry_control_contract_environment_contract_and_scheduler",
            "precleanup_archive_safety_and_worktree_compartment_guard",
        ],
        "replay_commands": [
            "npm run test:foundation-hardening",
            "npm run test:precleanup-safety",
            "npm run test:final-chain-ops",
            "npm run test:cleanroom-hardening-status",
        ],
        "known_blockers": [
            {
                "chain_id": "pdf_english",
                "status": "blocked_missing_manifest_and_smoke_artifacts",
                "guard": "pdf_english_recovery_requires_four_branch_manifest",
                "allowed_behavior": "fail_closed",
            }
        ],
        "checks": checks,
        "reports": {name: _public_report_record(item) for name, item in reports.items()},
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _report_record(name: str, relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    payload: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        payload = loaded if isinstance(loaded, dict) else {"not_object": True}
    return {
        "name": name,
        "path": relative_path,
        "exists": path.is_file(),
        "status": _report_status(payload) if payload else "missing",
        "payload": payload,
    }


def _public_report_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": record["path"],
        "exists": record["exists"],
        "status": record["status"],
    }


def _report_status(payload: dict[str, Any]) -> str:
    if "status" in payload:
        return str(payload["status"])
    if "ok" in payload:
        return "pass" if payload["ok"] is True else "fail"
    if "all_exit_codes_zero" in payload:
        return "pass" if payload["all_exit_codes_zero"] is True else "fail"
    if payload.get("schema_version") == "final_chain_control_contract.v0.1":
        return "pass"
    if payload.get("schema_version") == "final_chain_ready_sample_dry_run_report.v0.1":
        return "pass" if payload.get("ready_for_adapter_dry_run_count") == 3 else "fail"
    if payload.get("schema_version") == "pdf_english_manifest_recovery_audit.v0.1":
        return str(payload.get("source_audit_status") or "unknown")
    return "unknown"


def _status_reports_ok(reports: dict[str, dict[str, Any]]) -> bool:
    expected_blocked = {
        "pdf_english_recovery_validation": "blocked_missing_or_invalid_manifest",
        "pdf_english_recovery_source_audit": "no_importable_source_found",
        "pdf_english_recovery_intake_validation": "blocked_missing_or_invalid_recovery_candidate",
    }
    for name, record in reports.items():
        status = record["status"]
        if name in expected_blocked:
            if status != expected_blocked[name]:
                return False
        elif status not in {"pass", "ok"}:
            return False
    return True


def _json_value(reports: dict[str, dict[str, Any]], name: str, path: list[str]) -> Any:
    value: Any = reports.get(name, {}).get("payload", {})
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _ready_sample_validation_ok(reports: dict[str, dict[str, Any]]) -> bool:
    checks = _json_value(reports, "final_chain_ops", ["checks"])
    if not isinstance(checks, list):
        return False
    for check in checks:
        if isinstance(check, dict) and check.get("name") == "ready_sample_job_records_validate":
            return check.get("ok") is True
    return False


def _execution_contract(payload: dict[str, Any] | None) -> dict[str, bool]:
    payload = payload if isinstance(payload, dict) else {}
    contract = payload.get("execution_contract")
    source = contract if isinstance(contract, dict) else payload
    return {
        "model_invoked": source.get("model_invoked") is True,
        "database_written": source.get("database_written") is True,
        "runtime_imported": source.get("runtime_imported") is True,
        "business_secrets_read": source.get("business_secrets_read") is True,
    }


def _execution_contract_ok(payload: dict[str, Any] | None) -> bool:
    return not any(_execution_contract(payload).values())


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cleanroom Hardening Manifest 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Terror index estimate: `{report['terror_index_estimate']}`",
        "",
        "## Sealed Scopes",
        "",
    ]
    for scope in report["sealed_scopes"]:
        lines.append(f"- `{scope}`")
    lines.extend(["", "## Checks", ""])
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Known Blockers", ""])
    for blocker in report["known_blockers"]:
        lines.append(f"- `{blocker['chain_id']}` `{blocker['status']}` `{blocker['allowed_behavior']}`")
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
