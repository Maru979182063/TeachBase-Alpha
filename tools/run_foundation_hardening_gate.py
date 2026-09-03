from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "foundation_hardening_test_report_20260803.json"


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


def main() -> int:
    gates = [
        run_gate(
            "artifact_store_atomicity",
            ["python", "-m", "pytest", "tests/test_artifact_store.py", "-q"],
        ),
        run_gate(
            "model_call_retry_checkpoint",
            ["python", "-m", "pytest", "tests/test_model_call_guard.py", "-q"],
        ),
        run_gate(
            "docx_model_checkpoint_integration",
            ["python", "-m", "pytest", "tests/test_docx_native_text_repair_model_node_v01.py", "-q"],
        ),
        run_gate(
            "visual_model_checkpoint_integration",
            ["python", "-m", "pytest", "tests/test_visual_model_checkpoint_integration.py", "-q"],
        ),
        run_gate(
            "architecture_boundaries",
            ["python", "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"],
        ),
    ]
    report = {
        "schema_version": "foundation_hardening_gate_report.v0.1",
        "scope": [
            "artifact_store_atomic_writes",
            "model_call_retry_checkpoint_guard",
            "docx_model_checkpoint_integration",
            "visual_model_checkpoint_integration",
            "architecture_boundaries",
        ],
        "business_secrets_read": False,
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "all_exit_codes_zero": all(gate["exit_code"] == 0 for gate in gates),
        "gates": gates,
    }
    write_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_exit_codes_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
