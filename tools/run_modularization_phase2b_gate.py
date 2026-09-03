from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "reports" / "modularization_phase2b_test_report_20260715.json"
LEGACY_CLI_OUT = ROOT / "outputs" / "modularization_phase2b_legacy_cli_smoke"
REPORTS_TO_PRESERVE = [
    ROOT / "docs" / "reports" / "modularization_phase2a_test_report_20260715.json",
    ROOT / "docs" / "reports" / "repository_rescue_phase1_test_report_20260715.json",
]

GATES = [
    ("phase2a_full_gate", [sys.executable, "tools/run_modularization_phase2a_gate.py"], {0}),
    (
        "phase2b_config_parity",
        [sys.executable, "-m", "pytest", "tests/test_semantic_profile_config_parity.py", "-q"],
        {0},
    ),
    (
        "phase2b_artifact_concurrency_cleanup",
        [sys.executable, "-m", "pytest", "tests/test_artifact_store_atomic_writes.py", "-q"],
        {0},
    ),
    ("architecture_boundaries", [sys.executable, "-m", "pytest", "tests/test_architecture_boundaries.py", "-q"], {0}),
    (
        "legacy_cli_compatibility",
        [
            sys.executable,
            "tools/run_semantic_role_effectiveness_eval.py",
            "--run-id",
            "phase2b_legacy_cli_smoke",
            "--out-root",
            "outputs/modularization_phase2b_legacy_cli_smoke",
        ],
        {20},
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
        {0},
    ),
    (
        "docx_native_regression",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_docx_native_formula_providers.py",
            "tests/test_docx_native_formula_token_stream_v01.py",
            "tests/test_docx_native_text_repair_model_node_v01.py",
            "-q",
        ],
        {0},
    ),
]


def clean_legacy_cli_output() -> None:
    shutil.rmtree(LEGACY_CLI_OUT, ignore_errors=True)


def snapshot_files(paths: list[Path]) -> dict[Path, str | None]:
    return {path: path.read_text(encoding="utf-8") if path.exists() else None for path in paths}


def restore_files(snapshot: dict[Path, str | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.write_text(content, encoding="utf-8")


def sanitize_text(text: str) -> str:
    sanitized = text
    replacements = {
        str(ROOT): "<WORKSPACE>",
        str(ROOT).replace("\\", "/"): "<WORKSPACE>",
        sys.executable: "<PYTHON>",
        sys.executable.replace("\\", "/"): "<PYTHON>",
        json.dumps(sys.executable)[1:-1]: "<PYTHON>",
    }
    for source, target in replacements.items():
        sanitized = sanitized.replace(source, target)
    sanitized = re.sub(r"C:\\+Users\\+[^\"\n]*?python\.exe", "<PYTHON>", sanitized)
    sanitized = re.sub(r"C:/Users/[^\"\n]*?python\.exe", "<PYTHON>", sanitized)
    return sanitized


def portable_command(command: list[str]) -> list[str]:
    portable = []
    for idx, part in enumerate(command):
        if idx == 0 and part == sys.executable:
            portable.append("python")
        else:
            portable.append(sanitize_text(part))
    return portable


def run_gate(name: str, command: list[str], expected_exit_codes: set[int]) -> dict[str, Any]:
    if name == "legacy_cli_compatibility":
        clean_legacy_cli_output()
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    exit_code_expected = proc.returncode in expected_exit_codes
    return {
        "name": name,
        "command": portable_command(command),
        "exit_code": proc.returncode,
        "expected_exit_codes": sorted(expected_exit_codes),
        "exit_code_expected": exit_code_expected,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": sanitize_text(proc.stdout[-4000:]),
    }


def main() -> int:
    preserved_reports = snapshot_files(REPORTS_TO_PRESERVE)
    try:
        results = [run_gate(name, command, expected) for name, command, expected in GATES]
    finally:
        restore_files(preserved_reports)
    report = {
        "schema_version": "modularization_phase2b_gate_report.v0.1",
        "phase": "Phase 2B Package Foundation Hardening",
        "gate_count": len(results),
        "all_expected_exit_codes": all(row["exit_code_expected"] for row in results),
        "business_secrets_required": False,
        "model_invoked": False,
        "database_write_attempted": False,
        "runtime_import_attempted": False,
        "gates": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_expected_exit_codes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
