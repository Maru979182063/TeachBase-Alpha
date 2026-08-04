from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "precleanup_safety_gate_20260804.json"
COMPARTMENT_REPORT = ROOT / "docs" / "reports" / "worktree_compartments_20260804.json"


def run_gate(name: str, portable_command: list[str]) -> dict[str, Any]:
    actual_command = [sys.executable if part == "python" else part for part in portable_command]
    started = time.perf_counter()
    completed = subprocess.run(
        actual_command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "name": name,
        "command": portable_command,
        "exit_code": completed.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": completed.stdout[-4000:],
    }


def compartment_summary() -> dict[str, Any]:
    if not COMPARTMENT_REPORT.exists():
        return {"available": False, "unclassified": None, "counts": {}}
    report = read_json(COMPARTMENT_REPORT)
    counts = report.get("counts", {}) if isinstance(report, dict) else {}
    return {
        "available": True,
        "absolute_paths_as_inputs": bool(report.get("absolute_paths_as_inputs", True)),
        "unclassified": int(counts.get("unclassified", 0) or 0),
        "counts": counts,
    }


def main() -> int:
    gates = [
        run_gate("foundation_hardening", ["python", "tools/run_foundation_hardening_gate.py"]),
        run_gate(
            "final_chain_registry",
            [
                "python",
                "-m",
                "pytest",
                "tests/test_final_chain_registry.py",
                "-q",
            ],
        ),
        run_gate(
            "final_chain_registry_validator",
            ["python", "tools/validate_final_chain_registry.py", "--json"],
        ),
        run_gate(
            "final_chain_surface_classifier",
            ["python", "-m", "pytest", "tests/test_final_chain_surface_classifier.py", "-q"],
        ),
        run_gate(
            "cleanup_candidate_report",
            ["python", "-m", "pytest", "tests/test_cleanup_candidate_report.py", "-q"],
        ),
        run_gate(
            "precleanup_archive_safety",
            ["python", "-m", "pytest", "tests/test_precleanup_archive_safety.py", "-q"],
        ),
        run_gate(
            "precleanup_post_archive_report",
            ["python", "-m", "pytest", "tests/test_precleanup_post_archive_report.py", "-q"],
        ),
        run_gate("precleanup_post_archive_state", ["python", "tools/build_precleanup_post_archive_report.py"]),
        run_gate("worktree_compartments_final", ["python", "tools/build_worktree_compartment_report.py"]),
    ]
    compartments = compartment_summary()
    all_exit_codes_zero = all(gate["exit_code"] == 0 for gate in gates)
    unclassified_zero = compartments.get("unclassified") == 0
    report = {
        "schema_version": "precleanup_safety_gate_report.v0.1",
        "purpose": "guard cleanup work before archiving, deleting, or moving chain-adjacent files",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "business_secrets_read": False,
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "all_exit_codes_zero": all_exit_codes_zero,
        "unclassified_compartments_zero": unclassified_zero,
        "ok": bool(all_exit_codes_zero and unclassified_zero),
        "compartments": compartments,
        "gates": gates,
    }
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
