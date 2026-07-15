from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_semantic_role_effectiveness_eval import DEFAULT_CASES, _case_to_node, predict_case, validate_cases
from tools.semantic_role_eval_metrics import compute_metrics


class SemanticRoleGoldLeakageTests(unittest.TestCase):
    def test_unverified_cases_are_excluded_from_formal_metrics(self) -> None:
        cases = [
            {
                "case_id": "verified",
                "evaluation_tier": "VERIFIED_REAL_GOLD",
                "gold_status": "VERIFIED",
                "subject": "math",
                "expected_semantic_role": "exercise",
                "expected_presentation_kind": "text",
                "expected_disposition": "processable",
                "expected_route_candidate": "question_splitter",
                "expected_relations": [],
                "expected_needs_role_review": False,
            },
            {
                "case_id": "candidate",
                "evaluation_tier": "CANDIDATE_REVIEW",
                "gold_status": "REVIEW_REQUIRED",
                "subject": "math",
                "expected_semantic_role": "knowledge",
                "expected_presentation_kind": "text",
                "expected_disposition": "processable",
                "expected_route_candidate": "knowledge_transcription",
                "expected_relations": [],
                "expected_needs_role_review": False,
            },
        ]
        predictions = [
            {
                "case_id": "verified",
                "semantic_role": "exercise",
                "presentation_kind": "text",
                "disposition": "processable",
                "route_candidate": "question_splitter",
                "effective_route_candidate": "question_splitter",
                "needs_role_review": False,
                "hard_constraints_passed": True,
                "confidence": 0.82,
                "relations": [],
            },
            {
                "case_id": "candidate",
                "semantic_role": "wrong",
                "presentation_kind": "wrong",
                "disposition": "wrong",
                "route_candidate": "wrong",
                "effective_route_candidate": "wrong",
                "needs_role_review": False,
                "hard_constraints_passed": True,
                "confidence": 1.0,
                "relations": [],
            },
        ]
        metrics = compute_metrics(cases, predictions)
        self.assertEqual(metrics["verified_case_count"], 1)
        self.assertEqual(metrics["role_exact_match_accuracy"], 1.0)

    def test_expected_fields_do_not_change_prediction_input_or_prediction(self) -> None:
        base = json.loads(DEFAULT_CASES.read_text(encoding="utf-8-sig"))[0]
        base_node = _case_to_node(base)
        base_prediction = predict_case(base, "gold_leakage_metamorphic")
        mutations = {
            "expected_semantic_role": "exercise",
            "expected_presentation_kind": "table",
            "expected_disposition": "structurally_blocked",
            "expected_route_candidate": "review_only",
            "expected_relations": [{"type": "explains", "target_node_id": "mutated"}],
            "expected_needs_role_review": False,
        }
        for field, value in mutations.items():
            mutated = dict(base)
            mutated[field] = value
            self.assertEqual(_case_to_node(mutated), base_node, field)
            self.assertEqual(predict_case(mutated, "gold_leakage_metamorphic"), base_prediction, field)

    def test_fixture_gold_does_not_copy_current_node_type_as_role(self) -> None:
        cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8-sig"))
        copied = [
            case["case_id"]
            for case in cases
            if case["gold_status"] == "VERIFIED" and case["expected_semantic_role"] == case["current_node_type"]
        ]
        self.assertEqual(copied, [])

    def test_non_verified_case_cannot_claim_human_gold_source(self) -> None:
        case = json.loads(DEFAULT_CASES.read_text(encoding="utf-8-sig"))[0]
        case["gold_status"] = "REVIEW_REQUIRED"
        errors = validate_cases([case])
        self.assertIn(f"{case['case_id']}.non_verified_cannot_use_verified_gold_source:fixture_contract", errors)


if __name__ == "__main__":
    unittest.main()
