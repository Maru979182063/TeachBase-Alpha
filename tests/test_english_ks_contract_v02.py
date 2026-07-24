from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

contract_spec = importlib.util.spec_from_file_location("english_ks_contract_v02", TOOLS / "english_ks_contract_v02.py")
contract = importlib.util.module_from_spec(contract_spec)
sys.modules["english_ks_contract_v02"] = contract
assert contract_spec.loader
contract_spec.loader.exec_module(contract)

validator_spec = importlib.util.spec_from_file_location("english_ks_reference_validator_v02", TOOLS / "english_ks_reference_validator_v02.py")
validator = importlib.util.module_from_spec(validator_spec)
sys.modules["english_ks_reference_validator_v02"] = validator
assert validator_spec.loader
validator_spec.loader.exec_module(validator)

gate_spec = importlib.util.spec_from_file_location("english_ks_projection_gate_v02", TOOLS / "english_ks_projection_gate_v02.py")
gate = importlib.util.module_from_spec(gate_spec)
sys.modules["english_ks_projection_gate_v02"] = gate
assert gate_spec.loader
gate_spec.loader.exec_module(gate)

targeted_spec = importlib.util.spec_from_file_location("english_ks_targeted_region_verifier_v02", TOOLS / "english_ks_targeted_region_verifier_v02.py")
targeted = importlib.util.module_from_spec(targeted_spec)
sys.modules["english_ks_targeted_region_verifier_v02"] = targeted
assert targeted_spec.loader
targeted_spec.loader.exec_module(targeted)

closure_spec = importlib.util.spec_from_file_location("english_ks_contract_closure_v02", TOOLS / "english_ks_contract_closure_v02.py")
closure = importlib.util.module_from_spec(closure_spec)
sys.modules["english_ks_contract_closure_v02"] = closure
assert closure_spec.loader
closure_spec.loader.exec_module(closure)

decontam_spec = importlib.util.spec_from_file_location("english_ks_decontaminated_contract_v02", TOOLS / "english_ks_decontaminated_contract_v02.py")
decontam = importlib.util.module_from_spec(decontam_spec)
sys.modules["english_ks_decontaminated_contract_v02"] = decontam
assert decontam_spec.loader
decontam_spec.loader.exec_module(decontam)


def valid_payload() -> dict:
    return {
        "schema": "english_text_first_knowledge_structure_contract_v02.projection",
        "documents": [
            {
                "doc_id": "doc",
                "requested_page_range_capture_status": "COMPLETE",
                "source_page_images": [{"page_id": "doc:page_001", "page_number": 1, "path": "missing.png", "exists": False, "sha256": ""}],
                "source_bundles": [{"source_bundle_id": "bundle_1"}],
                "source_regions": [
                    {
                        "evidence_id": "ev_1",
                        "source_bundle_id": "bundle_1",
                        "page_id": "doc:page_001",
                        "page_number": 1,
                        "region_id": "bundle_1:p001:0001",
                        "bbox_norm1000": [1, 2, 3, 4],
                        "role": "table_fragment",
                        "source_kind": "original_page",
                        "verification_status": "VERIFIED",
                    }
                ],
                "source_region_groups": [
                    {
                        "source_region_group_id": "srg_1",
                        "members": [{"evidence_id": "ev_1", "page_id": "doc:page_001", "region_id": "bundle_1:p001:0001", "sequence": 1}],
                        "coverage_status": "COMPLETE",
                    }
                ],
                "asset_groups": [],
                "semantic_objects": [
                    {
                        "object_id": "obj_1",
                        "open_description": "Knowledge object",
                        "primary_role": {"label": "knowledge_structure", "confidence": 0.9},
                        "secondary_roles": [],
                        "source_bundle_refs": ["bundle_1"],
                        "typed_evidence_refs": ["ev_1"],
                        "source_region_group_refs": ["srg_1"],
                        "asset_group_refs": [],
                        "completeness": {
                            "requested_source_coverage": "COMPLETE",
                            "semantic_capture": "COMPLETE",
                            "source_region_grounding": "COMPLETE",
                            "asset_grounding": "NOT_CREATED",
                            "structured_extraction": "SOURCE_REGION_ONLY",
                        },
                        "structure": {"rows": ["r"], "columns": ["c"], "cells": []},
                        "projections": {
                            "qbank_projection": {"as_is_status": "UNSUPPORTED_AS_IS"},
                            "derivation": {"status": "NOT_APPLICABLE", "requires": [], "derived_object_refs": []},
                            "knowledge_structure": {
                                "status": "READY_WITH_SOURCE_REGIONS",
                                "capability_level": "SOURCE_REGION_BACKED",
                                "knowledge_projection_role": "STRUCTURE_NODE",
                                "reason": "",
                                "blocking_requirements": [],
                            },
                            "faithful_material": {
                                "status": "READY_WITH_SOURCE_REGIONS",
                                "capability_level": "SOURCE_REGION_BACKED",
                                "reason": "",
                                "blocking_requirements": [],
                            },
                        },
                        "human_review_status": "REQUIRED",
                    }
                ],
                "relations": [
                    {
                        "relation_id": "rel_1",
                        "subject": "obj_1",
                        "predicate": "aligned_to",
                        "object": "obj_1",
                        "predicate_open_text": "aligned_to",
                        "evidence_refs": ["srg_1"],
                        "confidence": 0.8,
                    }
                ],
                "uncertainties": [],
                "model_call_refs": {},
            }
        ],
        "model_calls": [],
        "validation_summary": {},
    }


