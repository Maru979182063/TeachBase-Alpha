from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from teachbase.final_chains import (
    ChainRunRequest,
    EnvironmentPolicy,
    build_final_chain_adapters,
    build_chain_run_plan,
    describe_adapters,
    inspect_adapter_contracts,
    inspect_registry_environments,
    load_final_chain_registry,
    schedule_chain_run,
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
    request = ChainRunRequest(chain_id="doc_math", input_path="sample.docx", output_root="outputs/final_chain_runs")

    plan = build_chain_run_plan(registry, request, workspace_root=ROOT)

    assert plan["status"] == "blocked"
    assert "canonical_entrypoint_present" in plan["blocked_reasons"]
    assert "canonical_configs_present" in plan["blocked_reasons"]


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
    assert by_id["doc_math"]["status"] == "blocked"
    assert "required_paths_present" in by_id["doc_math"]["blocked_reasons"]
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
        [sys.executable, "tools/final_chain_control.py", "env-check", "--chain-id", "doc_math"],
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
    assert env_payload["chains"][0]["chain_id"] == "doc_math"
    assert env_payload["chains"][0]["status"] == "blocked"

    adapter_completed = subprocess.run(
        [sys.executable, "tools/final_chain_control.py", "adapter-contracts", "--chain-id", "pdf_math"],
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
