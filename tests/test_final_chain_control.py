from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from teachbase.final_chains import ChainRunRequest, EnvironmentPolicy, build_chain_run_plan, load_final_chain_registry
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
