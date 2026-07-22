from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from docx_math_unit_boundary_resolver_v01 import classify_section_scope, replay_boundary_actions  # noqa: E402


RUN_ROOT = ROOT / "outputs" / "docx_native_boundary_resolver_v0_1" / "doc2_unit_boundary_replay_v10_2_20260716"
GOLDEN = ROOT / "tests" / "fixtures" / "docx_boundary" / "doc2_v10_golden.json"


def _load_artifacts() -> tuple[dict, dict, dict, dict, dict, dict]:
    matches = list(RUN_ROOT.glob("*/summary.json"))
    if not matches:
        pytest.skip("doc2 deterministic replay v10 artifacts are not present")
    base = matches[0].parent
    return (
        json.loads((base / "summary.json").read_text(encoding="utf-8")),
        json.loads((base / "question_boundary_candidates.json").read_text(encoding="utf-8")),
        json.loads((base / "block_disposition_manifest.json").read_text(encoding="utf-8")),
        json.loads((base / "boundary_review.json").read_text(encoding="utf-8")),
        json.loads((base / "boundary_repair_queue.json").read_text(encoding="utf-8")),
        json.loads((base / "question_family_manifest.json").read_text(encoding="utf-8")),
    )


def _base_dir() -> Path:
    matches = list(RUN_ROOT.glob("*/summary.json"))
    if not matches:
        pytest.skip("doc2 deterministic replay v10.2 artifacts are not present")
    return matches[0].parent


