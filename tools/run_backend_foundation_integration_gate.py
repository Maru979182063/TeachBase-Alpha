from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "backend_foundation_integration.json"


def run_gate(base: str) -> dict[str, Any]:
    commands = [
        ["npm", "run", "test:foundation-hardening"],
        ["npm", "run", "test:repository-rescue-phase1"],
        ["npm", "run", "test:modularization-phase2a"],
        ["npm", "run", "test:modularization-phase2b"],
        ["npm", "run", "test:precleanup-safety"],
        ["npm", "run", "test:final-chain-foundation-integration"],
        ["npm", "run", "test:java-shell-contract"],
        ["npm", "run", "test:java-backend-foundation"],
        ["npm", "run", "test:phase0-schema-spike"],
        ["npm", "run", "test:wp01-editor-working-draft-gate"],
        ["python", "tools/check_active_absolute_paths.py"],
        ["python", "tools/check_generated_material_policy.py", "--base", base],
        ["python", "tools/check_aggregate_repository_hygiene.py", "--base", base],
    ]
    results = [_run(command) for command in commands]
    return {
        "schema_version": "backend_foundation_integration_gate.v0.1",
        "gate": "BACKEND_FOUNDATION_INTEGRATION",
        "status": "PASS" if all(result["exit_code"] == 0 for result in results) else "FAIL",
        "base": base,
        "commands": results,
        "open_gates": [
            "FINAL_CHAIN_PRODUCTION_READINESS",
            "BLOCKS_TAG_SCHEMA_AND_SEARCH",
            "formal_authentication_and_acl",
            "frontend_409_merge_experience",
            "production_capacity",
            "standard_module",
            "unified_search",
            "knowledge_document",
            "question_group",
            "legacy_editor_draft_contract_drop",
        ],
        "baseline_debt": {
            "test_release_gate": "expected_68_of_71_until_separate_debt_work",
            "must_not_regress_from_base": True,
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written_outside_ephemeral_test_database": False,
            "production_runtime_imported": False,
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
    output = completed.stdout + "\n" + completed.stderr
    pass_matches = re.findall(r"(\d+) passed", output)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "passed_count": int(pass_matches[-1]) if pass_matches else None,
        "output_tail": _sanitize(output[-2000:]),
    }


def _sanitize(value: str) -> str:
    value = value.replace(str(ROOT), "<workspace>")
    value = re.sub(r"[A-Za-z]:[/\\][^\r\n\"']+", "<absolute-path>", value)
    return re.sub(r"/(?:Users|home)/[^\r\n\"']+", "<absolute-path>", value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the aggregate backend foundation integration gate.")
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    report = run_gate(args.base)
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
