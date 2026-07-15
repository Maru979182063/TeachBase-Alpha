from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "modularization_phase2a_test_report_20260715.json"

GATES = [
    (
        "semantic_role_eval",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_semantic_role_eval_schema.py",
            "tests/test_semantic_role_eval_metrics.py",
            "tests/test_semantic_role_gold_leakage.py",
            "tests/test_semantic_role_effectiveness_run.py",
            "tests/test_semantic_role_golden_parity.py",
            "-q",
        ],
    ),
    ("architecture_boundaries", [sys.executable, "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"]),
    ("repository_rescue_phase1", [sys.executable, "tools/run_repository_rescue_phase1_gate.py"]),
]


def run_gate(name: str, command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {
        "name": name,
        "command": command,
        "exit_code": proc.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": proc.stdout[-4000:],
    }


def main() -> int:
    results = [run_gate(name, command) for name, command in GATES]
    report = {
        "schema_version": "modularization_phase2a_gate_report.v0.1",
        "gate_count": len(results),
        "all_exit_codes_zero": all(row["exit_code"] == 0 for row in results),
        "gates": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_exit_codes_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
