from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "repository_rescue_phase1_test_report_20260715.json"

GATES = [
    ("pipeline_registry_validator", [sys.executable, "tools/validate_pipeline_registry.py", "--json"]),
    ("pipeline_registry_tests", [sys.executable, "-m", "pytest", "tests/test_pipeline_registry.py", "-q"]),
    (
        "semantic_shadow_isolation",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_semantic_role_shadow_isolation.py",
            "-q",
            "-k",
            "review_path_baseline_has_review or shadow_on_writes_only_allowed_sidecars or shadow_on_observes_real_role_differences or registry_declares_shadow_output_ownership",
        ],
    ),
    (
        "semantic_shadow_non_interference_real_rerun",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_semantic_role_shadow_isolation.py",
            "-q",
            "-k",
            "ready_path_experiments_off or review_path_experiments_off or review_reasons_and_repair_pool_non_interference or review_path_real_rerun_generator",
        ],
    ),
    (
        "semantic_eval",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_semantic_role_eval_schema.py",
            "tests/test_semantic_role_eval_metrics.py",
            "tests/test_semantic_role_gold_leakage.py",
            "tests/test_semantic_role_effectiveness_run.py",
            "-q",
        ],
    ),
    (
        "english_portable_regression",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_english_text_first_v05_pipeline.py",
            "tests/test_english_text_first_sidecar_graph_v01.py",
            "-q",
        ],
    ),
    (
        "docx_native_repair_regression",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_docx_native_formula_providers.py",
            "tests/test_docx_native_formula_token_stream_v01.py",
            "tests/test_docx_native_text_repair_model_node_v01.py",
            "-q",
        ],
    ),
]


def parse_pytest_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "not_run": 0}
    matches = re.findall(r"(\d+)\s+(passed|failed|skipped)", output)
    for raw_count, label in matches:
        counts[label] += int(raw_count)
    return counts


def run_gate(name: str, command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    duration = time.perf_counter() - started
    counts = parse_pytest_counts(proc.stdout)
    return {
        "name": name,
        "command": command,
        "exit_code": proc.returncode,
        **counts,
        "duration_seconds": round(duration, 3),
        "output_tail": proc.stdout[-4000:],
    }


def main() -> int:
    results = [run_gate(name, command) for name, command in GATES]
    report = {
        "schema_version": "repository_rescue_phase1_gate_report.v0.2",
        "gate_count": len(results),
        "passed": sum(row["passed"] for row in results),
        "failed": sum(row["failed"] for row in results),
        "skipped": sum(row["skipped"] for row in results),
        "not_run": sum(row["not_run"] for row in results),
        "all_exit_codes_zero": all(row["exit_code"] == 0 for row in results),
        "gates": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_exit_codes_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
