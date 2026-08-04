from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "docs" / "reports" / "cleanroom_hardening_status_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "cleanroom_hardening_status_20260804.md"

GATES = [
    {
        "name": "foundation_hardening",
        "command": [sys.executable, "tools/run_foundation_hardening_gate.py"],
        "report": "docs/reports/foundation_hardening_test_report_20260803.json",
    },
    {
        "name": "precleanup_safety",
        "command": [sys.executable, "tools/run_precleanup_safety_gate.py"],
        "report": "docs/reports/precleanup_safety_gate_20260804.json",
    },
    {
        "name": "final_chain_ops",
        "command": [sys.executable, "tools/run_final_chain_ops_gate.py"],
        "report": "docs/reports/final_chain_ops_gate_20260804.json",
    },
    {
        "name": "cleanroom_hardening_manifest",
        "command": [sys.executable, "tools/build_cleanroom_hardening_manifest.py"],
        "report": "docs/reports/cleanroom_hardening_manifest_20260804.json",
    },
    {
        "name": "cleanroom_hardening_manifest_validation",
        "command": [sys.executable, "tools/validate_cleanroom_hardening_manifest.py"],
        "report": "docs/reports/cleanroom_hardening_manifest_validation_20260804.json",
    },
    {
        "name": "final_chain_contract_tests",
        "command": [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_final_chain_control.py",
            "tests/test_final_chain_registry.py",
            "tests/test_final_chain_surface_classifier.py",
            "tests/test_cleanup_candidate_report.py",
            "tests/test_architecture_boundaries.py",
            "-q",
        ],
        "report": None,
    },
]