def assert_invalid(mutator, key: str) -> None:
    payload = valid_payload()
    payload["documents"][0]["doc_id"] = "grammar_tense_voice_p001_p004"
    mutator(payload)
    report = validator.validate_all(payload)
    assert not report[key], report


def test_full_nested_schema_positive_fixture() -> None:
    report = validator.validate_all(valid_payload())
    assert report["json_schema_valid"]
    assert report["reference_integrity_valid"]
    assert report["semantic_contract_valid"]
    assert report["projection_gate_valid"]


def test_documents_empty_object_fails_schema() -> None:
    payload = valid_payload()
    payload["documents"] = [{}]
    assert not validator.validate_all(payload)["json_schema_valid"]


def test_illegal_projection_status_fails_gate() -> None:
    assert_invalid(lambda p: p["documents"][0]["semantic_objects"][0]["projections"]["knowledge_structure"].update(status="YEP"), "projection_gate_valid")


def test_dangling_object_ref_fails_reference() -> None:
    assert_invalid(lambda p: p["documents"][0]["relations"][0].update(object="missing"), "reference_integrity_valid")


def test_dangling_asset_ref_fails_reference() -> None:
    assert_invalid(lambda p: p["documents"][0]["semantic_objects"][0]["asset_group_refs"].append("missing_asset_group"), "reference_integrity_valid")


def test_ready_with_asset_without_asset_fails_gate() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["semantic_objects"][0]["projections"]["knowledge_structure"]["status"] = "READY_WITH_ASSET"

    assert_invalid(mutate, "projection_gate_valid")


def test_asset_group_partial_coverage_fails_gate() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["asset_groups"] = [{"asset_group_id": "ag_1", "coverage_status": "PARTIAL", "members": []}]
        p["documents"][0]["semantic_objects"][0]["asset_group_refs"] = ["ag_1"]
        p["documents"][0]["semantic_objects"][0]["projections"]["knowledge_structure"]["status"] = "READY_WITH_ASSET"

    assert_invalid(mutate, "projection_gate_valid")


def test_partial_object_only_blocks_itself() -> None:
    partial = gate.project_v02(
        {"object_id": "a", "primary_role": {"label": "knowledge"}, "structure": {"representation_status": "partial"}},
        has_region_group=True,
        has_partial_region_group=True,
        has_complete_asset_group=False,
    )
    complete = gate.project_v02(
        {"object_id": "b", "primary_role": {"label": "knowledge"}, "structure": {"representation_status": "complete"}},
        has_region_group=True,
        has_complete_region_group=True,
        has_complete_asset_group=False,
    )
    assert partial["knowledge_structure"]["status"] == "NEEDS_REVIEW"
    assert complete["knowledge_structure"]["status"] == "NEEDS_REVIEW"


