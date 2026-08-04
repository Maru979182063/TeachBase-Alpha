from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from teachbase.final_chains import (
    ChainRunRequest,
    EnvironmentPolicy,
    build_final_chain_adapters,
    build_final_chain_control_dashboard,
    build_chain_run_plan,
    build_cleanroom_import_audit,
    build_readiness_matrix,
    describe_adapters,
    inspect_adapter_contracts,
    inspect_job_record,
    inspect_registry_environments,
    load_final_chain_registry,
    schedule_chain_run,
    transition_job_record,
)
from teachbase.core.errors import ConfigurationError


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"


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
    assert "canonical_entrypoint_present" in plan["blocked_reasons"]


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
    record_path = workspace / record["record_path"]
    assert record_path.exists()
    assert json.loads(record_path.read_text(encoding="utf-8"))["job_id"] == record["job_id"]
    assert record["lifecycle"]["status"] == "scheduled_blocked"
    assert record["lifecycle"]["terminal"] is True
    assert record["lifecycle"]["allowed_next_statuses"] == []


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
    assert not (tmp_path / "outside").exists()


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
    assert inspection["terminal"] is True
    assert inspection["model_invoked"] is False


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
    assert by_id["pdf_english"]["status"] == "blocked"
    assert "required_paths_present" in by_id["pdf_english"]["blocked_reasons"]
    assert "smoke_status_partial_requires_restore_or_rerun" in by_id["pdf_english"]["notes"]


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
    assert env_completed.returncode == 2
    env_payload = json.loads(env_completed.stdout)
    assert env_payload["schema_version"] == "final_chain_environment_report.v0.1"
    assert env_payload["chain_count"] == 1
    assert env_payload["chains"][0]["chain_id"] == "pdf_english"
    assert env_payload["chains"][0]["status"] == "blocked"

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
    assert by_id["pdf_english"]["environment"]["status"] == "blocked"


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


def test_adapter_dry_run_blocks_missing_input() -> None:
    registry = load_final_chain_registry(REGISTRY)
    adapter = build_final_chain_adapters(registry, workspace_root=ROOT)["pdf_math"]
    request = ChainRunRequest(chain_id="pdf_math", input_path="missing.pdf", output_root="outputs/final_chain_runs")

    result = adapter.dry_run(request)

    assert result["status"] == "dry_run_blocked"
    assert "input_path_present" in result["plan"]["blocked_reasons"]


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
    assert by_id["pdf_english"]["readiness_tier"] == "restore_or_rerun_required"
    assert "import_or_restore_canonical_entrypoint_and_configs" in by_id["pdf_english"]["recommended_actions"]


def test_readiness_matrix_uses_sample_input_to_mark_adapter_dry_run_ready(tmp_path: Path) -> None:
    registry = load_final_chain_registry(REGISTRY)
    doc_math_sample = tmp_path / "doc_math.docx"
    doc_english_sample = tmp_path / "doc_english.docx"
    pdf_math_sample = tmp_path / "pdf_math.pdf"
    doc_math_sample.write_text("docx placeholder", encoding="utf-8")
    doc_english_sample.write_text("docx placeholder", encoding="utf-8")
    pdf_math_sample.write_text("pdf placeholder", encoding="utf-8")

    report = build_readiness_matrix(
        registry,
        workspace_root=ROOT,
        sample_inputs={
            "doc_math": str(doc_math_sample),
            "doc_english": str(doc_english_sample),
            "pdf_math": str(pdf_math_sample),
        },
    )

    by_id = {item["chain_id"]: item for item in report["rows"]}
    assert report["ready_for_adapter_dry_run_count"] == 3
    assert by_id["doc_math"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["doc_english"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["pdf_math"]["readiness_tier"] == "ready_for_adapter_dry_run"
    assert by_id["pdf_math"]["adapter_dry_run_status"] == "dry_run_ready"
    assert by_id["pdf_english"]["readiness_tier"] == "restore_or_rerun_required"
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
    assert by_id["pdf_english"]["lane"] == "needs_artifact_restore_or_smoke"
    assert report["job_lifecycle_policy"]["allowed_transitions"]["scheduled_ready"] == [
        "dry_run_started",
        "cancelled",
    ]


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


def test_ready_sample_report_runs_three_control_adapters_without_side_effects() -> None:
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
    assert payload["ready_for_adapter_dry_run_count"] == 3
    assert payload["pdf_english_recovery_status"] == "restore_or_rerun_required"
    assert {row["chain_id"] for row in payload["rows"]} == {"doc_math", "doc_english", "pdf_math"}
    for row in payload["rows"]:
        assert row["sample_input"].startswith("tests/fixtures/final_chain_samples/")
        assert row["adapter_dry_run_status"] == "dry_run_ready"
        assert row["schedule_status"] == "scheduled_ready"
        assert row["adapter_invoked_entrypoint"] is False
        assert row["execution_contract"] == {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        }


def test_pdf_english_recovery_validator_fails_closed_without_manifest() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/validate_pdf_english_recovery.py", "--require-ready"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "pdf_english_recovery_validation.v0.1"
    assert payload["status"] == "blocked_missing_or_invalid_manifest"
    assert "four_branch_runs_declared" in payload["required_manifest_check_failures"]
    assert payload["execution_contract"] == {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


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
    assert payload["pdf_english_recovery_validation_status"] == "blocked_missing_or_invalid_manifest"
    assert checks["pdf_english_recovery_validator_fails_closed"]["ok"] is True
    assert checks["pdf_english_recovery_requires_four_branch_manifest"]["ok"] is True


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
