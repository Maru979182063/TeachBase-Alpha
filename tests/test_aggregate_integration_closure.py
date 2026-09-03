from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from tools.build_final_chain_production_readiness_gate import BLOCKERS, build_report as build_production_report
from tools.check_active_absolute_paths import build_report as build_path_report
from tools.check_generated_material_policy import build_report as build_material_report
from tools.compare_release_gate_reports import build_report as compare_release_reports
from tools.run_final_chain_foundation_integration_gate import COMMANDS as FOUNDATION_COMMANDS

ROOT = Path(__file__).resolve().parents[1]
BASE = "b96a400daadd11fd496ecc47152861f3d5496dae"


def test_final_chain_production_readiness_stays_open_and_non_required() -> None:
    report = build_production_report()

    assert report["gate"] == "FINAL_CHAIN_PRODUCTION_READINESS"
    assert report["status"] == "BLOCKED"
    assert report["required_for_backend_foundation_integration"] is False
    assert report["blockers"] == BLOCKERS


def test_active_machine_path_contract_is_zero() -> None:
    report = build_path_report()

    assert report["status"] == "pass"
    assert report["active_absolute_path_count"] == 0


def test_generated_material_inventory_is_complete_and_approved() -> None:
    report = build_material_report(BASE, "439249e95ffd3d27427812ac2b6a59744efb7421")

    assert report["inventory_count"] == 103
    assert report["original_pre_phase2b_inventory_count"] == 101
    assert report["phase2b_added_material_count"] == 2
    assert report["unknown_paths"] == []
    assert report["tracked_ci_generated_paths"] == []
    assert report["invalid_format_paths"] == []


def test_final_chain_binary_fixtures_use_real_container_formats() -> None:
    fixture_root = ROOT / "tests/fixtures/final_chain_samples"
    for name in ("doc_math_sample.docx", "doc_english_sample.docx"):
        with ZipFile(fixture_root / name) as archive:
            assert archive.testzip() is None
            assert "word/document.xml" in archive.namelist()
    for name in ("pdf_math_sample.pdf", "pdf_english_sample.pdf"):
        assert (fixture_root / name).read_bytes().startswith(b"%PDF-")


def test_aggregate_workflow_is_cross_platform_and_uses_current_action_runtimes() -> None:
    workflow = (ROOT / ".github/workflows/backend-foundation-integration.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-node@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "actions/setup-java@v6" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "github.event.pull_request.head.ref || github.ref_name" in workflow
    assert "secrets." not in workflow


def test_pdf_english_source_contract_is_foundation_only() -> None:
    payload = json.loads(
        (ROOT / "config/english_text_first_graph_first/foundation_rebuild_sources.json").read_text(encoding="utf-8")
    )

    assert payload["production_evidence"] is False
    assert payload["production_readiness_status"] == "BLOCKED"
    assert set(payload["production_readiness_blockers"]) == set(BLOCKERS)


def test_final_chain_ops_precedes_precleanup_reference_audit() -> None:
    commands = [" ".join(command) for command in FOUNDATION_COMMANDS]
    ops_index = commands.index(next(command for command in commands if "run_final_chain_ops_gate.py" in command))
    audit_index = commands.index(next(command for command in commands if "build_precleanup_deep_audit.py" in command))
    import_index = commands.index(next(command for command in commands if "import_pdf_english_rebuild_sources.py" in command))
    decision_index = commands.index(next(command for command in commands if "build_pdf_english_rebuild_decision.py" in command))
    manifest_index = commands.index(next(command for command in commands if "build_cleanroom_hardening_manifest.py" in command))
    pytest_index = commands.index(next(command for command in commands if "pytest" in command))

    assert ops_index < audit_index
    assert import_index < decision_index < manifest_index < pytest_index


def test_release_baseline_comparison_is_environment_relative(tmp_path: Path) -> None:
    base = {
        "summary": {"total": 71, "passed": 63, "failed": 8, "verdict": "NO-GO"},
        "results": [{"id": f"failure-{index}", "status": "failed"} for index in range(8)],
    }
    head = json.loads(json.dumps(base))
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    head_path.write_text(json.dumps(head), encoding="utf-8")

    report = compare_release_reports(base_path, head_path)

    assert report["status"] == "pass"
    assert all(check["ok"] for check in report["checks"])
