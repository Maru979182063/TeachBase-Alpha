from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from teachbase.final_chains import (
    ChainRunRequest,
    EnvironmentPolicy,
    FINAL_CHAIN_JOB_STATUSES,
    build_environment_interaction_contract,
    build_final_chain_adapters,
    build_final_chain_control_dashboard,
    build_chain_run_plan,
    build_cleanroom_import_audit,
    build_final_chain_control_contract,
    build_job_recovery_plan,
    build_job_recovery_plan_path,
    build_readiness_matrix,
    describe_adapters,
    inspect_adapter_contracts,
    inspect_job_record,
    inspect_registry_environments,
    load_final_chain_registry,
    schedule_chain_run,
    schedule_replacement_chain_run,
    schedule_registry_batch,
    transition_job_record,
    transition_job_record_path,
    validate_job_record,
)
from teachbase.core.errors import ConfigurationError


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"


def _valid_job_record_with_history(status: str, history: list[dict]) -> dict:
    latest_version = int(history[-1]["version"])
    return {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": "job",
        "created_at": "2026-08-04T00:00:00+00:00",
        "status": status,
        "chain_id": "pdf_math",
        "record_path": "outputs/final_chain_runs/_control/jobs/job/job_record.json",
        "plan": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
        "request_snapshot": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
        "environment_snapshot": {},
        "lifecycle": {
            "schema_version": "final_chain_job_lifecycle.v0.1",
            "status": status,
            "state_version": latest_version,
            "terminal": status in {"scheduled_blocked", "rejected", "dry_run_passed", "dry_run_failed", "cancelled"},
            "allowed_next_statuses": {
                "scheduled_ready": ["dry_run_started", "cancelled"],
                "dry_run_started": ["dry_run_passed", "dry_run_failed", "cancelled"],
            }.get(status, []),
            "updated_at": "2026-08-04T00:00:00+00:00",
            "history": history,
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
        "errors": [],
    }


def _write_minimal_english_docx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        "word/_rels/document.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""",
        "word/document.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Read the passage and answer the question.</w:t></w:r></w:p>
    <w:p><w:r><w:t>1. Choose the best title.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Answer: </w:t></w:r><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>    1    </w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>""",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_final_chain_control_lists_four_registered_chains_without_runtime_imports() -> None:
    registry = load_final_chain_registry(REGISTRY)

    assert [chain.chain_id for chain in registry.chains] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert all(chain.runtime_import_default_enabled is False for chain in registry.chains)
    assert all(chain.database_write_default_enabled is False for chain in registry.chains)


def test_plan_blocks_wrong_input_format_before_execution() -> None:
    registry = load_final_chain_registry(REGISTRY)
    request = ChainRunRequest(chain_id="pdf_math", input_path="sample.docx", output_root="outputs/final_chain_runs")

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "input_format_matches_chain" in plan["blocked_reasons"]
    assert "input_path_present" in plan["blocked_reasons"]
    assert plan["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_plan_reports_missing_cleanroom_entrypoints_as_blockers() -> None:
    registry = load_final_chain_registry(REGISTRY)
    request = ChainRunRequest(chain_id="pdf_english", input_path="sample.pdf", output_root="outputs/final_chain_runs")

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "input_path_present" in plan["blocked_reasons"]


def test_environment_flags_are_not_a_backdoor_for_dry_run_control() -> None:
    registry = load_final_chain_registry(REGISTRY)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path="sample.pdf",
        output_root="outputs/final_chain_runs",
        environment=EnvironmentPolicy(
            name="unsafe_probe",
            allow_model_calls=True,
            allow_database_writes=True,
            allow_runtime_import=True,
        ),
    )

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "environment_blocks_model_calls" in plan["blocked_reasons"]
    assert "environment_blocks_database_writes" in plan["blocked_reasons"]
    assert "environment_blocks_runtime_import" in plan["blocked_reasons"]


def test_execute_intent_is_not_a_backdoor_for_control_plane() -> None:
    registry = load_final_chain_registry(REGISTRY)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path="tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
        output_root="outputs/final_chain_runs",
        dry_run=False,
    )

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "control_plane_dry_run_only" in plan["blocked_reasons"]
    assert plan["execution_contract"]["model_invoked"] is False


def test_plan_requires_existing_input_file_and_workspace_output(tmp_path: Path) -> None:
    registry = load_final_chain_registry(REGISTRY)
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(sample),
        output_root=str(tmp_path.parent / "outside"),
    )

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert "input_path_present" not in plan["blocked_reasons"]
    assert "output_root_inside_workspace" in plan["blocked_reasons"]


def test_plan_requires_output_root_under_outputs() -> None:
    registry = load_final_chain_registry(REGISTRY)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path="sample.pdf",
        output_root="config/final_chain_runs",
    )

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "output_root_under_outputs" in plan["blocked_reasons"]


def test_unknown_chain_id_fails_closed() -> None:
    registry = load_final_chain_registry(REGISTRY)

    with pytest.raises(ConfigurationError):
        registry.get("unknown")


def test_final_chain_control_cli_outputs_machine_readable_plan() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "plan",
            "--chain-id",
            "doc_math",
            "--input",
            "fixture.docx",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_run_plan.v0.1"
    assert payload["chain_id"] == "doc_math"
    assert payload["status"] == "blocked"
    assert "input_path_present" in payload["blocked_reasons"]


def test_final_chain_control_cli_execute_intent_is_blocked() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "plan",
            "--chain-id",
            "pdf_math",
            "--input",
            "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
            "--execute",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "blocked"
    assert payload["dry_run"] is False
    assert "control_plane_dry_run_only" in payload["blocked_reasons"]


def test_scheduler_records_blocked_job_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(input_path.relative_to(workspace)),
        output_root="outputs/final_chain_runs",
        environment=EnvironmentPolicy(allow_model_calls=True),
    )

    record = schedule_chain_run(registry, request, workspace_root=workspace)

    assert record["status"] == "scheduled_blocked"
    assert record["execution_contract"]["model_invoked"] is False
    assert "environment_blocks_model_calls" in record["plan"]["blocked_reasons"]
    assert record["request_snapshot"]["workspace_contract"] == "relative_git_paths_only"
    assert record["request_snapshot"]["input"]["path"] == "input.pdf"
    assert record["request_snapshot"]["input"]["sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert record["plan"]["workspace_contract"] == "relative_git_paths_only"
    assert record["environment_snapshot"]["isolation_checks"]["model_calls_disabled"] is False
    assert record["environment_snapshot"]["execution_contract"]["model_invoked"] is False
    record_path = workspace / record["record_path"]
    assert record_path.exists()
    assert json.loads(record_path.read_text(encoding="utf-8"))["job_id"] == record["job_id"]
    assert record["lifecycle"]["status"] == "scheduled_blocked"
    assert record["lifecycle"]["terminal"] is True
    assert record["lifecycle"]["allowed_next_statuses"] == []
    assert record["record_validation"]["ok"] is True
    assert validate_job_record(record)["ok"] is True


def test_scheduler_rejects_output_root_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(chain_id="pdf_math", input_path="input.pdf", output_root=str(tmp_path / "outside"))

    record = schedule_chain_run(registry, request, workspace_root=workspace)

    assert record["status"] == "rejected"
    assert record["record_path"] == ""
    assert record["plan"]["output_root"] == "<outside-workspace>"
    assert record["request_snapshot"]["output_root"]["path"] == "<outside-workspace>"
    assert record["request_snapshot"]["output_root"]["inside_workspace"] is False
    assert record["errors"] == [{"code": "output_root_outside_workspace"}]
    assert record["lifecycle"]["status"] == "rejected"
    assert record["lifecycle"]["terminal"] is True
    assert record["record_validation"]["ok"] is True
    assert validate_job_record(record)["ok"] is True
    assert not (tmp_path / "outside").exists()


def test_scheduler_rejects_output_root_inside_workspace_but_outside_outputs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(input_path.relative_to(workspace)),
        output_root="config/final_chain_runs",
    )

    record = schedule_chain_run(registry, request, workspace_root=workspace)

    assert record["status"] == "rejected"
    assert record["record_path"] == ""
    assert record["errors"] == [{"code": "output_root_not_under_outputs"}]
    assert record["request_snapshot"]["output_root"]["path"] == "config/final_chain_runs"
    assert record["request_snapshot"]["output_root"]["inside_workspace"] is True
    assert record["lifecycle"]["status"] == "rejected"
    assert record["lifecycle"]["terminal"] is True
    assert record["record_validation"]["ok"] is True
    assert validate_job_record(record)["ok"] is True
    assert not (workspace / "config" / "final_chain_runs").exists()


def test_scheduler_snapshots_absolute_input_as_portable_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(input_path),
        output_root="outputs/final_chain_runs",
    )

    record = schedule_chain_run(registry, request, workspace_root=workspace)

    assert record["status"] == "scheduled_ready"
    assert record["request_snapshot"]["input"]["path"] == "input.pdf"
    assert record["plan"]["input_path"] == "input.pdf"
    assert record["request_snapshot"]["input"]["size_bytes"] == input_path.stat().st_size
    assert str(workspace) not in json.dumps(record)
    assert record["environment_snapshot"]["isolation_checks"] == {
        "model_calls_disabled": True,
        "database_writes_disabled": True,
        "runtime_import_disabled": True,
    }
    assert record["record_validation"]["ok"] is True
    assert validate_job_record(record)["ok"] is True

    bad_record = json.loads(json.dumps(record))
    bad_record["lifecycle"]["status"] = "dry_run_started"
    bad_record["record_path"] = "D:\\unsafe\\job_record.json"
    validation = validate_job_record(bad_record)
    error_codes = {error["code"] for error in validation["errors"]}
    assert validation["ok"] is False
    assert "lifecycle_status_mismatch" in error_codes
    assert "record_path_not_portable" in error_codes
    assert "absolute_path_leak" in error_codes
    assert "D:\\unsafe" not in json.dumps(validation)

    leaking_record = json.loads(json.dumps(record))
    leaking_record["status"] = "D:\\unsafe\\status"
    leaking_validation = validate_job_record(leaking_record)
    assert "unknown_status" in {error["code"] for error in leaking_validation["errors"]}
    assert "D:\\unsafe" not in json.dumps(leaking_validation)


def test_scheduler_retries_job_id_collision_without_overwriting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import teachbase.final_chains.control as control_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(chain_id="pdf_math", input_path="input.pdf", output_root="outputs/final_chain_runs")
    ids = iter(
        [
            "final_chain_pdf_math_collision",
            "final_chain_pdf_math_collision",
            "final_chain_pdf_math_unique",
        ]
    )
    monkeypatch.setattr(control_module, "generate_run_id", lambda prefix: next(ids))

    first = schedule_chain_run(registry, request, workspace_root=workspace)
    second = schedule_chain_run(registry, request, workspace_root=workspace)

    assert first["job_id"] == "final_chain_pdf_math_collision"
    assert second["job_id"] == "final_chain_pdf_math_unique"
    assert first["record_path"] != second["record_path"]
    first_payload = json.loads((workspace / first["record_path"]).read_text(encoding="utf-8"))
    second_payload = json.loads((workspace / second["record_path"]).read_text(encoding="utf-8"))
    assert first_payload["job_id"] == first["job_id"]
    assert second_payload["job_id"] == second["job_id"]
    assert validate_job_record(first_payload)["ok"] is True
    assert validate_job_record(second_payload)["ok"] is True


def test_english_docx_native_md_records_portable_source_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools_path = ROOT / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    import english_docx_native_md_v01 as native_md

    workspace = tmp_path / "workspace"
    docx_path = workspace / "inputs" / "english_native_smoke.docx"
    out_root = workspace / "outputs" / "english_docx_native_md"
    _write_minimal_english_docx(docx_path)
    monkeypatch.setattr(native_md, "ROOT", workspace)

    summary = native_md.run(
        SimpleNamespace(
            docx=docx_path,
            run_id="portable_source_paths",
            out_root=str(out_root),
            clean=True,
        )
    )
    block_stream_path = workspace / summary["artifacts"]["block_stream"]
    block_stream = json.loads(block_stream_path.read_text(encoding="utf-8"))

    assert summary["status"] == "ok"
    assert summary["source_docx"] == "inputs/english_native_smoke.docx"
    assert block_stream["source_docx"] == "inputs/english_native_smoke.docx"
    assert Path(summary["source_docx"]).is_absolute() is False
    assert Path(block_stream["source_docx"]).is_absolute() is False
    assert block_stream["counts"]["word_underline_blank_tokens"] == 1
    assert "[[BLANK_1]]" in (workspace / summary["artifacts"]["document_markdown"]).read_text(encoding="utf-8")
    assert str(workspace) not in json.dumps(summary)
    assert str(workspace) not in json.dumps(block_stream)


def test_batch_scheduler_queues_all_four_ready_chains_after_raw_pdf_promotion() -> None:
    registry = load_final_chain_registry(REGISTRY)
    sample_inputs = {
        "doc_math": "tests/fixtures/final_chain_samples/doc_math_sample.docx",
        "doc_english": "tests/fixtures/final_chain_samples/doc_english_sample.docx",
        "pdf_math": "tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
        "pdf_english": "tests/fixtures/final_chain_samples/pdf_english_sample.pdf",
    }

    report = schedule_registry_batch(
        registry,
        sample_inputs,
        output_root="outputs/final_chain_batch_queue",
        workspace_root=ROOT,
    )

    rows = {row["chain_id"]: row for row in report["rows"]}
    serialized = json.dumps(report, ensure_ascii=False)
    assert report["schema_version"] == "final_chain_batch_queue_report.v0.1"
    assert report["status"] == "pass"
    assert report["workspace_contract"] == "relative_git_paths_only"
    assert report["absolute_paths_as_inputs"] is False
    assert report["chain_count"] == 4
    assert report["scheduled_ready_count"] == 4
    assert report["scheduled_blocked_count"] == 0
    assert report["rejected_count"] == 0
    assert rows["doc_math"]["schedule_status"] == "scheduled_ready"
    assert rows["doc_english"]["schedule_status"] == "scheduled_ready"
    assert rows["pdf_math"]["schedule_status"] == "scheduled_ready"
    assert rows["pdf_english"]["schedule_status"] == "scheduled_ready"
    assert rows["pdf_english"]["blocked_reasons"] == []
    assert all(row["record_validation_ok"] and row["self_validation_ok"] for row in report["rows"])
    assert all(row["record_path"].startswith("outputs/final_chain_batch_queue/_control/jobs/") for row in report["rows"])
    assert report["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_job_lifecycle_allows_only_guarded_dry_run_transitions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(input_path.relative_to(workspace)),
        output_root="outputs/final_chain_runs",
    )
    record = schedule_chain_run(registry, request, workspace_root=workspace)

    started = transition_job_record(record, "dry_run_started", reason="adapter dry-run accepted")
    checkpoint_path = "outputs/final_chain_runs/report.json"
    passed = transition_job_record(
        started,
        "dry_run_passed",
        reason="adapter dry-run completed",
        checkpoint={"record_path": Path(checkpoint_path)},
    )
    inspection = inspect_job_record(passed)

    assert started["status"] == "dry_run_started"
    assert started["lifecycle"]["allowed_next_statuses"] == ["dry_run_passed", "dry_run_failed", "cancelled"]
    assert passed["status"] == "dry_run_passed"
    assert passed["lifecycle"]["terminal"] is True
    assert passed["lifecycle"]["history"][-1]["checkpoint"]["record_path"] == checkpoint_path
    assert started["record_validation"]["ok"] is True
    assert passed["record_validation"]["ok"] is True
    assert validate_job_record(passed)["ok"] is True
    assert inspection["terminal"] is True
    assert inspection["model_invoked"] is False


def test_job_lifecycle_portabilizes_string_checkpoint_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    record = {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": "job",
        "created_at": "2026-08-04T00:00:00+00:00",
        "status": "dry_run_started",
        "chain_id": "pdf_math",
    }
    report_path = workspace / "outputs" / "final_chain_runs" / "report.json"
    outside_path = tmp_path / "outside" / "report.json"

    passed = transition_job_record(
        record,
        "dry_run_passed",
        reason="adapter dry-run completed",
        checkpoint={"report_path": str(report_path), "outside_path": str(outside_path)},
        workspace_root=workspace,
    )

    checkpoint = passed["lifecycle"]["history"][-1]["checkpoint"]
    assert checkpoint["report_path"] == "outputs/final_chain_runs/report.json"
    assert checkpoint["outside_path"] == "<outside-workspace>"
    assert passed["record_validation"]["ok"] is False
    assert passed["record_validation"]["error_count"] > 0
    assert str(tmp_path) not in json.dumps(checkpoint)


def test_job_lifecycle_rejects_illegal_transition() -> None:
    record = {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": "job",
        "created_at": "2026-08-04T00:00:00+00:00",
        "status": "scheduled_blocked",
        "chain_id": "pdf_math",
    }

    with pytest.raises(ConfigurationError):
        transition_job_record(record, "dry_run_started", reason="blocked jobs cannot start")


def test_job_lifecycle_rejects_stale_expected_status_and_version() -> None:
    record = {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": "job",
        "created_at": "2026-08-04T00:00:00+00:00",
        "status": "scheduled_ready",
        "chain_id": "pdf_math",
        "lifecycle": {
            "schema_version": "final_chain_job_lifecycle.v0.1",
            "status": "scheduled_ready",
            "state_version": 2,
            "terminal": False,
            "allowed_next_statuses": ["dry_run_started", "cancelled"],
            "updated_at": "2026-08-04T00:00:00+00:00",
            "history": [
                {
                    "version": 1,
                    "status": "scheduled_ready",
                    "at": "2026-08-04T00:00:00+00:00",
                    "reason": "scheduled",
                    "checkpoint": None,
                }
            ],
        },
    }

    with pytest.raises(ConfigurationError) as status_error:
        transition_job_record(
            record,
            "dry_run_started",
            reason="stale worker",
            expected_status="scheduled_blocked",
        )
    with pytest.raises(ConfigurationError) as version_error:
        transition_job_record(
            record,
            "dry_run_started",
            reason="stale worker",
            expected_status="scheduled_ready",
            expected_state_version=1,
        )

    assert status_error.value.error_code == "final_chain_job_stale_transition"
    assert status_error.value.evidence == {"expected_status": "scheduled_blocked", "actual_status": "scheduled_ready"}
    assert version_error.value.error_code == "final_chain_job_stale_transition"
    assert version_error.value.evidence == {"expected_state_version": 1, "actual_state_version": 2}


def test_job_record_path_transition_cleans_lock_and_rejects_stale_version(tmp_path: Path) -> None:
    record_path = tmp_path / "job_record.json"
    record_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_job_record.v0.1",
                "job_id": "job",
                "created_at": "2026-08-04T00:00:00+00:00",
                "status": "scheduled_ready",
                "chain_id": "pdf_math",
                "record_path": "outputs/final_chain_runs/_control/jobs/job/job_record.json",
                "plan": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
                "request_snapshot": {
                    "workspace_contract": "relative_git_paths_only",
                    "absolute_paths_as_inputs": False,
                },
                "environment_snapshot": {},
                "lifecycle": {
                    "schema_version": "final_chain_job_lifecycle.v0.1",
                    "status": "scheduled_ready",
                    "state_version": 1,
                    "terminal": False,
                    "allowed_next_statuses": ["dry_run_started", "cancelled"],
                    "updated_at": "2026-08-04T00:00:00+00:00",
                    "history": [
                        {
                            "version": 1,
                            "status": "scheduled_ready",
                            "at": "2026-08-04T00:00:00+00:00",
                            "reason": "scheduled",
                            "checkpoint": None,
                        }
                    ],
                },
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    updated = transition_job_record_path(
        record_path,
        "dry_run_started",
        reason="first worker",
        expected_status="scheduled_ready",
        expected_state_version=1,
    )
    with pytest.raises(ConfigurationError) as stale_error:
        transition_job_record_path(
            record_path,
            "dry_run_passed",
            reason="stale worker",
            expected_status="scheduled_ready",
            expected_state_version=1,
        )

    final_record = json.loads(record_path.read_text(encoding="utf-8"))
    assert updated["status"] == "dry_run_started"
    assert updated["lifecycle"]["state_version"] == 2
    assert final_record["status"] == "dry_run_started"
    assert stale_error.value.error_code == "final_chain_job_stale_transition"
    assert not record_path.with_name(f".{record_path.name}.lock").exists()


def test_concurrent_job_record_path_transitions_allow_only_one_stale_checked_worker(tmp_path: Path) -> None:
    record_path = tmp_path / "job_record.json"
    record_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_job_record.v0.1",
                "job_id": "job",
                "created_at": "2026-08-04T00:00:00+00:00",
                "status": "scheduled_ready",
                "chain_id": "pdf_math",
                "record_path": "outputs/final_chain_runs/_control/jobs/job/job_record.json",
                "plan": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
                "request_snapshot": {
                    "workspace_contract": "relative_git_paths_only",
                    "absolute_paths_as_inputs": False,
                },
                "environment_snapshot": {},
                "lifecycle": {
                    "schema_version": "final_chain_job_lifecycle.v0.1",
                    "status": "scheduled_ready",
                    "state_version": 1,
                    "terminal": False,
                    "allowed_next_statuses": ["dry_run_started", "cancelled"],
                    "updated_at": "2026-08-04T00:00:00+00:00",
                    "history": [
                        {
                            "version": 1,
                            "status": "scheduled_ready",
                            "at": "2026-08-04T00:00:00+00:00",
                            "reason": "scheduled",
                            "checkpoint": None,
                        }
                    ],
                },
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
                "errors": [],
            }
        ),
        encoding="utf-8",
    )

    def worker(target_status: str) -> str:
        try:
            transition_job_record_path(
                record_path,
                target_status,
                reason=f"worker requested {target_status}",
                expected_status="scheduled_ready",
                expected_state_version=1,
            )
            return "ok"
        except ConfigurationError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ["dry_run_started", "cancelled"]))

    final_record = json.loads(record_path.read_text(encoding="utf-8"))
    assert results.count("ok") == 1
    assert results.count("final_chain_job_stale_transition") == 1
    assert final_record["status"] in {"dry_run_started", "cancelled"}
    assert final_record["lifecycle"]["state_version"] == 2
    assert validate_job_record(final_record)["ok"] is True
    assert not record_path.with_name(f".{record_path.name}.lock").exists()


def test_job_recovery_plan_allows_replacement_for_retryable_failed_dry_run() -> None:
    record = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {
                "version": 2,
                "status": "dry_run_started",
                "at": "2026-08-04T00:00:01+00:00",
                "reason": "adapter dry-run accepted",
                "checkpoint": None,
            },
            {
                "version": 3,
                "status": "dry_run_failed",
                "at": "2026-08-04T00:00:02+00:00",
                "reason": "transient worker EOF",
                "checkpoint": {"retryable": True, "artifact_ref": "outputs/final_chain_runs/job/error.json"},
            },
        ],
    )

    plan = build_job_recovery_plan(record, max_attempts=3)

    assert plan["schema_version"] == "final_chain_job_recovery_plan.v0.1"
    assert plan["action"] == "schedule_replacement_job"
    assert plan["reason"] == "latest_failure_is_retryable_and_attempt_budget_remains"
    assert plan["can_schedule_replacement_job"] is True
    assert plan["started_attempt_count"] == 1
    assert plan["latest_failure_retryable"] is True
    assert plan["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_job_recovery_plan_stops_when_retry_budget_is_exhausted() -> None:
    record = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {"version": 2, "status": "dry_run_started", "at": "2026-08-04T00:00:01+00:00", "reason": "try 1", "checkpoint": None},
            {"version": 3, "status": "dry_run_failed", "at": "2026-08-04T00:00:02+00:00", "reason": "try 1 failed", "checkpoint": {"retryable": True}},
            {"version": 4, "status": "dry_run_started", "at": "2026-08-04T00:00:03+00:00", "reason": "try 2", "checkpoint": None},
            {"version": 5, "status": "dry_run_failed", "at": "2026-08-04T00:00:04+00:00", "reason": "try 2 failed", "checkpoint": {"retryable": True}},
            {"version": 6, "status": "dry_run_started", "at": "2026-08-04T00:00:05+00:00", "reason": "try 3", "checkpoint": None},
            {"version": 7, "status": "dry_run_failed", "at": "2026-08-04T00:00:06+00:00", "reason": "try 3 failed", "checkpoint": {"retryable": True}},
        ],
    )

    plan = build_job_recovery_plan(record, max_attempts=3)

    assert plan["action"] == "manual_review_required"
    assert plan["reason"] == "retry_attempt_budget_exhausted"
    assert plan["can_schedule_replacement_job"] is False
    assert plan["started_attempt_count"] == 3


def test_job_recovery_plan_path_redacts_invalid_absolute_checkpoint(tmp_path: Path) -> None:
    record = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {
                "version": 2,
                "status": "dry_run_started",
                "at": "2026-08-04T00:00:01+00:00",
                "reason": "adapter dry-run accepted",
                "checkpoint": None,
            },
            {
                "version": 3,
                "status": "dry_run_failed",
                "at": "2026-08-04T00:00:02+00:00",
                "reason": "bad checkpoint",
                "checkpoint": {"retryable": True, "artifact_ref": str(tmp_path / "absolute.json")},
            },
        ],
    )
    record_path = tmp_path / "job_record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_job_recovery_plan_path(record_path)

    serialized = json.dumps(plan, ensure_ascii=False)
    assert plan["action"] == "manual_review_required"
    assert plan["reason"] == "job_record_validation_failed"
    assert plan["record_validation"]["ok"] is False
    assert "<absolute-path>" in serialized
    assert str(tmp_path) not in serialized


def test_schedule_replacement_chain_run_inherits_request_and_records_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tools").mkdir()
    (workspace / "tools" / "run.py").write_text("print('not imported')\n", encoding="utf-8")
    input_path = workspace / "input.pdf"
    input_path.write_text("pdf placeholder\n", encoding="utf-8")
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    original = schedule_chain_run(
        registry,
        ChainRunRequest(chain_id="pdf_math", input_path="input.pdf", output_root="outputs/final_chain_runs"),
        workspace_root=workspace,
    )
    started = transition_job_record(original, "dry_run_started", reason="worker accepted")
    failed = transition_job_record(
        started,
        "dry_run_failed",
        reason="transient EOF",
        checkpoint={"retryable": True, "artifact_ref": "outputs/final_chain_runs/job/error.json"},
    )

    replacement = schedule_replacement_chain_run(registry, failed, workspace_root=workspace, max_attempts=3)

    assert replacement["status"] == "scheduled_ready"
    assert replacement["job_id"] != original["job_id"]
    assert replacement["request_snapshot"]["input"]["path"] == "input.pdf"
    assert replacement["plan"]["input_path"] == "input.pdf"
    assert replacement["plan"]["output_root"] == "outputs/final_chain_runs"
    assert replacement["replacement"] == {
        "schema_version": "final_chain_replacement_job.v0.1",
        "parent_job_id": original["job_id"],
        "parent_chain_id": "pdf_math",
        "parent_state_version": 3,
        "attempt_number": 2,
        "max_attempts": 3,
        "recovery_reason": "latest_failure_is_retryable_and_attempt_budget_remains",
        "recovery_plan_schema": "final_chain_job_recovery_plan.v0.1",
    }
    assert replacement["record_validation"]["ok"] is True
    assert validate_job_record(replacement)["ok"] is True
    assert json.loads((workspace / replacement["record_path"]).read_text(encoding="utf-8"))["replacement"][
        "parent_job_id"
    ] == original["job_id"]
    assert str(workspace) not in json.dumps(replacement)


def test_schedule_replacement_chain_run_rejects_when_recovery_plan_disallows_retry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)
    failed = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {
                "version": 2,
                "status": "dry_run_started",
                "at": "2026-08-04T00:00:01+00:00",
                "reason": "worker accepted",
                "checkpoint": None,
            },
            {
                "version": 3,
                "status": "dry_run_failed",
                "at": "2026-08-04T00:00:02+00:00",
                "reason": "schema failure",
                "checkpoint": {"retryable": False},
            },
        ],
    )

    with pytest.raises(ConfigurationError) as error:
        schedule_replacement_chain_run(registry, failed, workspace_root=workspace, max_attempts=3)

    assert error.value.error_code == "final_chain_replacement_not_allowed"
    assert error.value.evidence["action"] == "manual_review_required"
    assert error.value.evidence["reason"] == "latest_failure_is_not_retryable"


def test_final_chain_control_cli_validates_job_record_contract(tmp_path: Path) -> None:
    record = {
        "schema_version": "final_chain_job_record.v0.1",
        "job_id": "job",
        "created_at": "2026-08-04T00:00:00+00:00",
        "status": "scheduled_ready",
        "chain_id": "pdf_math",
        "record_path": "outputs/final_chain_runs/_control/jobs/job/job_record.json",
        "plan": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
        "request_snapshot": {"workspace_contract": "relative_git_paths_only", "absolute_paths_as_inputs": False},
        "environment_snapshot": {},
        "lifecycle": {
            "schema_version": "final_chain_job_lifecycle.v0.1",
            "status": "scheduled_ready",
            "state_version": 1,
            "terminal": False,
            "allowed_next_statuses": ["dry_run_started", "cancelled"],
            "updated_at": "2026-08-04T00:00:00+00:00",
            "history": [
                {
                    "version": 1,
                    "status": "scheduled_ready",
                    "at": "2026-08-04T00:00:00+00:00",
                    "reason": "scheduled",
                    "checkpoint": None,
                }
            ],
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
        "errors": [],
    }
    record_path = tmp_path / "job_record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    valid_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "job-validate", "--record", str(record_path), "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert valid_completed.returncode == 0
    assert json.loads(valid_completed.stdout)["ok"] is True

    record["record_path"] = "D:\\unsafe\\job_record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    invalid_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "job-validate", "--record", str(record_path), "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert invalid_completed.returncode == 2
    payload = json.loads(invalid_completed.stdout)
    assert payload["ok"] is False
    assert "record_path_not_portable" in {error["code"] for error in payload["errors"]}
    assert "D:\\unsafe" not in json.dumps(payload)


def test_final_chain_control_cli_inspects_and_transitions_job_record(tmp_path: Path) -> None:
    record_path = tmp_path / "job_record.json"
    record_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_job_record.v0.1",
                "job_id": "job",
                "created_at": "2026-08-04T00:00:00+00:00",
                "status": "scheduled_ready",
                "chain_id": "pdf_math",
            }
        ),
        encoding="utf-8",
    )

    inspect_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "job-inspect", "--record", str(record_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    transition_completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "job-transition",
            "--record",
            str(record_path),
            "--status",
            "dry_run_started",
            "--reason",
            "cli smoke",
            "--expect-status",
            "scheduled_ready",
            "--expect-state-version",
            "1",
            "--with-checkpoint",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert inspect_completed.returncode == 0
    inspect_payload = json.loads(inspect_completed.stdout)
    assert inspect_payload["status"] == "scheduled_ready"
    assert inspect_payload["allowed_next_statuses"] == ["dry_run_started", "cancelled"]
    assert transition_completed.returncode == 0
    transition_payload = json.loads(transition_completed.stdout)
    assert transition_payload["status"] == "dry_run_started"
    assert transition_payload["lifecycle"]["history"][-1]["checkpoint"] == {"source": "final_chain_control_cli"}
    assert json.loads(record_path.read_text(encoding="utf-8"))["status"] == "dry_run_started"


def test_final_chain_control_cli_builds_job_recovery_plan(tmp_path: Path) -> None:
    record = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {
                "version": 2,
                "status": "dry_run_started",
                "at": "2026-08-04T00:00:01+00:00",
                "reason": "adapter dry-run accepted",
                "checkpoint": None,
            },
            {
                "version": 3,
                "status": "dry_run_failed",
                "at": "2026-08-04T00:00:02+00:00",
                "reason": "EOF from external worker",
                "checkpoint": {"retryable": True},
            },
        ],
    )
    record_path = tmp_path / "job_record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "job-recovery-plan",
            "--record",
            str(record_path),
            "--max-attempts",
            "3",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_job_recovery_plan.v0.1"
    assert payload["action"] == "schedule_replacement_job"
    assert payload["can_schedule_replacement_job"] is True
    assert payload["execution_contract"]["runtime_imported"] is False


def test_final_chain_control_cli_schedules_replacement_job(tmp_path: Path) -> None:
    record = _valid_job_record_with_history(
        "dry_run_failed",
        [
            {
                "version": 1,
                "status": "scheduled_ready",
                "at": "2026-08-04T00:00:00+00:00",
                "reason": "scheduled",
                "checkpoint": None,
            },
            {
                "version": 2,
                "status": "dry_run_started",
                "at": "2026-08-04T00:00:01+00:00",
                "reason": "adapter dry-run accepted",
                "checkpoint": None,
            },
            {
                "version": 3,
                "status": "dry_run_failed",
                "at": "2026-08-04T00:00:02+00:00",
                "reason": "EOF from external worker",
                "checkpoint": {"retryable": True},
            },
        ],
    )
    record["plan"]["input_path"] = "tests/fixtures/final_chain_samples/pdf_math_sample.pdf"
    record["plan"]["output_root"] = "outputs/final_chain_cli_replacements"
    record_path = tmp_path / "failed_job_record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "job-schedule-replacement",
            "--record",
            str(record_path),
            "--max-attempts",
            "3",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "scheduled_ready"
    assert payload["replacement"]["parent_job_id"] == "job"
    assert payload["replacement"]["attempt_number"] == 2
    assert payload["request_snapshot"]["input"]["path"] == "tests/fixtures/final_chain_samples/pdf_math_sample.pdf"
    assert payload["execution_contract"]["model_invoked"] is False
    assert str(tmp_path) not in serialized
    assert (ROOT / payload["record_path"]).is_file()


def test_final_chain_control_cli_reports_missing_job_record_as_json(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "job-inspect",
            "--record",
            str(tmp_path / "missing_job_record.json"),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_control_error.v0.1"
    assert payload["error"]["code"] == "final_chain_job_record_missing"
    assert payload["model_invoked"] is False


def test_environment_report_is_machine_readable_and_side_effect_free() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = inspect_registry_environments(registry, workspace_root=ROOT)

    assert report["schema_version"] == "final_chain_environment_report.v0.1"
    assert report["chain_count"] == 4
    assert report["model_invoked"] is False
    assert report["database_written"] is False
    assert report["runtime_imported"] is False
    assert report["business_secrets_read"] is False
    by_id = {item["chain_id"]: item for item in report["chains"]}
    assert by_id["pdf_math"]["checks"]["required_paths_present"] is True
    assert by_id["doc_math"]["status"] == "ready"
    assert by_id["doc_english"]["status"] == "ready"
    assert by_id["pdf_english"]["status"] == "ready"
    assert by_id["pdf_english"]["blocked_reasons"] == []


def test_environment_interaction_contract_is_external_orchestrator_safe() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = build_environment_interaction_contract(registry, workspace_root=ROOT)

    assert report["schema_version"] == "final_chain_environment_interaction_contract.v0.1"
    assert report["status"] == "pass"
    assert report["consumer_role"] == "external_orchestrator_or_java_backbone"
    assert report["ready_chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert report["blocked_chain_ids"] == []
    assert report["filesystem_contract"]["write_scope"] == ["outputs/"]
    assert report["filesystem_contract"]["absolute_paths_as_reproducible_inputs"] is False
    assert report["forbidden_side_effects"] == {
        "model_calls": True,
        "database_writes": True,
        "runtime_imports": True,
        "business_secret_reads": True,
    }
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["all_profiles_deny_model_calls"]["ok"] is True
    assert checks["blocked_profiles_fail_closed"]["value"] == []
    by_id = {item["chain_id"]: item for item in report["profiles"]}
    assert by_id["pdf_english"]["environment_gate"] == "ready_for_control_plane"
    assert by_id["pdf_math"]["environment_gate"] == "ready_for_control_plane"
    assert by_id["pdf_math"]["required_path_count"] == by_id["pdf_math"]["required_path_present_count"]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_adapter_contracts_forbid_runtime_side_effects_in_dry_run() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = inspect_adapter_contracts(registry)

    assert report["ok"] is True
    assert report["chain_count"] == 4
    for contract in report["contracts"]:
        assert contract["schema_version"] == "final_chain_adapter.v0.1"
        assert {"describe", "plan", "dry_run"}.issubset(contract["required_methods"])
        assert {"model_call", "database_write", "runtime_import", "business_secret_read"}.issubset(
            contract["forbidden_during_dry_run"]
        )
        assert contract["execution_contract"] == {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }


def test_final_chain_control_cli_env_check_and_adapter_contracts() -> None:
    env_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "env-check", "--chain-id", "pdf_english", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert env_completed.returncode == 0
    env_payload = json.loads(env_completed.stdout)
    assert env_payload["schema_version"] == "final_chain_environment_report.v0.1"
    assert env_payload["chain_count"] == 1
    assert env_payload["chains"][0]["chain_id"] == "pdf_english"
    assert env_payload["chains"][0]["status"] == "ready"

    env_contract_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "env-contract", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert env_contract_completed.returncode == 0
    env_contract_payload = json.loads(env_contract_completed.stdout)
    env_contract_serialized = json.dumps(env_contract_payload, ensure_ascii=False)
    assert env_contract_payload["schema_version"] == "final_chain_environment_interaction_contract.v0.1"
    assert env_contract_payload["blocked_chain_ids"] == []
    assert "D:\\" not in env_contract_serialized
    assert "C:\\" not in env_contract_serialized
    assert "/Users/" not in env_contract_serialized

    adapter_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "adapter-contracts", "--chain-id", "pdf_math", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert adapter_completed.returncode == 0
    adapter_payload = json.loads(adapter_completed.stdout)
    assert adapter_payload["ok"] is True
    assert adapter_payload["contracts"][0]["chain_id"] == "pdf_math"


def test_adapter_registry_covers_all_four_final_chains() -> None:
    registry = load_final_chain_registry(REGISTRY)

    adapters = build_final_chain_adapters(registry, workspace_root=ROOT)
    report = describe_adapters(registry, workspace_root=ROOT)

    assert set(adapters) == {"doc_math", "doc_english", "pdf_math", "pdf_english"}
    assert report["chain_count"] == 4
    assert report["model_invoked"] is False
    assert report["database_written"] is False
    assert report["runtime_imported"] is False
    by_id = {item["chain_id"]: item for item in report["descriptions"]}
    assert by_id["pdf_math"]["contract"]["required_methods"] == ["describe", "plan", "dry_run"]
    assert by_id["pdf_english"]["environment"]["status"] == "ready"


def test_adapter_dry_run_never_invokes_entrypoint_or_runtime(tmp_path: Path) -> None:
    registry = load_final_chain_registry(REGISTRY)
    adapter = build_final_chain_adapters(registry, workspace_root=ROOT)["pdf_math"]
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")
    request = ChainRunRequest(chain_id="pdf_math", input_path=str(sample), output_root="outputs/final_chain_runs")

    result = adapter.dry_run(request)

    assert result["schema_version"] == "final_chain_adapter_dry_run.v0.1"
    assert result["status"] == "dry_run_ready"
    assert result["adapter_invoked_entrypoint"] is False
    assert result["model_invoked"] is False
    assert result["database_written"] is False
    assert result["runtime_imported"] is False
    assert result["business_secrets_read"] is False
    assert result["plan"]["workspace_contract"] == "relative_git_paths_only"
    assert result["request_snapshot"]["input"]["path"] == "<outside-workspace>"
    assert str(tmp_path) not in json.dumps(result)


def test_adapter_dry_run_blocks_missing_input() -> None:
    registry = load_final_chain_registry(REGISTRY)
    adapter = build_final_chain_adapters(registry, workspace_root=ROOT)["pdf_math"]
    request = ChainRunRequest(chain_id="pdf_math", input_path="missing.pdf", output_root="outputs/final_chain_runs")

    result = adapter.dry_run(request)

    assert result["status"] == "dry_run_blocked"
    assert "input_path_present" in result["plan"]["blocked_reasons"]


def test_adapter_execution_preflight_exposes_unified_worker_contract(tmp_path: Path) -> None:
    registry = load_final_chain_registry(REGISTRY)
    adapter = build_final_chain_adapters(registry, workspace_root=ROOT)["pdf_math"]
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")
    request = ChainRunRequest(
        chain_id="pdf_math",
        input_path=str(sample),
        output_root="outputs/final_chain_runs",
    )

    result = adapter.execution_preflight(request)

    assert result["schema_version"] == "final_chain_execution_preflight.v0.1"
    assert result["status"] == "execution_preflight_blocked"
    assert result["adapter_api_version"] == "final_chain_adapter.v0.2"
    assert result["supported_job_statuses"] == list(FINAL_CHAIN_JOB_STATUSES)
    assert "standard_cli_contract_missing" in result["blocked_reasons"]
    assert result["command_contract"]["canonical_entrypoint"] == "tools/run_question_ingest_skill.py"
    assert result["command_contract"]["execute_now"] is False
    assert result["result_contract"]["schema_version"] == "final_chain_job_result.v0.1"
    assert result["adapter_invoked_entrypoint"] is False
    assert result["model_invoked"] is False
    assert result["database_written"] is False
    assert result["runtime_imported"] is False


def test_final_chain_control_cli_adapter_describe_and_dry_run(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")

    describe_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "adapter-describe", "--chain-id", "pdf_math"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert describe_completed.returncode == 0
    describe_payload = json.loads(describe_completed.stdout)
    assert describe_payload["chain_count"] == 1
    assert describe_payload["descriptions"][0]["chain_id"] == "pdf_math"

    dry_run_completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "adapter-dry-run",
            "--chain-id",
            "pdf_math",
            "--input",
            str(sample),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert dry_run_completed.returncode == 0
    dry_run_payload = json.loads(dry_run_completed.stdout)
    assert dry_run_payload["status"] == "dry_run_ready"
    assert dry_run_payload["adapter_invoked_entrypoint"] is False


def test_final_chain_control_cli_adapter_execution_preflight(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "adapter-execution-preflight",
            "--chain-id",
            "pdf_math",
            "--input",
            str(sample),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_execution_preflight.v0.1"
    assert payload["status"] == "execution_preflight_blocked"
    assert "standard_cli_contract_missing" in payload["blocked_reasons"]
    assert payload["adapter_invoked_entrypoint"] is False


def test_readiness_matrix_summarizes_four_chain_import_and_dry_run_gaps() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = build_readiness_matrix(registry, workspace_root=ROOT)

    assert report["schema_version"] == "final_chain_readiness_matrix.v0.1"
    assert report["chain_count"] == 4
    assert report["model_invoked"] is False
    assert report["database_written"] is False
    assert report["runtime_imported"] is False
    by_id = {item["chain_id"]: item for item in report["rows"]}
    assert by_id["pdf_math"]["readiness_tier"] == "environment_ready_input_needed"
    assert by_id["doc_math"]["readiness_tier"] == "environment_ready_input_needed"
    assert by_id["doc_english"]["readiness_tier"] == "environment_ready_input_needed"
    assert by_id["pdf_english"]["readiness_tier"] == "environment_ready_input_needed"
    assert "provide_existing_input_file_for_adapter_dry_run" in by_id["pdf_english"]["recommended_actions"]


def test_readiness_matrix_uses_sample_input_to_mark_adapter_dry_run_ready(tmp_path: Path) -> None:
    registry = load_final_chain_registry(REGISTRY)
    doc_math_sample = tmp_path / "doc_math.docx"
    doc_english_sample = tmp_path / "doc_english.docx"
    pdf_math_sample = tmp_path / "pdf_math.pdf"
    pdf_english_sample = tmp_path / "pdf_english.pdf"
    doc_math_sample.write_text("docx placeholder", encoding="utf-8")
    doc_english_sample.write_text("docx placeholder", encoding="utf-8")
    pdf_math_sample.write_text("pdf placeholder", encoding="utf-8")
    pdf_english_sample.write_text("pdf placeholder", encoding="utf-8")

    report = build_readiness_matrix(
        registry,
        workspace_root=ROOT,
        sample_inputs={
            "doc_math": str(doc_math_sample),
            "doc_english": str(doc_english_sample),
            "pdf_math": str(pdf_math_sample),
            "pdf_english": str(pdf_english_sample),
        },
    )

    by_id = {item["chain_id"]: item for item in report["rows"]}
    assert report["ready_for_adapter_dry_run_count"] == 4
    assert by_id["doc_math"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["doc_english"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["pdf_math"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["pdf_math"]["adapter_dry_run_status"] == "dry_run_ready"
    assert by_id["pdf_english"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["pdf_math"]["recommended_actions"] == [
        "wire_real_adapter_dry_run_without_model_or_database_side_effects"
    ]


def test_final_chain_control_cli_readiness_matrix(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "readiness-matrix",
            "--chain-id",
            "pdf_math",
            "--sample-input",
            f"pdf_math={sample}",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_readiness_matrix.v0.1"
    assert payload["chain_count"] == 1
    assert payload["rows"][0]["chain_id"] == "pdf_math"
    assert payload["rows"][0]["readiness_tier"] == "ready_for_adapter_dry_run"


def test_final_chain_control_cli_queues_four_chain_batch_without_execution() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "queue",
            "--sample-input",
            "doc_math=tests/fixtures/final_chain_samples/doc_math_sample.docx",
            "--sample-input",
            "doc_english=tests/fixtures/final_chain_samples/doc_english_sample.docx",
            "--sample-input",
            "pdf_math=tests/fixtures/final_chain_samples/pdf_math_sample.pdf",
            "--sample-input",
            "pdf_english=tests/fixtures/final_chain_samples/pdf_english_sample.pdf",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "final_chain_batch_queue_report.v0.1"
    assert payload["status"] == "pass"
    assert payload["scheduled_ready_count"] == 4
    assert payload["scheduled_blocked_count"] == 0
    assert payload["rejected_count"] == 0
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_final_chain_control_dashboard_groups_chains_by_scheduling_lane() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = build_final_chain_control_dashboard(registry, workspace_root=ROOT)

    assert report["schema_version"] == "final_chain_control_dashboard.v0.1"
    assert report["workspace_contract"] == "relative_git_paths_only"
    assert report["absolute_paths_as_inputs"] is False
    assert report["contract_ok"] is True
    assert report["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    by_id = {item["chain_id"]: item for item in report["rows"]}
    assert by_id["doc_math"]["lane"] == "needs_sample_input"
    assert by_id["doc_english"]["lane"] == "needs_sample_input"
    assert by_id["pdf_math"]["lane"] == "needs_sample_input"
    assert by_id["pdf_english"]["lane"] == "needs_sample_input"
    assert report["job_lifecycle_policy"]["allowed_transitions"]["scheduled_ready"] == [
        "dry_run_started",
        "cancelled",
    ]


def test_final_chain_control_contract_is_external_orchestrator_safe() -> None:
    registry = load_final_chain_registry(REGISTRY)

    report = build_final_chain_control_contract(registry)

    assert report["schema_version"] == "final_chain_control_contract.v0.1"
    assert report["consumer_role"] == "external_orchestrator_or_java_backbone"
    assert report["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert report["control_plane_contract"]["dry_run_only"] is True
    assert report["control_plane_contract"]["execute_intent_blocked"] is True
    assert report["control_plane_contract"]["scheduler_writes_only_under"] == "outputs/"
    assert all(report["forbidden_side_effects"].values())
    assert report["commands"]["contract"] == "tools/final_chain_control.py contract --json"
    assert report["commands"]["env_contract"] == "tools/final_chain_control.py env-contract --json"
    assert report["commands"]["queue"] == "tools/final_chain_control.py queue --sample-input <chain_id=path> --json"
    assert report["commands"]["job_validate"] == (
        "tools/final_chain_control.py job-validate --record <relative_record_path> --json"
    )
    assert report["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_final_chain_control_contract_report_has_no_absolute_paths() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_control_contract.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "final_chain_control_contract.v0.1"
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_final_chain_environment_contract_report_has_no_absolute_paths() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_environment_contract.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "final_chain_environment_interaction_contract.v0.1"
    assert payload["status"] == "pass"
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_final_chain_control_cli_contract_is_portable() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "contract", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "final_chain_control_contract.v0.1"
    assert payload["control_plane_contract"]["dry_run_only"] is True
    assert payload["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_final_chain_control_cli_dashboard_filters_one_chain(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_text("pdf placeholder", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/final_chain_control.py",
            "dashboard",
            "--chain-id",
            "pdf_math",
            "--sample-input",
            f"pdf_math={sample}",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_control_dashboard.v0.1"
    assert payload["chain_count"] == 1
    assert payload["lane_counts"] == {"adapter_dry_run_ready": 1}
    assert payload["rows"][0]["chain_id"] == "pdf_math"


def test_ready_sample_report_runs_four_control_adapters_without_side_effects() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_ready_sample_report.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "final_chain_ready_sample_dry_run_report.v0.1"
    assert payload["workspace_contract"] == "relative_git_paths_only"
    assert payload["absolute_paths_as_inputs"] is False
    assert payload["ready_for_adapter_dry_run_count"] == 4
    assert payload["pdf_english_recovery_status"] == "raw_pdf_promotion_passed_java_shell_admission"
    assert {row["chain_id"] for row in payload["rows"]} == {"doc_math", "doc_english", "pdf_math", "pdf_english"}
    for row in payload["rows"]:
        assert row["sample_input"].startswith("tests/fixtures/final_chain_samples/")
        assert row["adapter_dry_run_status"] == "dry_run_ready"
        assert row["schedule_status"] == "scheduled_ready"
        assert row["job_record_self_validation_ok"] is True
        assert row["job_record_self_validation_error_count"] == 0
        assert row["job_record_validation_ok"] is True
        assert row["job_record_validation_error_count"] == 0
        assert row["adapter_invoked_entrypoint"] is False
        assert row["execution_contract"] == {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }


def test_batch_queue_report_schedules_four_chain_control_records() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_batch_queue_report.py"],
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
    assert payload["schema_version"] == "final_chain_batch_queue_report.v0.1"
    assert payload["status"] == "pass"
    assert payload["chain_count"] == 4
    assert payload["scheduled_ready_count"] == 4
    assert payload["scheduled_blocked_count"] == 0
    assert checks["batch_covers_four_registered_chains"]["ok"] is True
    assert checks["four_ready_jobs_scheduled"]["ok"] is True
    assert checks["pdf_english_is_scheduled_ready_after_raw_pdf_promotion"]["ok"] is True
    assert checks["all_job_records_validate"]["ok"] is True
    assert checks["all_job_records_written_under_outputs"]["ok"] is True
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_batch_queue_report_validator_accepts_sealed_queue_report() -> None:
    batch = subprocess.run(
        [sys.executable, "tools/build_final_chain_batch_queue_report.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert batch.returncode == 0

    completed = subprocess.run(
        [sys.executable, "tools/validate_final_chain_batch_queue_report.py"],
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
    assert payload["schema_version"] == "final_chain_batch_queue_validation.v0.1"
    assert payload["status"] == "pass"
    assert payload["batch_report_path"] == "docs/reports/final_chain_batch_queue_20260804.json"
    assert checks["batch_report_covers_exact_four_final_chains"]["ok"] is True
    assert checks["batch_queue_status_split_is_expected"]["ok"] is True
    assert checks["pdf_english_schedules_ready_after_raw_pdf_promotion"]["ok"] is True
    assert checks["job_record_contract_paths_are_stable_and_under_outputs"]["ok"] is True
    assert checks["job_record_validations_are_clean"]["ok"] is True
    assert checks["batch_report_contains_no_absolute_paths"]["ok"] is True
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_batch_queue_report_validator_rejects_tampered_queue_report() -> None:
    from tools.validate_final_chain_batch_queue_report import _build_checks

    tampered = {
        "schema_version": "final_chain_batch_queue_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass",
        "chain_count": 4,
        "scheduled_ready_count": 4,
        "scheduled_blocked_count": 0,
        "rejected_count": 0,
        "rows": [
            {
                "chain_id": "doc_math",
                "schedule_status": "scheduled_ready",
                "plan_status": "ready",
                "record_path": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_path_contract": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_validation_ok": True,
                "record_validation_error_count": 0,
                "self_validation_ok": True,
                "self_validation_error_count": 0,
                "blocked_reasons": [],
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
            },
            {
                "chain_id": "doc_english",
                "schedule_status": "scheduled_ready",
                "plan_status": "ready",
                "record_path": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_path_contract": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_validation_ok": True,
                "record_validation_error_count": 0,
                "self_validation_ok": True,
                "self_validation_error_count": 0,
                "blocked_reasons": [],
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
            },
            {
                "chain_id": "pdf_math",
                "schedule_status": "scheduled_ready",
                "plan_status": "ready",
                "record_path": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_path_contract": "outputs/final_chain_batch_queue/_control/jobs/<generated>/job_record.json",
                "record_validation_ok": True,
                "record_validation_error_count": 0,
                "self_validation_ok": True,
                "self_validation_error_count": 0,
                "blocked_reasons": [],
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
            },
            {
                "chain_id": "pdf_english",
                "schedule_status": "scheduled_ready",
                "plan_status": "ready",
                "record_path": "D:\\unsafe\\job_record.json",
                "record_path_contract": "D:\\unsafe\\job_record.json",
                "record_validation_ok": True,
                "record_validation_error_count": 0,
                "self_validation_ok": True,
                "self_validation_error_count": 0,
                "blocked_reasons": [],
                "execution_contract": {
                    "model_invoked": False,
                    "database_written": False,
                    "runtime_imported": False,
                    "business_secrets_read": False,
                },
            },
        ],
        "checks": [
            {"name": "batch_covers_four_registered_chains", "ok": True},
            {"name": "three_ready_jobs_scheduled", "ok": True},
            {"name": "pdf_english_is_scheduled_blocked", "ok": True},
            {"name": "no_rejected_jobs", "ok": True},
            {"name": "all_job_records_validate", "ok": True},
            {"name": "all_job_records_written_under_outputs", "ok": True},
            {"name": "no_runtime_side_effects_reported", "ok": True},
        ],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }

    checks = {item["name"]: item for item in _build_checks(tampered)}
    assert checks["batch_queue_status_split_is_expected"]["ok"] is True
    assert checks["pdf_english_schedules_ready_after_raw_pdf_promotion"]["ok"] is True
    assert checks["batch_report_checks_pass"]["ok"] is False
    assert checks["job_record_contract_paths_are_stable_and_under_outputs"]["ok"] is False
    assert checks["batch_report_contains_no_absolute_paths"]["ok"] is False


def test_orchestrator_handshake_report_summarizes_external_control_contract() -> None:
    batch = subprocess.run(
        [sys.executable, "tools/build_final_chain_batch_queue_report.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert batch.returncode == 0
    batch_validation = subprocess.run(
        [sys.executable, "tools/validate_final_chain_batch_queue_report.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert batch_validation.returncode == 0

    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_orchestrator_handshake.py"],
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
    assert payload["schema_version"] == "final_chain_orchestrator_handshake.v0.1"
    assert payload["status"] == "pass"
    assert payload["consumer_role"] == "external_orchestrator_or_java_backbone"
    assert payload["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["ready_chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["blocked_chain_ids"] == []
    assert payload["admission_policy"]["pdf_english"]["java_shell_admission"] == "allowed_after_raw_pdf_promotion"
    assert payload["admission_policy"]["pdf_english"]["model_execution_default_enabled"] is False
    assert payload["commands"]["queue"] == "tools/final_chain_control.py queue --sample-input <chain_id=path> --json"
    assert checks["required_commands_are_declared"]["ok"] is True
    assert checks["filesystem_contract_is_outputs_only"]["ok"] is True
    assert checks["job_lifecycle_blocks_scheduled_blocked_start"]["ok"] is True
    assert checks["batch_queue_validation_passes"]["ok"] is True
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_orchestrator_handshake_validator_accepts_sealed_handshake() -> None:
    handshake = subprocess.run(
        [sys.executable, "tools/build_final_chain_orchestrator_handshake.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert handshake.returncode == 0

    completed = subprocess.run(
        [sys.executable, "tools/validate_final_chain_orchestrator_handshake.py"],
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
    assert payload["schema_version"] == "final_chain_orchestrator_handshake_validation.v0.1"
    assert payload["status"] == "pass"
    assert checks["external_orchestrator_role_is_explicit"]["ok"] is True
    assert checks["chain_split_matches_final_chain_contract"]["ok"] is True
    assert checks["required_command_sequence_is_stable"]["ok"] is True
    assert checks["admission_policy_keeps_pdf_english_non_executing"]["ok"] is True
    assert checks["source_reports_are_relative_and_present"]["ok"] is True
    assert checks["handshake_contains_no_absolute_paths"]["ok"] is True
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_orchestrator_handshake_validator_rejects_tampered_handshake() -> None:
    from tools.validate_final_chain_orchestrator_handshake import _build_checks

    tampered = {
        "schema_version": "final_chain_orchestrator_handshake.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass",
        "consumer_role": "external_orchestrator_or_java_backbone",
        "chain_ids": ["doc_math", "doc_english", "pdf_math", "pdf_english"],
        "ready_chain_ids": ["doc_math", "doc_english", "pdf_math", "pdf_english"],
        "blocked_chain_ids": [],
        "required_command_sequence": ["contract", "queue"],
        "commands": {
            "contract": "tools/final_chain_control.py contract --json",
            "queue": "D:\\unsafe\\queue.exe",
        },
        "filesystem_contract": {
            "read_scope": "registered_relative_paths_only",
            "write_scope": ["config/"],
            "absolute_paths_as_reproducible_inputs": False,
        },
        "job_lifecycle_policy": {
            "allowed_transitions": {
                "scheduled_ready": ["dry_run_started", "cancelled"],
                "scheduled_blocked": ["dry_run_started"],
            }
        },
        "admission_policy": {
            "pdf_english": {
                "expected_status": "scheduled_ready",
                "environment_gate": "ready_for_control_plane",
                "java_shell_admission": "allowed_after_raw_pdf_promotion",
                "model_execution_default_enabled": True,
                "runtime_import_default_enabled": False,
                "database_write_default_enabled": False,
            }
        },
        "source_reports": {
            "control_contract": "docs/reports/final_chain_control_contract_20260804.json",
            "environment_contract": "docs/reports/final_chain_environment_contract_20260804.json",
            "batch_queue_validation": "D:\\unsafe\\batch.json",
        },
        "checks": [{"name": "batch_queue_validation_passes", "ok": True}],
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }

    checks = {item["name"]: item for item in _build_checks(tampered)}
    assert checks["chain_split_matches_final_chain_contract"]["ok"] is True
    assert checks["required_command_sequence_is_stable"]["ok"] is False
    assert checks["command_map_uses_legacy_cli_only"]["ok"] is False
    assert checks["admission_policy_keeps_pdf_english_non_executing"]["ok"] is False
    assert checks["filesystem_contract_limits_writes_to_outputs"]["ok"] is False
    assert checks["job_lifecycle_policy_blocks_scheduled_blocked_start"]["ok"] is False
    assert checks["source_reports_are_relative_and_present"]["ok"] is False
    assert checks["handshake_contains_no_absolute_paths"]["ok"] is False


def test_pdf_english_recovery_validator_accepts_fresh_rebuild_manifest() -> None:
    rebuilt = subprocess.run(
        [
            sys.executable,
            "tools/build_pdf_english_graph_first_rebuild_smoke.py",
            "--source-manifest",
            "config/english_text_first_graph_first/foundation_rebuild_sources.json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    completed = subprocess.run(
        [sys.executable, "tools/validate_pdf_english_recovery.py", "--require-ready"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "pdf_english_recovery_validation.v0.1"
    assert payload["status"] == "ready_for_manifest_gate"
    assert payload["required_manifest_check_failures"] == []
    assert payload["smoke_artifacts"]["source"] == "active_manifest_fresh_smoke_artifacts"
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_pdf_english_recovery_intake_accepts_current_fresh_candidate() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/validate_pdf_english_recovery_intake.py", "--require-ready"],
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
    assert payload["schema_version"] == "pdf_english_recovery_intake_validation.v0.1"
    assert payload["status"] == "candidate_ready_for_quarantine_import"
    assert payload["candidate_root_contract"]["candidate_label"] == "current_cleanroom_workspace"
    assert checks["active_manifest_present"]["ok"] is True
    assert checks["manifest_checker_present"]["ok"] is True
    assert checks["smoke_zip_present"]["ok"] is True
    assert checks["smoke_dir_present"]["ok"] is True
    assert checks["smoke_zip_valid"]["ok"] is True
    assert payload["required_check_failures"] == []
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_pdf_english_recovery_intake_accepts_isolated_candidate_without_path_leak(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    manifest = candidate / "config" / "english_text_first_graph_first" / "active_manifest.json"
    checker = candidate / "tools" / "english_text_first_graph_first_manifest_check.py"
    smoke_root = candidate / "outputs" / "english_text_first_graph_first"
    smoke_dir = smoke_root / "final_chain_smoke_20260728"
    smoke_zip = smoke_root / "final_chain_smoke_20260728.zip"
    manifest.parent.mkdir(parents=True)
    checker.parent.mkdir(parents=True)
    smoke_dir.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "pipeline_name": "english_text_first_graph_first",
                "allow_only_manifest_runs": True,
                "forbid_timestamp_latest_selection": True,
                "runs": {
                    "reading": "reading_run",
                    "grammar": "grammar_run",
                    "writing": "writing_run",
                    "cloze": "cloze_run",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    checker.write_text("print('english_text_first_graph_first_manifest_valid')\n", encoding="utf-8")
    (smoke_dir / "summary.json").write_text('{"status": "pass"}\n', encoding="utf-8")
    with zipfile.ZipFile(smoke_zip, "w") as archive:
        archive.write(smoke_dir / "summary.json", "summary.json")

    from tools.validate_pdf_english_recovery_intake import build_report

    payload = build_report(candidate)
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["status"] == "candidate_ready_for_quarantine_import"
    assert payload["candidate_root_contract"]["candidate_label"] == "provided_candidate_root"
    assert payload["candidate_root_contract"]["scope"] == "external_candidate_redacted"
    assert checks["pipeline_name_matches"]["ok"] is True
    assert checks["four_branch_runs_declared"]["ok"] is True
    assert checks["manifest_checker_present"]["ok"] is True
    assert checks["smoke_zip_valid"]["ok"] is True
    assert checks["smoke_dir_nonempty"]["ok"] is True
    assert str(tmp_path) not in serialized
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_pdf_english_recovery_source_audit_uses_labels_without_absolute_paths() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_pdf_english_recovery_source_audit.py",
            "--source-root",
            "repository_head=.",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "pdf_english_manifest_recovery_audit.v0.1"
    assert payload["source_audit_status"] == "fresh_rebuild_candidate_found"
    assert payload["recovery_status"] == "fresh_rebuild_candidate_found"
    assert payload["importable_source_labels"] == ["repository_head"]
    assert payload["searched_location_labels"] == ["repository_head"]
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def test_final_chain_ops_health_seals_operator_cli_surface() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_ops_health.py"],
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
    assert payload["schema_version"] == "final_chain_ops_health.v0.1"
    assert payload["status"] == "pass"
    assert payload["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["ready_chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["blocked_chain_ids"] == []
    assert payload["missing_npm_scripts"] == []
    assert payload["pdf_english_intake_status"] == "candidate_ready_for_quarantine_import"
    assert payload["pdf_english_raw_pdf_promotion_status"] == "pass"
    assert payload["pdf_english_java_shell_admission_allowed"] is True
    assert checks["four_final_chains_split_is_stable"]["ok"] is True
    assert checks["control_cli_commands_declared"]["ok"] is True
    assert checks["npm_operator_scripts_expose_control_surface"]["ok"] is True
    assert checks["job_recovery_and_replacement_are_non_executing"]["ok"] is True
    assert checks["job_transition_guard_is_locked_and_versioned"]["ok"] is True
    assert checks["filesystem_and_runtime_policy_are_closed"]["ok"] is True
    assert checks["dashboard_lanes_match_current_recovery_state"]["ok"] is True
    assert checks["pdf_english_intake_gate_has_fresh_candidate"]["ok"] is True
    assert checks["pdf_english_raw_pdf_promotion_admits_java_shell_without_model_execution"]["ok"] is True
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_final_chain_execution_gap_report_is_machine_readable_and_fail_closed() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_final_chain_execution_gap_report.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == "final_chain_execution_gap_report.v0.1"
    assert payload["status"] == "blocked_missing_execution_contracts"
    assert payload["continuous_production_ready"] is False
    assert payload["chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["execution_preflight_ready_count"] == 0
    assert payload["execution_preflight_blocked_count"] == 4
    assert "standard_cli_contract_missing" in payload["missing_for_continuous_production"]
    assert "database_queue_contract_missing" in payload["missing_for_continuous_production"]
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized
    by_id = {row["chain_id"]: row for row in payload["rows"]}
    assert by_id["pdf_math"]["plan_status"] == "ready"
    assert by_id["pdf_english"]["plan_status"] == "ready"
    assert by_id["pdf_math"]["adapter_invoked_entrypoint"] is False


def test_final_chain_ops_gate_includes_pdf_english_recovery_validation() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/run_final_chain_ops_gate.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert payload["status"] == "pass"
    assert payload["control_contract_schema"] == "final_chain_control_contract.v0.1"
    assert payload["environment_contract_schema"] == "final_chain_environment_interaction_contract.v0.1"
    assert payload["environment_ready_chain_ids"] == ["doc_math", "doc_english", "pdf_math", "pdf_english"]
    assert payload["environment_blocked_chain_ids"] == []
    assert payload["batch_queue_schema"] == "final_chain_batch_queue_report.v0.1"
    assert payload["batch_queue_validation_schema"] == "final_chain_batch_queue_validation.v0.1"
    assert payload["orchestrator_handshake_schema"] == "final_chain_orchestrator_handshake.v0.1"
    assert payload["orchestrator_handshake_validation_schema"] == "final_chain_orchestrator_handshake_validation.v0.1"
    assert payload["ops_health_schema"] == "final_chain_ops_health.v0.1"
    assert payload["batch_queue_ready_count"] == 4
    assert payload["batch_queue_blocked_count"] == 0
    assert payload["pdf_english_recovery_validation_status"] == "ready_for_manifest_gate"
    assert payload["pdf_english_recovery_source_audit_status"] == "fresh_rebuild_candidate_found"
    assert payload["pdf_english_recovery_intake_status"] == "candidate_ready_for_quarantine_import"
    assert payload["pdf_english_raw_pdf_promotion_status"] == "pass"
    assert payload["pdf_english_java_shell_admission_allowed"] is True
    assert checks["pdf_english_recovery_validator_ready_for_manifest_gate"]["ok"] is True
    assert checks["pdf_english_recovery_four_branch_manifest_declared"]["ok"] is True
    assert checks["pdf_english_recovery_source_audit_has_fresh_candidate"]["ok"] is True
    assert checks["pdf_english_recovery_intake_candidate_ready"]["ok"] is True
    assert checks["pdf_english_recovery_intake_manifest_and_smoke_present"]["ok"] is True
    assert checks["pdf_english_raw_pdf_promotion_passes"]["ok"] is True
    assert checks["final_chain_ops_health_passes"]["ok"] is True
    assert checks["ready_sample_job_records_validate"]["ok"] is True
    assert checks["batch_queue_covers_four_chains"]["ok"] is True
    assert checks["batch_queue_schedules_four_ready_zero_blocked"]["ok"] is True
    assert checks["batch_queue_job_records_validate"]["ok"] is True
    assert checks["batch_queue_report_validation_passes"]["ok"] is True
    assert checks["orchestrator_handshake_passes"]["ok"] is True
    assert checks["orchestrator_handshake_validation_passes"]["ok"] is True
    assert checks["environment_contract_passes"]["ok"] is True
    assert checks["environment_contract_covers_four_profiles"]["ok"] is True
    assert checks["environment_contract_admits_four_chains_to_control_plane"]["ok"] is True
    assert checks["environment_contract_limits_writes_to_outputs"]["ok"] is True
    assert checks["control_contract_is_dry_run_only"]["ok"] is True
    assert checks["control_contract_covers_four_chains"]["ok"] is True
    assert checks["control_contract_declares_non_executing_recovery_plan"]["ok"] is True


def test_cleanroom_hardening_manifest_seals_current_gate_outputs() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_cleanroom_hardening_manifest.py"],
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
    assert payload["schema_version"] == "cleanroom_hardening_manifest.v0.1"
    assert payload["status"] == "pass"
    assert "foundation_artifact_atomicity_and_model_checkpoint_guard" in payload["sealed_scopes"]
    assert "final_chain_registry_control_contract_environment_contract_and_scheduler" in payload["sealed_scopes"]
    assert "pdf_english_raw_pdf_graph_first_java_shell_admission" in payload["sealed_scopes"]
    assert "precleanup_archive_safety_and_worktree_compartment_guard" in payload["sealed_scopes"]
    assert checks["required_reports_present"]["ok"] is True
    assert payload["reports"]["final_chain_batch_queue"]["status"] == "pass"
    assert payload["reports"]["final_chain_batch_queue_validation"]["status"] == "pass"
    assert payload["reports"]["final_chain_orchestrator_handshake"]["status"] == "pass"
    assert payload["reports"]["final_chain_orchestrator_handshake_validation"]["status"] == "pass"
    assert payload["reports"]["final_chain_ops_health"]["status"] == "pass"
    assert payload["reports"]["pdf_english_recovery_intake_validation"]["status"] == "candidate_ready_for_quarantine_import"
    assert payload["reports"]["pdf_english_rebuild_decision"]["status"] == "rebuild_track_allowed"
    assert payload["reports"]["pdf_english_rebuild_source_import"]["status"] == "pass"
    assert payload["reports"]["pdf_english_raw_pdf_promotion"]["status"] == "pass"
    assert checks["final_chain_ops_covers_four_chains"]["ok"] is True
    assert checks["final_chain_job_records_self_and_external_validated"]["ok"] is True
    assert checks["pdf_english_fresh_rebuild_candidate_is_sealed"]["ok"] is True
    assert checks["pdf_english_recovery_intake_gate_is_sealed"]["ok"] is True
    assert checks["pdf_english_rebuild_track_is_explicit"]["ok"] is True
    assert checks["pdf_english_rebuild_source_import_is_sealed"]["ok"] is True
    assert checks["pdf_english_raw_pdf_promotion_is_sealed"]["ok"] is True
    assert checks["final_chain_ops_health_is_sealed"]["ok"] is True
    assert payload["known_blockers"] == [
        {
            "scope": "continuous_production_worker",
            "status": "java_orchestrator_worker_db_contract_not_implemented",
            "guard": "external_backbone_required_for_unattended_batch_processing",
            "allowed_behavior": "control_plane_dry_run_and_queue_only",
            "legacy_artifact_wait_required": False,
            "safe_boundary": "no_model_db_runtime_execution_without_explicit_worker_contract",
        }
    ]
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_cleanroom_hardening_manifest_validator_accepts_sealed_manifest() -> None:
    manifest = subprocess.run(
        [sys.executable, "tools/build_cleanroom_hardening_manifest.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert manifest.returncode == 0

    completed = subprocess.run(
        [sys.executable, "tools/validate_cleanroom_hardening_manifest.py"],
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
    assert payload["schema_version"] == "cleanroom_hardening_manifest_validation.v0.1"
    assert payload["status"] == "pass"
    assert payload["manifest_path"] == "docs/reports/cleanroom_hardening_manifest_20260804.json"
    assert checks["manifest_schema_contract_matches"]["ok"] is True
    assert checks["required_report_records_present"]["ok"] is True
    assert checks["report_paths_are_relative_and_existing"]["ok"] is True
    assert checks["required_manifest_checks_pass"]["ok"] is True
    assert checks["known_continuous_production_blocker_is_non_executing"]["ok"] is True
    assert checks["execution_contract_has_no_runtime_side_effects"]["ok"] is True
    assert checks["manifest_contains_no_absolute_paths"]["ok"] is True
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_pdf_english_rebuild_decision_keeps_old_identity_closed_but_allows_rebuild() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_pdf_english_rebuild_decision.py",
            "--source-root",
            "repository_head=.",
        ],
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
    assert payload["schema_version"] == "pdf_english_rebuild_decision.v0.1"
    assert payload["status"] == "rebuild_track_allowed"
    assert payload["legacy_artifact_wait_required"] is False
    assert payload["rebuild_track_allowed"] is True
    assert payload["ready_claim_allowed"] is False
    assert payload["old_identity_claim_allowed"] is False
    assert checks["fresh_rebuild_candidate_replaces_missing_legacy_artifacts"]["ok"] is True
    assert checks["cleanroom_v05_rebuild_scaffold_present"]["ok"] is True
    assert checks["old_local_graph_first_source_code_available_if_present"]["ok"] is True
    assert checks["portable_regression_passes_without_model_or_runtime"]["ok"] is True
    assert checks["user_supplied_downstream_review_evidence_if_present"]["ok"] is True
    assert checks["cleanroom_graph_first_source_import_is_sealed"]["ok"] is True
    assert checks["fresh_rebuild_smoke_manifest_gate_passes"]["ok"] is True
    assert checks["raw_pdf_graph_first_promotion_passes"]["ok"] is True
    assert "cleanroom_import_of_required_graph_first_source_files" in payload["completed_rebuild_evidence"]
    assert "cleanroom_import_of_required_graph_first_source_files" not in payload["required_promotion_evidence"]
    assert "new_active_manifest_generated_from_fresh_rebuild_outputs" in payload["completed_rebuild_evidence"]
    assert "raw_pdf_graph_first_promotion_passes_for_java_shell_admission" in payload["completed_rebuild_evidence"]
    assert "java_worker_and_database_contract_before_unattended_production_ready_claim" in payload["required_promotion_evidence"]
    assert "do_not_synthesize_old_active_manifest" in payload["unsafe_actions"]
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


@pytest.mark.parametrize(
    ("tool", "required_option"),
    [
        ("tools/build_pdf_english_graph_first_rebuild_smoke.py", "--source-manifest"),
        ("tools/build_pdf_english_rebuild_decision.py", "--source-root"),
        ("tools/build_pdf_english_recovery_source_audit.py", "--source-root"),
        ("tools/import_pdf_english_rebuild_sources.py", "--source-root"),
    ],
)
def test_pdf_english_recovery_tools_fail_closed_without_explicit_input(
    tool: str,
    required_option: str,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "must_not_be_scanned"
    fake_home.mkdir()
    completed = subprocess.run(
        [sys.executable, tool],
        cwd=ROOT,
        env={**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert required_option in completed.stderr
    assert str(fake_home) not in completed.stdout + completed.stderr


def test_pdf_english_foundation_source_manifest_is_hash_controlled_and_non_production() -> None:
    path = ROOT / "config/english_text_first_graph_first/foundation_rebuild_sources.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["source_kind"] == "repository_controlled_foundation_fixture"
    assert payload["scope"] == "final_chain_foundation_integration_only"
    assert payload["production_evidence"] is False
    assert payload["production_readiness_status"] == "BLOCKED"
    assert set(payload["branches"]) == {"reading", "writing", "grammar", "cloze"}
    assert all(record["sha256"] for branch in payload["branches"].values() for record in branch["page_files"])


def test_pdf_english_user_zip_intake_classifies_downstream_review_evidence(tmp_path: Path) -> None:
    from tools.build_pdf_english_user_zip_intake import build_report

    zips = [
        _write_review_zip(tmp_path / "en_reading_downstream_fixed_20260728.zip", "English_reading_downstream_fixed"),
        _write_review_zip(tmp_path / "en_writing_downstream_fixed_20260728.zip", "English_writing_downstream_fixed"),
        _write_review_zip(tmp_path / "en_grammar_downstream_fixed_20260728.zip", "English_grammar_downstream_fixed"),
        _write_review_zip(tmp_path / "en_cloze_gloss_end_3cases_20260728_review_v2.zip", "完形填空选项释义后置 3题回归"),
        _write_doc_math_review_zip(tmp_path / "doc1_triangles__side_by_side_filtered_v02.zip"),
    ]

    payload = build_report(zips)
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = {item["name"]: item for item in payload["checks"]}

    assert payload["schema_version"] == "pdf_english_user_zip_intake.v0.1"
    assert payload["status"] == "downstream_review_evidence_received"
    assert payload["received_branch_evidence"] == ["cloze", "grammar", "reading", "writing"]
    assert payload["non_pdf_english_zip_count"] == 1
    assert payload["canonical_recovery_artifacts_present"] is False
    assert payload["legacy_artifact_recovery_ready"] is False
    assert payload["rebuild_evidence_available"] is True
    assert payload["ready_claim_allowed"] is False
    assert payload["old_identity_claim_allowed"] is False
    assert checks["four_pdf_english_branch_review_packages_present"]["ok"] is True
    assert checks["no_zip_contains_canonical_active_manifest"]["ok"] is True
    assert checks["no_zip_contains_final_chain_smoke"]["ok"] is True
    assert any(record["classification"] == "doc_math_review" for record in payload["records"])
    assert str(tmp_path) not in serialized
    assert "D:\\" not in serialized
    assert "C:\\" not in serialized
    assert "/Users/" not in serialized


def test_pdf_english_rebuild_source_import_allowlist_is_unique_and_source_only() -> None:
    from tools.import_pdf_english_rebuild_sources import SOURCE_FILES

    assert len(SOURCE_FILES) == len(set(SOURCE_FILES))
    assert all(not item.startswith("outputs/") for item in SOURCE_FILES)
    assert not any("active_manifest" in item for item in SOURCE_FILES)
    assert "tools/english_text_first_display_projection_planner_v01.py" in SOURCE_FILES


def test_cleanroom_hardening_manifest_validator_rejects_tampered_contract() -> None:
    from tools.validate_cleanroom_hardening_manifest import _build_checks

    tampered = {
        "schema_version": "cleanroom_hardening_manifest.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": "pass",
        "sealed_scopes": [
            "foundation_artifact_atomicity_and_model_checkpoint_guard",
            "final_chain_registry_control_contract_environment_contract_and_scheduler",
            "precleanup_archive_safety_and_worktree_compartment_guard",
        ],
        "replay_commands": [
            "npm run test:foundation-hardening",
            "npm run test:precleanup-safety",
            "npm run test:final-chain-ops",
            "npm run test:cleanroom-hardening-status",
        ],
        "known_blockers": [
            {
                "scope": "continuous_production_worker",
                "status": "java_orchestrator_worker_db_contract_not_implemented",
                "guard": "external_backbone_required_for_unattended_batch_processing",
                "allowed_behavior": "control_plane_dry_run_and_queue_only",
                "legacy_artifact_wait_required": False,
                "safe_boundary": "no_model_db_runtime_execution_without_explicit_worker_contract",
            }
        ],
        "checks": [
            {"name": "required_reports_present", "ok": True},
            {"name": "all_status_reports_pass_or_expected_blocked", "ok": True},
            {"name": "final_chain_ops_covers_four_chains", "ok": True},
            {"name": "final_chain_job_records_self_and_external_validated", "ok": True},
            {"name": "pdf_english_fresh_rebuild_candidate_is_sealed", "ok": True},
            {"name": "pdf_english_raw_pdf_promotion_is_sealed", "ok": True},
            {"name": "no_report_declares_runtime_side_effects", "ok": True},
        ],
        "reports": {
            "foundation_hardening": {
                "path": "C:\\not-portable\\foundation.json",
                "exists": True,
                "status": "pass",
            }
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": True,
            "business_secrets_read": False,
        },
    }

    checks = {item["name"]: item for item in _build_checks(tampered)}
    assert checks["required_report_records_present"]["ok"] is False
    assert checks["report_paths_are_relative_and_existing"]["ok"] is False
    assert checks["execution_contract_has_no_runtime_side_effects"]["ok"] is False
    assert checks["manifest_contains_no_absolute_paths"]["ok"] is False


def test_cleanroom_import_audit_reports_candidates_without_absolute_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    workspace.mkdir()
    (workspace / "config").mkdir()
    (source / "tools").mkdir(parents=True)
    (source / "config").mkdir(parents=True)
    entrypoint = source / "tools" / "run.py"
    config_path = source / "config" / "pipeline.json"
    entrypoint.write_text("print('not imported')\n", encoding="utf-8")
    config_path.write_text('{"ok": true}\n', encoding="utf-8")
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "tools/run.py",
                        "sha256": hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry_path = workspace / "final_chain_registry.yaml"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "final_chain_registry.v0.1",
                "selection_policy": {},
                "chains": [
                    {
                        "chain_id": "pdf_math",
                        "display_name": "PDF Math",
                        "input_format": "pdf",
                        "subject": "math",
                        "protection_status": "protected",
                        "registry_readiness": "ready",
                        "confidence": "high",
                        "canonical_entrypoint": "tools/run.py",
                        "canonical_config_paths": ["config/pipeline.json"],
                        "smoke_status": {"status": "pass"},
                        "runtime_import_policy": {"default_enabled": False},
                        "database_write_policy": {"default_enabled": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = load_final_chain_registry(registry_path)

    report = build_cleanroom_import_audit(
        registry,
        workspace_root=workspace,
        source_roots={"old_local": source},
        handoff_inventories={"pdf_math": inventory_path},
    )

    assert report["schema_version"] == "final_chain_cleanroom_import_audit.v0.1"
    assert report["absolute_paths_as_inputs"] is False
    assert report["missing_in_cleanroom_count"] == 2
    assert report["importable_candidate_count"] == 2
    by_role = {row["role"]: row for row in report["rows"]}
    assert by_role["canonical_entrypoint"]["relative_path"] == "tools/run.py"
    assert by_role["canonical_entrypoint"]["source_candidates"][0]["source_label"] == "old_local"
    assert by_role["canonical_entrypoint"]["source_candidates"][0]["matches_handoff_inventory"] is True
    assert str(source) not in json.dumps(report)


def _write_review_zip(path: Path, title: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("index.html", f"<!doctype html><title>{title}</title><img src='assets/pages/page_001.png'>")
        archive.writestr("assets/pages/page_001.png", b"not-a-real-image-but-valid-zip-entry")
    return path


def _write_doc_math_review_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("index.html", "<!doctype html><title>DOCX math side-by-side review</title>")
        archive.writestr(
            "review_package_summary.json",
            json.dumps({"schema": "docx_math_side_by_side_review_v0.1", "run_id": "gatefix"}),
        )
    return path