def test_structured_editable_with_empty_cells_fails_semantic() -> None:
    def mutate(p: dict) -> None:
        obj = p["documents"][0]["semantic_objects"][0]
        obj["completeness"]["structured_extraction"] = "STRUCTURED_EDITABLE"
        obj["structure"]["cells"] = []

    assert_invalid(mutate, "semantic_contract_valid")


def test_uses_asset_target_type_validation() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["relations"][0]["predicate"] = "uses_asset"
        p["documents"][0]["relations"][0]["object"] = "obj_1"

    assert_invalid(mutate, "reference_integrity_valid")


def test_qbank_as_is_and_derivation_are_separate() -> None:
    proj = gate.project_v02(
        {"object_id": "obj", "primary_role": {"label": "practice"}, "structure": {"representation_status": "complete"}, "projections": {"qbank": {"status": "DERIVABLE"}}},
        has_region_group=True,
        has_complete_asset_group=False,
    )
    assert proj["qbank_projection"]["as_is_status"] == "NEEDS_REVIEW"
    assert proj["derivation"]["status"] == "NOT_APPLICABLE"


def test_derived_object_requires_derived_from_relation() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["semantic_objects"][0]["projections"]["derivation"]["status"] = "READY_FOR_GENERATION"
        p["documents"][0]["semantic_objects"][0]["projections"]["derivation"]["derived_object_refs"] = ["derived_1"]

    assert_invalid(mutate, "projection_gate_valid")


def test_knowledge_projection_role_validation() -> None:
    assert_invalid(lambda p: p["documents"][0]["semantic_objects"][0]["projections"]["knowledge_structure"].update(knowledge_projection_role="BUCKET"), "semantic_contract_valid")


def test_old_gold_exact_directional_metrics_separated_if_output_exists() -> None:
    path = ROOT / "outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v02_20260716_1205/old_grammar_exact_comparison.json"
    if path.exists():
        data = contract.read_json(path)
        metrics = data["metrics"]
        assert "directional" in metrics
        assert "qbank_as_is_exact" in metrics


def test_portable_html_uses_review_assets_if_output_exists() -> None:
    path = ROOT / "outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v02_20260716_1205/knowledge_structure_review.html"
    if path.exists():
        html = path.read_text(encoding="utf-8")
        assert "review_assets/" in html
        assert "C:\\Users" not in html


def test_v01_baseline_non_destructive_if_output_exists() -> None:
    path = ROOT / "outputs/english_text_first_pipeline_v02_spec_20260715/knowledge_structure_projection_v01_20260716_combined_v2/run_summary.json"
    assert path.exists()


def test_targeted_region_verifier_does_not_create_asset_group() -> None:
    payload = valid_payload()
    payload["documents"][0]["doc_id"] = "grammar_tense_voice_p001_p004"
    obj = payload["documents"][0]["semantic_objects"][0]
    obj["object_id"] = "obj_003"
    obj["source_region_group_refs"] = ["srg_1"]
    payload["documents"][0]["source_region_groups"][0]["source_region_group_id"] = "srg_1"
    call = {
        "call_id": "call",
        "document_id": "grammar_tense_voice_p001_p004",
        "model": "model",
        "result": {
            "source_region_groups": [
                {
                    "object_id": "obj_003",
                    "purpose": "fillable_template",
                    "coverage_status": "COMPLETE",
                    "members": [
                        {"page_number": 1, "bbox_norm1000": [10, 20, 900, 500], "role": "table_fragment", "sequence": 1}
                    ],
                    "reason": "verified",
                }
            ]
        },
    }

    updated = targeted.apply_verified_regions(payload, call)
    updated_obj = updated["documents"][0]["semantic_objects"][0]
    assert updated["documents"][0]["asset_groups"] == []
    assert updated_obj["asset_group_refs"] == []
    assert updated_obj["completeness"]["source_region_grounding"] == "COMPLETE"
    assert updated_obj["completeness"]["asset_grounding"] == "UNVERIFIED"
    assert updated_obj["projections"]["knowledge_structure"]["status"] == "READY_WITH_SOURCE_REGIONS"


