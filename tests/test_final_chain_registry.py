from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tools.validate_final_chain_registry import validate_final_chain_registry


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"


def _load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8-sig"))


def test_final_chain_registry_declares_four_product_chains() -> None:
    registry = _load_registry()
    assert registry["schema_version"] == "final_chain_registry.v0.1"
    chains = {item["chain_id"]: item for item in registry["chains"]}
    assert set(chains) == {"doc_math", "doc_english", "pdf_math", "pdf_english"}
    assert len(chains) == len(registry["chains"])


def test_current_final_chain_registry_validates() -> None:
    result = validate_final_chain_registry(REGISTRY, ROOT)
    assert result["ok"], result
    assert result["chain_count"] == 4


def test_final_chains_are_protected_and_runtime_safe_by_default() -> None:
    registry = _load_registry()
    assert registry["selection_policy"]["do_not_guess_latest_directory"] is True
    for chain in registry["chains"]:
        assert chain["protection_status"] == "protected"
        assert chain["runtime_import_policy"]["default_enabled"] is False
        assert chain["database_write_policy"]["default_enabled"] is False


def test_high_confidence_chains_have_passed_smoke_status() -> None:
    chains = {item["chain_id"]: item for item in _load_registry()["chains"]}
    for chain_id in ("doc_math", "doc_english", "pdf_math"):
        assert chains[chain_id]["confidence"] == "high"
        assert chains[chain_id]["smoke_status"]["status"] == "pass"


def test_pdf_english_is_registered_with_raw_pdf_promotion_admission() -> None:
    chains = {item["chain_id"]: item for item in _load_registry()["chains"]}
    pdf_english = chains["pdf_english"]
    assert pdf_english["canonical_pipeline_name"] == "english_text_first_graph_first"
    assert pdf_english["canonical_entrypoint"] == "config/english_text_first_graph_first/active_manifest.json"
    assert pdf_english["smoke_status"]["status"] == "pass"
    assert pdf_english["registry_readiness"] == "ready_for_java_shell_admission"
    assert pdf_english["java_shell_admission"]["allowed"] is True
    assert pdf_english["java_shell_admission"]["not_a_model_execution_claim"] is True
    assert pdf_english["production_model_execution_policy"]["model_calls_default_enabled"] is False


def test_duplicate_final_chain_id_fails() -> None:
    registry = _load_registry()
    registry["chains"].append(dict(registry["chains"][0]))
    with tempfile.TemporaryDirectory() as td:
        temp_registry = Path(td) / "final_chain_registry.yaml"
        temp_registry.write_text(json.dumps(registry), encoding="utf-8")
        result = validate_final_chain_registry(temp_registry, ROOT)
    assert not result["ok"]
    assert any(error["code"] == "duplicate_chain_id" for error in result["errors"])


def test_pdf_english_java_shell_admission_marker_is_required() -> None:
    registry = _load_registry()
    for chain in registry["chains"]:
        if chain["chain_id"] == "pdf_english":
            chain["registry_readiness"] = "protected_definition_ready"
            chain["java_shell_admission"]["allowed"] = False
    with tempfile.TemporaryDirectory() as td:
        temp_registry = Path(td) / "final_chain_registry.yaml"
        temp_registry.write_text(json.dumps(registry), encoding="utf-8")
        result = validate_final_chain_registry(temp_registry, ROOT)
    assert not result["ok"]
    codes = {error["code"] for error in result["errors"]}
    assert "pdf_english_missing_java_shell_admission_marker" in codes
    assert "pdf_english_java_shell_admission_not_allowed" in codes