def _candidate_by_block(candidates: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for question in candidates["questions"]:
        for block_id in question["block_ids"]:
            result.setdefault(block_id, []).append(question["candidate_id"])
    return result


def _disposition_by_block(disposition: dict) -> dict[str, str]:
    return {item["block_id"]: item["disposition"] for item in disposition["dispositions"]}


def test_doc2_v10_numeric_prefix_does_not_override_semantic_role() -> None:
    summary, candidates, disposition, _review, _queue, _family = _load_artifacts()
    by_block = _candidate_by_block(candidates)
    by_disp = _disposition_by_block(disposition)

    false_candidates = {
        "qb_b_000002",
        "qb_b_000003",
        "qb_b_000004",
        "qb_b_000017",
        "qb_b_000022",
        "qb_b_000023",
    }
    assert false_candidates.isdisjoint({question["candidate_id"] for question in candidates["questions"]})
    assert candidates["questions"][0]["start_block_id"] == "b_000027"
    assert candidates["questions"][0]["candidate_id"] == "qb_b_000027"
    assert summary["usage"]["total_tokens"] == 0

    for index in range(2, 5):
        assert by_block.get(f"b_{index:06d}", []) == []
        assert by_disp[f"b_{index:06d}"] == "instruction"
    for index in range(9, 25):
        assert by_block.get(f"b_{index:06d}", []) == []
        assert by_disp[f"b_{index:06d}"] in {"knowledge", "section", "decorative"}


def test_doc2_v10_required_boundary_examples() -> None:
    _summary, candidates, disposition, review, queue, _family = _load_artifacts()
    by_block = _candidate_by_block(candidates)
    by_disp = _disposition_by_block(disposition)

    assert by_block["b_000047"] == ["qb_b_000047"]
    assert by_block["b_000048"] == ["qb_b_000047"]
    assert by_block["b_000056"] == ["qb_b_000056"]
    assert by_block["b_000057"] == ["qb_b_000057"]
    assert by_block["b_000058"] == ["qb_b_000058"]

    assert by_block["b_000068"] == ["qb_b_000068"]
    assert by_block["b_000069"] == ["qb_b_000069"]
    assert by_block["b_000070"] == ["qb_b_000070"]

    assert by_block["b_000079"] == ["qb_b_000079"]
    assert by_block["b_000081"] == ["qb_b_000079"]
    assert by_block["b_000082"] == ["qb_b_000082"]
    assert by_block["b_000086"] == ["qb_b_000082"]
    assert by_block["b_000087"] == ["qb_b_000082"]
    assert by_block["b_000088"] == ["qb_b_000082"]
    assert "qb_b_000088" not in {question["candidate_id"] for question in candidates["questions"]}
    assert by_block["b_000089"] == ["qb_b_000089"]
    assert by_block["b_000096"] == ["qb_b_000089"]

    assert by_block["b_000219"] == ["qb_b_000219"]
    assert by_block["b_000223"] == ["qb_b_000219"]
    assert by_disp["b_000227"] == "section"
    assert by_disp["b_000228"] == "section"
    assert by_block["b_000229"] == ["qb_b_000229"]

    assert by_block["b_000287"] == ["qb_b_000287"]
    assert by_block["b_000288"] == ["qb_b_000287"]
    assert by_block["b_000308"] == ["qb_b_000308"]
    assert by_block["b_000312"] == ["qb_b_000308"]

    assert review["question_flow_status"] == "bulk_ready"
    assert review["document_content_status"] == "partial"
    assert [case["target_block_ids"] for case in queue["repair_cases"]] == [["b_000226"]]
    assert queue["repair_cases"][0]["allowed_actions"] == [
        "attach_to_previous_question",
        "attach_to_next_section",
        "classify_non_question",
        "quarantine_span",
        "no_change",
    ]


def test_doc2_v10_disposition_and_family_integrity() -> None:
    summary, candidates, disposition, _review, _queue, family = _load_artifacts()
    assert disposition["block_count"] == 322
    assert disposition["disposition_block_count"] == 322
    assert disposition["duplicate_disposition_count"] == 0
    assert disposition["missing_disposition_count"] == 0
    assert disposition["question_block_overlap_count"] == 0
    assert disposition["source_content_hash_change_count"] == 0

    assert summary["question_count"] == len(candidates["questions"])
    assert summary["ready_question_count"] == sum(
        1 for question in candidates["questions"] if question["boundary_status"] == "ready"
    )
    assert not [
        question["candidate_id"]
        for question in candidates["questions"]
        if question["boundary_status"] == "ready"
        and (question["quality_flags"] or question["review_flags"] or question["blocking_reasons"])
    ]

    candidate_ids = {question["candidate_id"] for question in candidates["questions"]}
    for item in family["families"]:
        assert item["root_candidate_id"] in candidate_ids
        assert any(member["candidate_id"] == item["root_candidate_id"] for member in item["members"])


def test_doc2_v10_1_action_replay_and_audit_gates() -> None:
    base = _base_dir()
    summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    immutable = json.loads((base / "immutable_block_stream.json").read_text(encoding="utf-8"))
    assembly = json.loads((base / "boundary_assembly_actions.json").read_text(encoding="utf-8"))
    repair = json.loads((base / "boundary_repair_actions.json").read_text(encoding="utf-8"))
    audit = json.loads((base / "boundary_action_replay_audit.json").read_text(encoding="utf-8"))

    replayed = replay_boundary_actions(immutable, assembly, repair)
    assert audit["status"] == "pass"
    assert audit["question_boundary_mismatch_count"] == 0
    assert audit["candidate_owner_mismatch_count"] == 0
    assert audit["disposition_mismatch_count"] == 0
    assert audit["family_reference_mismatch_count"] == 0
    assert audit["status_mismatch_count"] == 0
    assert replayed["status"]["question_flow_status"] == "bulk_ready"
    assert replayed["status"]["document_content_status"] == "partial"
    assert repair["actions"] == []

    assert summary["audit_trace_status"] == "pass"
    assert summary["action_replay_status"] == "pass"
    assert summary["projection_replay_status"] == "pass"
    assert summary["artifact_consistency_status"] == "pass"
    assert summary["semantic_boundary_validation_status"] == "pass"
    assert summary["boundary_pattern_audit_status"] == "pass"
    assert summary["raw_issue_closure_status"] == "pass"
    assert summary["golden_fixture_status"] == "pass"
    assert summary["six_doc_regression_allowed"] is True


def test_doc2_v10_1_action_disposition_consistency_for_prior_mismatches() -> None:
    base = _base_dir()
    assembly = json.loads((base / "boundary_assembly_actions.json").read_text(encoding="utf-8"))
    disposition = json.loads((base / "block_disposition_manifest.json").read_text(encoding="utf-8"))
    action_by_block = {
        action.get("block_id"): action
        for action in assembly["actions"]
        if action.get("type") in {"classify_non_question", "quarantine_span"}
    }
    disp_by_block = {item["block_id"]: item for item in disposition["dispositions"]}

    assert action_by_block["b_000000"]["as"] == "document_meta"
    assert disp_by_block["b_000000"]["disposition"] == "document_meta"
    assert action_by_block["b_000001"]["as"] == "decorative"
    assert disp_by_block["b_000001"]["disposition"] == "decorative"
    assert action_by_block["b_000025"]["as"] == "decorative"
    assert disp_by_block["b_000025"]["disposition"] == "decorative"

    for action in [action_by_block["b_000000"], action_by_block["b_000001"], action_by_block["b_000025"]]:
        assert action["action_id"].startswith("assembly_action_")
        assert action["actor"] == "deterministic_rule"
        assert action["rule_id"]


def test_doc2_v10_1_raw_issue_closure_and_golden_fixture() -> None:
    base = _base_dir()
    raw = json.loads((base / "raw_issue_resolution_manifest.json").read_text(encoding="utf-8"))
    golden_audit = json.loads((base / "golden_fixture_audit.json").read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    candidates = json.loads((base / "question_boundary_candidates.json").read_text(encoding="utf-8"))

    assert raw["raw_issue_count"] == 10
    assert raw["resolution_record_count"] == 10
    assert raw["metrics"]["missing_resolution_count"] == 0
    assert raw["unresolved_without_repair_case_count"] == 0
    assert raw["missing_resolution_action_reference_count"] == 0
    assert {item["resolution_status"] for item in raw["resolutions"]} <= {
        "resolved_deterministically",
        "false_positive",
        "superseded",
        "converted_to_repair_case",
        "quarantined",
        "partially_resolved",
        "still_open",
    }
    assert raw["metrics"]["converted_to_repair_case_count"] >= 1
    assert raw["metrics"]["quarantined_count"] >= 1

    assert golden_audit["status"] == "pass"
    assert golden_audit["schema_version"] == "docx_math_golden_fixture_audit.v0.2"
    assert golden_audit["assertion_count"] > 0
    assert golden_audit["failed_assertion_count"] == 0
    by_candidate = {question["candidate_id"]: question for question in candidates["questions"]}
    assert len(candidates["questions"]) == golden["expected_question_count"]
    for candidate_id, expected in golden["expected_boundaries"].items():
        question = by_candidate[candidate_id]
        assert [question["start_block_id"], question["end_block_id"]] == expected

    inventory = json.loads((base / "boundary_rule_inventory.json").read_text(encoding="utf-8"))
    overfit = json.loads((base / "overfit_literal_scan.json").read_text(encoding="utf-8"))
    evidence = json.loads((base / "boundary_decision_evidence.json").read_text(encoding="utf-8"))
    assert inventory["rule_count"] >= 20
    assert inventory["regex_rule_count"] == 0
    assert overfit["status"] == "pass"
    assert overfit["forbidden_literal_match_count"] == 0
    assert evidence["status"] == "pass"
    assert evidence["single_evidence_final_decision_count"] == 0
    assert evidence["regex_only_final_decision_count"] == 0
    assert evidence["keyword_only_section_scope_count"] == 0
    assert evidence["hardcoded_literal_decision_count"] == 0
    assert evidence["production_code_reads_golden_fixture"] is False
    assert evidence["production_code_reads_doc2_fixture"] is False


def test_doc2_v10_2_semantic_section_scope_closure() -> None:
    base = _base_dir()
    candidates = json.loads((base / "question_boundary_candidates.json").read_text(encoding="utf-8"))
    disposition = json.loads((base / "block_disposition_manifest.json").read_text(encoding="utf-8"))
    section_scope = json.loads((base / "section_scope_manifest.json").read_text(encoding="utf-8"))
    semantic = json.loads((base / "semantic_boundary_audit.json").read_text(encoding="utf-8"))
    assembly = json.loads((base / "boundary_assembly_actions.json").read_text(encoding="utf-8"))

    by_candidate = {question["candidate_id"]: question for question in candidates["questions"]}
    by_disp = {item["block_id"]: item for item in disposition["dispositions"]}
    by_section = {item["block_id"]: item for item in section_scope["sections"]}

    assert "qb_b_000088" not in by_candidate
    assert by_candidate["qb_b_000082"]["block_ids"] == [
        "b_000082",
        "b_000083",
        "b_000084",
        "b_000085",
        "b_000086",
        "b_000087",
        "b_000088",
    ]
    assert by_candidate["qb_b_000082"]["question_block_roles"]["b_000087"] == "internal_heading"
    assert by_candidate["qb_b_000082"]["question_block_roles"]["b_000088"] == "prompt"
    assert by_disp["b_000087"]["owner_candidate_id"] == "qb_b_000082"
    assert by_disp["b_000087"]["question_block_role"] == "internal_heading"
    assert by_disp["b_000088"]["owner_candidate_id"] == "qb_b_000082"
    assert by_disp["b_000088"]["question_block_role"] == "prompt"
    assert by_section["b_000087"]["section_scope"] == "question_internal"
    assert by_section["b_000087"]["hard_stop"] is False
    assert by_section["b_000087"]["owner_candidate_id"] == "qb_b_000082"
    assert section_scope["section_scope_missing_count"] == 0
    assert section_scope["unknown_section_count"] == 0
    assert semantic["status"] == "pass"
    assert semantic["context_dependent_orphan_question_count"] == 0
    assert semantic["question_internal_heading_split_count"] == 0
    assert semantic["unresolved_section_scope_count"] == 0

    create_action = next(action for action in assembly["actions"] if action.get("candidate_id") == "qb_b_000082")
    assert create_action["type"] == "create_question"
    assert create_action["block_ids"][-2:] == ["b_000087", "b_000088"]
    assert create_action["question_block_roles"]["b_000087"] == "internal_heading"


def test_doc2_v10_section_scope_counterfactuals() -> None:
    section_block = {
        "block_id": "b_s",
        "source_order": 10,
        "text": "【问题解决】",
        "markdown": "【问题解决】",
        "formula_count": 0,
        "image_refs": [],
    }
    positive = classify_section_scope(
        block=section_block,
        current_question_open=True,
        current_section_kind="problem",
        units_for_block=[{"relation": "continues_previous", "semantic_role": "section"}],
        next_units=[{"relation": "part_of_question", "semantic_role": "question"}],
        next_block={"block_id": "b_next", "source_order": 11, "text": "根据上述材料回答问题", "markdown": "根据上述材料回答问题"},
    )
    assert positive["section_scope"] == "question_internal"
    assert positive["hard_stop"] is False

    numbered_next = classify_section_scope(
        block=section_block,
        current_question_open=True,
        current_section_kind="assessment",
        units_for_block=[{"relation": "continues_previous", "semantic_role": "section"}],
        next_units=[{"relation": "part_of_question", "semantic_role": "question"}],
        next_block={"block_id": "b_next", "source_order": 11, "text": "1．新的独立试卷题", "markdown": "1．新的独立试卷题"},
    )
    assert numbered_next["section_scope"] != "question_internal"

    no_open_question = classify_section_scope(
        block=section_block,
        current_question_open=False,
        current_section_kind="section",
        units_for_block=[{"relation": "standalone", "semantic_role": "section"}],
        next_units=[{"relation": "standalone", "semantic_role": "knowledge"}],
        next_block={"block_id": "b_next", "source_order": 11, "text": "本节主要解决运算问题", "markdown": "本节主要解决运算问题"},
    )
    assert no_open_question["section_scope"] == "document"
    assert no_open_question["hard_stop"] is True