def run_command(command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = round(time.perf_counter() - started, 3)
    return {
        "command": _portable_command(command),
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "output_tail": completed.stdout[-5000:],
    }


def build_report() -> dict[str, Any]:
    gate_results = []
    for gate in GATES:
        result = run_command(gate["command"])
        report_payload = _read_report(gate["report"])
        gate_results.append(
            {
                "name": gate["name"],
                **result,
                "report_path": gate["report"],
                "report_status": _report_status(report_payload),
                "execution_contract": _execution_contract(report_payload),
            }
        )
    checks = _build_checks(gate_results)
    status = "pass" if all(check["ok"] for check in checks) else "fail"
    return {
        "schema_version": "cleanroom_hardening_status.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": status,
        "terror_index_estimate": "3.0_to_3.2",
        "scope": [
            "foundation_artifact_and_model_call_hardening",
            "precleanup_archive_safety",
            "final_chain_control_and_scheduling_shell",
            "pdf_english_recovery_fail_closed_boundary",
        ],
        "checks": checks,
        "gates": gate_results,
        "remaining_known_blockers": [
            {
                "chain_id": "pdf_english",
                "status": "blocked_missing_manifest_and_smoke_artifacts",
                "safe_boundary": "validate_pdf_english_recovery_requires_manifest_before_ready_claim",
            }
        ],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _read_report(relative_path: str | None) -> dict[str, Any]:
    if relative_path is None:
        return {"status": "pass", "execution_contract": _empty_execution_contract()}
    path = ROOT / relative_path
    if not path.is_file():
        return {"missing": True}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {"not_object": True}


def _report_status(report: dict[str, Any]) -> str:
    if report.get("missing"):
        return "missing"
    if "status" in report:
        return str(report["status"])
    if "ok" in report:
        return "pass" if report["ok"] is True else "fail"
    if "all_exit_codes_zero" in report:
        return "pass" if report["all_exit_codes_zero"] is True else "fail"
    return "unknown"


def _execution_contract(report: dict[str, Any]) -> dict[str, bool]:
    contract = report.get("execution_contract")
    if isinstance(contract, dict):
        return {
            "model_invoked": contract.get("model_invoked") is True,
            "database_written": contract.get("database_written") is True,
            "runtime_imported": contract.get("runtime_imported") is True,
            "business_secrets_read": contract.get("business_secrets_read") is True,
        }
    return {
        "model_invoked": report.get("model_invoked") is True,
        "database_written": report.get("database_written") is True,
        "runtime_imported": report.get("runtime_imported") is True,
        "business_secrets_read": report.get("business_secrets_read") is True,
    }


def _empty_execution_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def _build_checks(gate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = [
        {
            "name": "all_gate_exit_codes_zero",
            "ok": all(gate["exit_code"] == 0 for gate in gate_results),
            "value": {gate["name"]: gate["exit_code"] for gate in gate_results},
        },
        {
            "name": "all_gate_reports_pass_or_ok",
            "ok": all(gate["report_status"] in {"pass", "ok"} for gate in gate_results),
            "value": {gate["name"]: gate["report_status"] for gate in gate_results},
        },
        {
            "name": "no_gate_reports_runtime_side_effects",
            "ok": all(not any(gate["execution_contract"].values()) for gate in gate_results),
            "value": {gate["name"]: gate["execution_contract"] for gate in gate_results},
        },
    ]
    final_chain_gate = next((gate for gate in gate_results if gate["name"] == "final_chain_ops"), None)
    if final_chain_gate:
        payload = _read_report(final_chain_gate["report_path"])
        checks.append(
            {
                "name": "final_chain_ops_keeps_pdf_english_fail_closed",
                "ok": payload.get("pdf_english_recovery_validation_status") == "blocked_missing_or_invalid_manifest",
                "value": payload.get("pdf_english_recovery_validation_status"),
            }
        )
        checks.append(
            {
                "name": "three_ready_chains_sample_scheduled",
                "ok": payload.get("ready_sample_count") == 3,
                "value": payload.get("ready_sample_count"),
            }
        )
    manifest_gate = next((gate for gate in gate_results if gate["name"] == "cleanroom_hardening_manifest"), None)
    if manifest_gate:
        payload = _read_report(manifest_gate["report_path"])
        checks.append(
            {
                "name": "cleanroom_hardening_manifest_passes",
                "ok": payload.get("status") == "pass",
                "value": payload.get("status"),
            }
        )
        checks.append(
            {
                "name": "cleanroom_hardening_manifest_tracks_known_blocker",
                "ok": any(
                    isinstance(item, dict)
                    and item.get("chain_id") == "pdf_english"
                    and item.get("allowed_behavior") == "fail_closed"
                    for item in payload.get("known_blockers", [])
                ),
                "value": payload.get("known_blockers", []),
            }
        )
    manifest_validation_gate = next(
        (gate for gate in gate_results if gate["name"] == "cleanroom_hardening_manifest_validation"), None
    )
    if manifest_validation_gate:
        payload = _read_report(manifest_validation_gate["report_path"])
        checks.append(
            {
                "name": "cleanroom_hardening_manifest_validation_passes",
                "ok": payload.get("status") == "pass",
                "value": payload.get("status"),
            }
        )
        checks.append(
            {
                "name": "cleanroom_hardening_manifest_validation_is_portable",
                "ok": payload.get("workspace_contract") == "relative_git_paths_only"
                and payload.get("absolute_paths_as_inputs") is False,
                "value": {
                    "workspace_contract": payload.get("workspace_contract"),
                    "absolute_paths_as_inputs": payload.get("absolute_paths_as_inputs"),
                },
            }
        )
    return checks


def _portable_command(command: list[str]) -> list[str]:
    portable = []
    for item in command:
        path = Path(item)
        if path.is_absolute() and path == Path(sys.executable):
            portable.append("python")
        else:
            portable.append(item.replace("\\", "/"))
    return portable


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Cleanroom Hardening Status 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Terror index estimate: `{report['terror_index_estimate']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Remaining Known Blockers", ""])
    for blocker in report["remaining_known_blockers"]:
        lines.append(f"- `{blocker['chain_id']}`: `{blocker['status']}`")
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
