from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

REPORT_JSON = ROOT / "docs" / "reports" / "cleanroom_goal_gap_audit_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "cleanroom_goal_gap_audit_20260804.md"

SOURCES = {
    "foundation": "docs/reports/foundation_hardening_test_report_20260803.json",
    "precleanup": "docs/reports/precleanup_safety_gate_20260804.json",
    "final_chain_ops": "docs/reports/final_chain_ops_gate_20260804.json",
    "manifest": "docs/reports/cleanroom_hardening_manifest_20260804.json",
    "manifest_validation": "docs/reports/cleanroom_hardening_manifest_validation_20260804.json",
    "status": "docs/reports/cleanroom_hardening_status_20260804.json",
    "control_contract": "docs/reports/final_chain_control_contract_20260804.json",
    "environment_contract": "docs/reports/final_chain_environment_contract_20260804.json",
    "handshake_validation": "docs/reports/final_chain_orchestrator_handshake_validation_20260804.json",
    "pdf_english_recovery_intake_validation": "docs/reports/pdf_english_recovery_intake_validation_20260804.json",
    "final_chain_ops_health": "docs/reports/final_chain_ops_health_20260804.json",
}

NO_SIDE_EFFECTS = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report() -> dict[str, Any]:
    sources = {name: _load_source(path) for name, path in SOURCES.items()}
    checks = _build_checks(sources)
    residual_gaps = _residual_gaps(sources)
    status = "pass_with_known_gap" if all(check["ok"] for check in checks) and residual_gaps else "pass"
    if any(not check["ok"] for check in checks):
        status = "fail"
    return {
        "schema_version": "cleanroom_goal_gap_audit.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": status,
        "objective": (
            "Reduce cleanroom risk toward terror index around 3 by sealing foundation/final-chain/precleanup "
            "work and hardening protected final-chain scheduling, robustness, and external environment interaction."
        ),
        "terror_index_estimate": _value(sources, "status", ["terror_index_estimate"]),
        "completion_claim_allowed": False,
        "completion_blockers": residual_gaps,
        "checks": checks,
        "evidence_sources": {name: {"path": source["path"], "exists": source["exists"]} for name, source in sources.items()},
        "execution_contract": NO_SIDE_EFFECTS,
    }