def test_unverified_source_region_cannot_ready() -> None:
    payload = valid_payload()
    obj = payload["documents"][0]["semantic_objects"][0]
    payload["documents"][0]["source_region_groups"][0]["coverage_status"] = "UNVERIFIED"
    obj["completeness"]["source_region_grounding"] = "UNVERIFIED"
    report = validator.validate_all(payload)
    assert not report["projection_gate_valid"]


def test_projector_maps_unverified_to_review_and_partial_to_preserve_fragment() -> None:
    unverified = gate.project_v02(
        {"object_id": "u", "primary_role": {"label": "knowledge"}, "structure": {"representation_status": "complete"}},
        has_region_group=True,
    )
    partial = gate.project_v02(
        {"object_id": "p", "primary_role": {"label": "knowledge"}, "structure": {"representation_status": "partial"}},
        has_region_group=True,
        has_partial_region_group=True,
    )
    assert unverified["knowledge_structure"]["status"] == "NEEDS_REVIEW_WITH_SOURCE_REGIONS"
    assert partial["knowledge_structure"]["status"] == "NEEDS_REVIEW"
    assert partial["faithful_material"]["status"] == "PRESERVE_PARTIAL_FRAGMENT"


def test_no_asset_group_maps_to_not_created_and_not_asset_only() -> None:
    completeness = gate.completeness_for(
        {"object_id": "x", "structure": {"rows": ["r"], "columns": ["c"], "cells": []}},
        has_region_group=True,
        has_complete_region_group=True,
        has_complete_asset_group=False,
    )
    assert completeness["asset_grounding"] == "NOT_CREATED"
    assert completeness["structured_extraction"] == "SOURCE_REGION_ONLY"


def test_not_applicable_derivation_requires_empty() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["semantic_objects"][0]["projections"]["derivation"]["requires"] = ["human_review"]

    assert_invalid(mutate, "projection_gate_valid")


def test_blocked_qbank_requires_blocking_requirements() -> None:
    def mutate(p: dict) -> None:
        qbank = p["documents"][0]["semantic_objects"][0]["projections"]["qbank_projection"]
        qbank["as_is_status"] = "BLOCKED"
        qbank["blocking_requirements"] = []

    assert_invalid(mutate, "projection_gate_valid")


def test_verified_evidence_requires_source_bundle_id() -> None:
    def mutate(p: dict) -> None:
        p["documents"][0]["source_regions"][0]["source_bundle_id"] = ""

    assert_invalid(mutate, "reference_integrity_valid")


def test_malformed_region_id_and_page_mismatch_and_bbox_oob_fail_reference() -> None:
    assert_invalid(lambda p: p["documents"][0]["source_regions"][0].update(region_id="r1"), "reference_integrity_valid")
    assert_invalid(lambda p: p["documents"][0]["source_regions"][0].update(region_id="bundle_1:p002:0001"), "reference_integrity_valid")
    assert_invalid(lambda p: p["documents"][0]["source_regions"][0].update(bbox_norm1000=[0, 0, 2000, 10]), "reference_integrity_valid")


def test_standalone_label_does_not_create_depends_on_warning() -> None:
    payload = valid_payload()
    payload["documents"][0]["semantic_objects"][0]["primary_role"]["label"] = "standalone_practice_set"
    payload["documents"][0]["relations"][0]["predicate"] = "depends_on"
    report = validator.validate_all(payload)
    assert report["projection_gate_valid"]
    assert not report["projection_gate_warnings"]


