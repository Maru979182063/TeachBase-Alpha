from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cleanroom_goal_gap_audit_tracks_residual_completion_gap() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_cleanroom_goal_gap_audit.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["schema_version"] == "cleanroom_goal_gap_audit.v0.1"
    assert payload["status"] == "pass_with_known_gap"
    assert payload["terror_index_estimate"] == "3.0_to_3.2"
    assert payload["completion_claim_allowed"] is False
    assert payload["completion_blockers"] == [
        {
            "chain_id": "pdf_english",
            "status": "blocked_missing_manifest_and_smoke_artifacts",
            "safe_boundary": "validate_pdf_english_recovery_requires_manifest_before_ready_claim",
        }
    ]
    assert checks["foundation_gate_sealed"]["ok"] is True
    assert checks["precleanup_gate_sealed"]["ok"] is True
    assert checks["final_chain_ops_gate_sealed"]["ok"] is True
    assert checks["four_final_chains_accounted_for"]["ok"] is True
    assert checks["scheduler_recovery_and_replacement_contract_present"]["ok"] is True
    assert checks["external_orchestrator_handshake_validated"]["ok"] is True
    assert checks["environment_interaction_isolated"]["ok"] is True
    assert checks["no_runtime_side_effects_reported"]["ok"] is True
    assert checks["terror_index_in_target_band"]["ok"] is True
    assert checks["cleanroom_manifest_validated"]["ok"] is True
    assert checks["final_chain_contract_tests_pass"]["ok"] is True
    assert checks["pdf_english_remains_fail_closed_not_silent_ready"]["ok"] is True
    assert checks["pdf_english_recovery_intake_gate_ready_for_restored_candidate"]["ok"] is True
    assert checks["final_chain_ops_health_seals_cli_and_recovery_surface"]["ok"] is True
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized
