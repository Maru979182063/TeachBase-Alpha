from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.validate_java_shell_contract import CONTRACT, build_report

ROOT = Path(__file__).resolve().parents[1]


def test_java_shell_contract_validates_without_side_effects() -> None:
    report = build_report(CONTRACT)
    checks = {item["name"]: item for item in report["checks"]}

    assert report["schema_version"] == "java_shell_contract_validation.v0.1"
    assert report["status"] == "pass"
    assert checks["four_protected_chain_ids_declared"]["ok"] is True
    assert checks["task_state_machine_declares_required_statuses"]["ok"] is True
    assert checks["database_contract_declares_required_tables"]["ok"] is True
    assert checks["worker_contract_has_lock_heartbeat_timeout_retry_and_dedupe"]["ok"] is True
    assert checks["ui_contract_hides_internal_nodes"]["ok"] is True
    assert report["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_java_shell_contract_cli_writes_portable_report() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/validate_java_shell_contract.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "pass"
    assert payload["contract_path"] == "config/java_shell_contract_v01.json"
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized
