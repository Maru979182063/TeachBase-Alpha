from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "final_chain_foundation_integration.json"

COMMANDS = [
    [sys.executable, "tools/run_foundation_hardening_gate.py"],
    [sys.executable, "tools/run_final_chain_ops_gate.py"],
    # 按依赖顺序生成 safety gate 的审计输入，避免依赖仓库中的历史报告缓存。
    [
        sys.executable,
        "tools/classify_final_chain_surface.py",
        "--target-root",
        ".",
        "--target-root-label",
        "cleanroom_partial_project",
        "--output-json",
        "docs/reports/final_chain_surface_classification_cleanroom_20260731.json",
        "--output-md",
        "docs/reports/final_chain_surface_classification_cleanroom_20260731.md",
    ],
    [
        sys.executable,
        "tools/build_cleanup_candidate_report.py",
        "--classification",
        "docs/reports/final_chain_surface_classification_cleanroom_20260731.json",
        "--target-root",
        ".",
        "--scan-references",
        "--output-json",
        "docs/reports/cleanup_candidates_cleanroom_20260731.json",
        "--output-md",
        "docs/reports/cleanup_candidates_cleanroom_20260731.md",
    ],
    [sys.executable, "tools/build_precleanup_deep_audit.py"],
    [sys.executable, "tools/run_precleanup_safety_gate.py"],
    [
        sys.executable,
        "tools/build_pdf_english_rebuild_decision.py",
        "--source-root",
        "repository_head=.",
    ],
    [sys.executable, "tools/validate_final_chain_registry.py", "--json"],
    [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_final_chain_control.py",
        "tests/test_final_chain_registry.py",
        "tests/test_final_chain_surface_classifier.py",
        "tests/test_cleanup_candidate_report.py",
        "tests/test_architecture_boundaries.py",
        "tests/test_aggregate_integration_closure.py",
        "-q",
    ],
    [sys.executable, "tools/check_active_absolute_paths.py"],
    [sys.executable, "tools/build_final_chain_production_readiness_gate.py"],
]


def run_gate() -> dict[str, Any]:
    results = [_run(command) for command in COMMANDS]
    production = _read_json(ROOT / "artifacts/ci/final_chain_production_readiness.json")
    ops = _read_json(ROOT / "docs/reports/final_chain_ops_gate_20260804.json")
    checks = [
        {
            "name": "all_foundation_commands_pass",
            "ok": all(result["exit_code"] == 0 for result in results),
            "value": [{"command": result["command"], "exit_code": result["exit_code"]} for result in results],
        },
        {
            "name": "pdf_english_rebuilds_from_head",
            "ok": ops.get("pdf_english_foundation_rebuild_status") == "PASS",
            "value": ops.get("pdf_english_foundation_rebuild_status"),
        },
        {
            "name": "production_readiness_remains_explicitly_blocked",
            "ok": production.get("status") == "BLOCKED"
            and production.get("required_for_backend_foundation_integration") is False,
            "value": production.get("blockers"),
        },
        {
            "name": "foundation_has_no_runtime_side_effects",
            "ok": ops.get("execution_contract")
            == {
                "model_invoked": False,
                "database_written": False,
                "runtime_imported": False,
                "business_secrets_read": False,
            },
            "value": ops.get("execution_contract"),
        },
    ]
    return {
        "schema_version": "final_chain_foundation_integration.v0.1",
        "gate": "FINAL_CHAIN_FOUNDATION_INTEGRATION",
        "status": "PASS" if all(check["ok"] for check in checks) else "FAIL",
        "required_check": True,
        "checks": checks,
        "commands": results,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def _run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "command": ["python" if index == 0 else value for index, value in enumerate(command)],
        "exit_code": completed.returncode,
        "passed_count": _passed_count(completed.stdout),
        "stdout_tail": _sanitize(completed.stdout[-1200:]),
        "stderr_tail": _sanitize(completed.stderr[-1200:]),
    }


def _passed_count(output: str) -> int | None:
    matches = re.findall(r"(\d+) passed", output)
    return int(matches[-1]) if matches else None


def _sanitize(value: str) -> str:
    value = value.replace(str(ROOT), "<workspace>")
    value = re.sub(r"[A-Za-z]:[/\\][^\r\n\"']+", "<absolute-path>", value)
    value = re.sub(r"/(?:Users|home)/[^\r\n\"']+", "<absolute-path>", value)
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    report = run_gate()
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
