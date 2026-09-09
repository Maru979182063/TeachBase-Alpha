from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_g5_workflow_is_cross_platform_and_runs_the_complete_gate() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "g5-canonical-import.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["g5-gate"]
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    rendered = workflow_path.read_text(encoding="utf-8")
    assert "npm run test:g5-canonical-import" in rendered
    assert "cancel-in-progress: true" in rendered
    assert "python-version: \"3.12\"" in rendered
    assert "node-version: \"20\"" in rendered
    assert "java-version: \"21\"" in rendered


def test_g5_aggregate_gate_includes_the_g4_full_gate() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["test:g5-canonical-import"]
    assert "npm run test:g4-handout-foundation" in command
    assert "npm run test:g4-handout-live" not in command


def test_g5_contract_keeps_domain_and_non_scope_boundaries_explicit() -> None:
    contract = (ROOT / "docs" / "architecture" / "g5_canonical_import_contract.md").read_text(encoding="utf-8")
    for value in (
        "ordinary_content",
        "stable identity",
        "immutable revision",
        "occurrence",
        "source evidence",
        "teacher",
        "student",
        "Release Seed",
        "Risk",
    ):
        assert value in contract


def test_g5_machine_schema_is_versioned_and_question_agnostic() -> None:
    schema = json.loads((ROOT / "config" / "canonical_import" / "canonical_content_import_v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:teachbase:canonical-content-import:v1"
    required = set(schema["required"])
    assert {"questions", "standardModules", "handout", "sourceDocuments", "sourceRegions"} <= required
    assert schema["properties"]["contractVersion"]["const"] == "teachbase.canonical-content-import.v1"


def test_machine_reports_are_real_and_green_when_present() -> None:
    for name in ("g5_v010_migration_gate.json", "g5_canonical_import_live_gate.json"):
        path = ROOT / "docs" / "reports" / name
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["status"] == "passed"
        assert report["cleanup"] == "passed"