def test_explicit_independence_claim_conflicts_with_depends_on_warning() -> None:
    payload = valid_payload()
    payload["documents"][0]["semantic_objects"][0]["independence_claim"] = {
        "value": True,
        "provenance": "human_review",
    }
    payload["documents"][0]["relations"][0]["predicate"] = "depends_on"
    report = validator.validate_all(payload)
    assert report["projection_gate_valid"]
    assert report["projection_gate_warnings"]


def test_closure_converts_unverified_ready_to_review_and_asset_not_created() -> None:
    payload = valid_payload()
    obj = payload["documents"][0]["semantic_objects"][0]
    payload["documents"][0]["source_region_groups"][0]["coverage_status"] = "UNVERIFIED"
    obj["completeness"]["source_region_grounding"] = "UNVERIFIED"
    obj["completeness"]["asset_grounding"] = "UNVERIFIED"
    obj["completeness"]["structured_extraction"] = "ASSET_ONLY"
    closed = closure.close_contract(payload)
    closed_obj = closed["documents"][0]["semantic_objects"][0]
    assert closed_obj["completeness"]["source_region_grounding"] == "UNVERIFIED"
    assert closed_obj["completeness"]["asset_grounding"] == "NOT_CREATED"
    assert closed_obj["completeness"]["structured_extraction"] == "SOURCE_REGION_ONLY"
    assert closed_obj["projections"]["knowledge_structure"]["status"] == "NEEDS_REVIEW_WITH_SOURCE_REGIONS"
    assert closed_obj["human_review_status"] == "REQUIRED"


def comparable_eligibility(payload: dict) -> list[dict]:
    result = decontam.projection_eligibility(payload)
    return [
        {
            "source_region_grounding": row["source_region_grounding"],
            "qbank_as_is": row["qbank_as_is"],
            "knowledge_structure": row["knowledge_structure"],
            "faithful_material": row["faithful_material"],
        }
        for row in result["rows"]
    ]


def comparable_findings(payload: dict) -> list[tuple[str, str]]:
    return [(item["code"], item["severity"]) for item in decontam.contract_findings(payload)]


def test_role_label_text_mutation_does_not_change_deterministic_gate() -> None:
    payload = valid_payload()
    mutated = deepcopy(payload)
    mutated["documents"][0]["semantic_objects"][0]["primary_role"]["label"] = "role_x7q"
    assert comparable_eligibility(payload) == comparable_eligibility(mutated)
    assert comparable_findings(payload) == comparable_findings(mutated)


def test_open_description_reason_predicate_text_mutation_does_not_change_findings() -> None:
    payload = valid_payload()
    mutated = deepcopy(payload)
    mutated["documents"][0]["semantic_objects"][0]["open_description"] = "foo_9182"
    mutated["documents"][0]["relations"][0]["reason"] = "bar_331"
    mutated["documents"][0]["relations"][0]["predicate_open_text"] = "baz_777"
    assert comparable_eligibility(payload) == comparable_eligibility(mutated)
    assert comparable_findings(payload) == comparable_findings(mutated)


def test_uses_asset_conflict_preserves_raw_predicate() -> None:
    payload = valid_payload()
    payload["documents"][0]["relations"][0]["predicate"] = "uses_asset"
    payload["documents"][0]["relations"][0]["object"] = "obj_1"
    findings = decontam.contract_findings(payload)
    assert any(item["code"] == "RELATION_TARGET_TYPE_CONFLICT" for item in findings)
    assert payload["documents"][0]["relations"][0]["predicate"] == "uses_asset"


def test_malformed_region_id_is_not_repaired_by_decontaminated_contract() -> None:
    payload = valid_payload()
    payload["documents"][0]["source_regions"][0]["region_id"] = ":p004:0007"
    findings = decontam.contract_findings(payload)
    assert any(item["code"] == "SOURCE_REGION_ID_UNPARSEABLE" for item in findings)
    assert payload["documents"][0]["source_regions"][0]["region_id"] == ":p004:0007"
