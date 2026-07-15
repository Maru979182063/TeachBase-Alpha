from __future__ import annotations

import json
from pathlib import Path

from tools.run_semantic_role_effectiveness_eval import DEFAULT_CASES, OUTPUT_FILES, run_eval


def test_semantic_role_eval_matches_phase2a_golden_contract(tmp_path: Path) -> None:
    exit_code, summary = run_eval(cases_path=DEFAULT_CASES, out_root=tmp_path, run_id="phase2a_golden")

    assert exit_code == 20
    assert summary["status"] == "SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED"
    assert summary["verified_real_gold_case_count"] == 0
    assert summary["contract_fixture_count"] == 12
    assert summary["candidate_case_count"] == 12
    assert summary["hard_safety_gate_passed"] is True
    assert summary["dataset_coverage_gate_passed"] is False
    assert summary["model_invoked"] is False
    assert summary["paid_model_invoked"] is False
    assert summary["database_write_attempted"] is False
    assert summary["runtime_import_attempted"] is False

    out_dir = tmp_path / "phase2a_golden"
    for name in OUTPUT_FILES:
        assert (out_dir / name).exists(), name
    assert (out_dir / "review_pack" / "index.html").exists()
    assert (out_dir / "review_pack" / "review_decisions.json").exists()

    coverage = json.loads((out_dir / "dataset_coverage.json").read_text(encoding="utf-8-sig"))
    assert coverage["evaluation_tier_counts"] == {"CONTRACT_FIXTURE": 12}
    assert coverage["verified_real_gold_case_count"] == 0
    assert coverage["coverage_gate"]["passed"] is False

    manifest = json.loads((out_dir / "evaluation_manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["adapter_mode"] == "shadow_only"
    assert manifest["business_mutation_allowed"] is False
    assert manifest["model_invoked"] is False
    assert manifest["paid_model_invoked"] is False
    assert manifest["database_write_attempted"] is False
    assert manifest["runtime_import_attempted"] is False