def _build_checks(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    final_chain_checks = _checks_by_name(_value(sources, "final_chain_ops", ["checks"]))
    control_commands = _value(sources, "control_contract", ["commands"])
    recovery_plan = _value(sources, "control_contract", ["job_lifecycle_policy", "recovery_plan"])
    final_chain_contract_tests_gate = _gate_record(sources, "final_chain_contract_tests")
    final_chain_contract_tests_tail = str(final_chain_contract_tests_gate.get("output_tail") or "")
    return [
        {
            "name": "foundation_gate_sealed",
            "ok": _value(sources, "foundation", ["all_exit_codes_zero"]) is True
            and _source_status(sources, "foundation") == "pass",
            "value": _source_status(sources, "foundation"),
        },
        {
            "name": "precleanup_gate_sealed",
            "ok": _source_status(sources, "precleanup") == "pass",
            "value": _source_status(sources, "precleanup"),
        },
        {
            "name": "final_chain_ops_gate_sealed",
            "ok": _source_status(sources, "final_chain_ops") == "pass",
            "value": _source_status(sources, "final_chain_ops"),
        },
        {
            "name": "four_final_chains_accounted_for",
            "ok": _value(sources, "final_chain_ops", ["environment_ready_chain_ids"])
            == ["doc_math", "doc_english", "pdf_math"]
            and _value(sources, "final_chain_ops", ["environment_blocked_chain_ids"]) == ["pdf_english"],
            "value": {
                "ready": _value(sources, "final_chain_ops", ["environment_ready_chain_ids"]),
                "blocked": _value(sources, "final_chain_ops", ["environment_blocked_chain_ids"]),
            },
        },
        {
            "name": "scheduler_recovery_and_replacement_contract_present",
            "ok": isinstance(control_commands, dict)
            and "job_recovery_plan" in control_commands
            and "job_schedule_replacement" in control_commands
            and isinstance(recovery_plan, dict)
            and recovery_plan.get("replacement_records_parent_job") is True,
            "value": recovery_plan,
        },
        {
            "name": "external_orchestrator_handshake_validated",
            "ok": _source_status(sources, "handshake_validation") == "pass",
            "value": _source_status(sources, "handshake_validation"),
        },
        {
            "name": "environment_interaction_isolated",
            "ok": _source_status(sources, "environment_contract") == "pass"
            and _value(sources, "environment_contract", ["filesystem_contract", "write_scope"]) == ["outputs/"],
            "value": {
                "status": _source_status(sources, "environment_contract"),
                "write_scope": _value(sources, "environment_contract", ["filesystem_contract", "write_scope"]),
            },
        },
        {
            "name": "no_runtime_side_effects_reported",
            "ok": all(_execution_contract(source["payload"]) == NO_SIDE_EFFECTS for source in sources.values()),
            "value": {name: _execution_contract(source["payload"]) for name, source in sources.items()},
        },
        {
            "name": "terror_index_in_target_band",
            "ok": _value(sources, "status", ["terror_index_estimate"]) == "3.0_to_3.2",
            "value": _value(sources, "status", ["terror_index_estimate"]),
        },
        {
            "name": "cleanroom_manifest_validated",
            "ok": _source_status(sources, "manifest") == "pass" and _source_status(sources, "manifest_validation") == "pass",
            "value": {
                "manifest": _source_status(sources, "manifest"),
                "manifest_validation": _source_status(sources, "manifest_validation"),
            },
        },
        {
            "name": "final_chain_contract_tests_pass",
            "ok": final_chain_contract_tests_gate.get("exit_code") == 0 and "passed" in final_chain_contract_tests_tail,
            "value": {
                "exit_code": final_chain_contract_tests_gate.get("exit_code"),
                "output_tail": final_chain_contract_tests_tail,
            },
        },
        {
            "name": "pdf_english_remains_fail_closed_not_silent_ready",
            "ok": final_chain_checks.get("pdf_english_recovery_validator_fails_closed") is True
            and _value(sources, "final_chain_ops", ["pdf_english_recovery_validation_status"])
            == "blocked_missing_or_invalid_manifest",
            "value": _value(sources, "final_chain_ops", ["pdf_english_recovery_validation_status"]),
        },
        {
            "name": "pdf_english_recovery_intake_gate_ready_for_restored_candidate",
            "ok": _source_status(sources, "pdf_english_recovery_intake_validation")
            == "blocked_missing_or_invalid_recovery_candidate"
            and _value(
                sources,
                "pdf_english_recovery_intake_validation",
                ["candidate_root_contract", "path_recording"],
            )
            == "label_or_workspace_relative_only",
            "value": {
                "status": _source_status(sources, "pdf_english_recovery_intake_validation"),
                "required_check_failures": _value(
                    sources,
                    "pdf_english_recovery_intake_validation",
                    ["required_check_failures"],
                ),
            },
        },
        {
            "name": "final_chain_ops_health_seals_cli_and_recovery_surface",
            "ok": _source_status(sources, "final_chain_ops_health") == "pass"
            and _value(sources, "final_chain_ops_health", ["missing_npm_scripts"]) == [],
            "value": {
                "status": _source_status(sources, "final_chain_ops_health"),
                "missing_npm_scripts": _value(sources, "final_chain_ops_health", ["missing_npm_scripts"]),
            },
        },
    ]


def _residual_gaps(sources: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    blockers = _value(sources, "status", ["remaining_known_blockers"])
    if not isinstance(blockers, list):
        return []
    gaps: list[dict[str, str]] = []
    for blocker in blockers:
        if isinstance(blocker, dict):
            gaps.append(
                {
                    "chain_id": str(blocker.get("chain_id") or ""),
                    "status": str(blocker.get("status") or ""),
                    "safe_boundary": str(blocker.get("safe_boundary") or ""),
                }
            )
    return gaps


def _load_source(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    payload: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        payload = loaded if isinstance(loaded, dict) else {"not_object": True}
    return {"path": relative_path, "exists": path.is_file(), "payload": payload}


def _source_status(sources: dict[str, dict[str, Any]], name: str) -> str:
    payload = sources.get(name, {}).get("payload")
    if not isinstance(payload, dict):
        return "missing"
    if "status" in payload:
        return str(payload["status"])
    if payload.get("all_exit_codes_zero") is True:
        return "pass"
    return "unknown"


def _checks_by_name(checks: Any) -> dict[str, bool]:
    if not isinstance(checks, list):
        return {}
    return {
        str(check.get("name")): check.get("ok") is True
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("name"), str)
    }


def _value(sources: dict[str, dict[str, Any]], name: str, path: list[Any]) -> Any:
    value: Any = sources.get(name, {}).get("payload", {})
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and isinstance(key, int) and 0 <= key < len(value):
            value = value[key]
        else:
            return None
    return value


def _gate_record(sources: dict[str, dict[str, Any]], gate_name: str) -> dict[str, Any]:
    gates = _value(sources, "status", ["gates"])
    if not isinstance(gates, list):
        return {}
    for gate in gates:
        if isinstance(gate, dict) and gate.get("name") == gate_name:
            return gate
    return {}


def _execution_contract(payload: Any) -> dict[str, bool]:
    payload = payload if isinstance(payload, dict) else {}
    contract = payload.get("execution_contract")
    source = contract if isinstance(contract, dict) else payload
    return {
        "model_invoked": source.get("model_invoked") is True,
        "database_written": source.get("database_written") is True,
        "runtime_imported": source.get("runtime_imported") is True,
        "business_secrets_read": source.get("business_secrets_read") is True,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cleanroom Goal Gap Audit 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Terror index estimate: `{report['terror_index_estimate']}`",
        f"Completion claim allowed: `{str(report['completion_claim_allowed']).lower()}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Completion Blockers", ""])
    for blocker in report["completion_blockers"]:
        lines.append(f"- `{blocker['chain_id']}` `{blocker['status']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"pass", "pass_with_known_gap"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
