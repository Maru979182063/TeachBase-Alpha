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
        "name": "pdf_english_raw_pdf_promotion",
        "command": [sys.executable, "tools/build_pdf_english_raw_pdf_promotion_gate.py"],
        "report": "docs/reports/pdf_english_raw_pdf_promotion_20260806.json",
    },
    {
        "name": "pdf_english_rebuild_decision",
        "command": [
            sys.executable,
            "tools/build_pdf_english_rebuild_decision.py",
            "--source-root",
            "repository_head=.",
        ],
        "report": "docs/reports/pdf_english_rebuild_decision_20260804.json",
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
            "pdf_english_raw_pdf_java_shell_admission",
            "pdf_english_lost_artifact_rebuild_track",
        ],
        "checks": checks,
        "gates": gate_results,
        "remaining_known_blockers": [
            {
                "scope": "continuous_production_worker",
                "status": "java_orchestrator_worker_db_contract_not_implemented",
                "safe_boundary": "no_model_db_runtime_execution_without_explicit_worker_contract",
                "legacy_artifact_wait_required": False,
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
            "ok": all(
                gate["report_status"] in {"pass", "ok"}
                or (gate["name"] == "pdf_english_rebuild_decision" and gate["report_status"] == "rebuild_track_allowed")
                for gate in gate_results
            ),
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
                "name": "final_chain_ops_admits_pdf_english_after_raw_pdf_promotion",
                "ok": payload.get("pdf_english_raw_pdf_promotion_status") == "pass"
                and payload.get("pdf_english_java_shell_admission_allowed") is True
                and payload.get("environment_blocked_chain_ids") == [],
                "value": {
                    "promotion": payload.get("pdf_english_raw_pdf_promotion_status"),
                    "java_shell_admission": payload.get("pdf_english_java_shell_admission_allowed"),
                    "blocked": payload.get("environment_blocked_chain_ids"),
                },
            }
        )
        checks.append(
            {
                "name": "four_ready_chains_sample_scheduled",
                "ok": payload.get("ready_sample_count") == 4,
                "value": payload.get("ready_sample_count"),
            }
        )
    rebuild_gate = next((gate for gate in gate_results if gate["name"] == "pdf_english_rebuild_decision"), None)
    if rebuild_gate:
        payload = _read_report(rebuild_gate["report_path"])
        checks.append(
            {
                "name": "pdf_english_has_non_blocking_rebuild_track",
                "ok": payload.get("status") == "rebuild_track_allowed"
                and payload.get("rebuild_track_allowed") is True
                and payload.get("legacy_artifact_wait_required") is False
                and payload.get("ready_claim_allowed") is False,
                "value": {
                    "status": payload.get("status"),
                    "rebuild_track_allowed": payload.get("rebuild_track_allowed"),
                    "legacy_artifact_wait_required": payload.get("legacy_artifact_wait_required"),
                    "ready_claim_allowed": payload.get("ready_claim_allowed"),
                },
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
                "name": "cleanroom_hardening_manifest_tracks_continuous_production_blocker",
                "ok": any(
                    isinstance(item, dict)
                    and item.get("scope") == "continuous_production_worker"
                    and item.get("allowed_behavior") == "control_plane_dry_run_and_queue_only"
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
        lines.append(f"- `{blocker['scope']}`: `{blocker['status']}`")
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
