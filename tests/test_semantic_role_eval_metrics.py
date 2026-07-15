from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.semantic_role_eval_metrics import compute_metrics


class SemanticRoleEvalMetricsTests(unittest.TestCase):
    def test_accuracy_macro_f1_false_safe_and_confusion(self) -> None:
        cases = [
            {
                "case_id": "c1",
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
                "case_id": "c2",
                "evaluation_tier": "VERIFIED_REAL_GOLD",
                "gold_status": "VERIFIED",
                "subject": "math",
                "expected_semantic_role": "knowledge",
                "expected_presentation_kind": "text",
                "expected_disposition": "processable",
                "expected_route_candidate": "knowledge_transcription",
                "expected_relations": [],
                "expected_needs_role_review": True,
            },
            {
                "case_id": "c3",
                "evaluation_tier": "CONTRACT_FIXTURE",
                "gold_status": "UNVERIFIED",
                "subject": "english",
                "expected_semantic_role": "",
                "expected_presentation_kind": "",
                "expected_disposition": "",
                "expected_route_candidate": "",
                "expected_relations": [],
                "expected_needs_role_review": False,
            },
        ]
        predictions = [
            {
                "case_id": "c1",
                "semantic_role": "exercise",
                "presentation_kind": "text",
                "disposition": "processable",
                "route_candidate": "question_splitter",
                "effective_route_candidate": "question_splitter",
                "needs_role_review": False,
                "hard_constraints_passed": True,
                "confidence": 0.84,
                "relations": [],
            },
            {
                "case_id": "c2",
                "semantic_role": "exercise",
                "presentation_kind": "text",
                "disposition": "processable",
                "route_candidate": "question_splitter",
                "effective_route_candidate": "question_splitter",
                "needs_role_review": False,
                "hard_constraints_passed": True,
                "confidence": 0.91,
                "relations": [],
            },
            {
                "case_id": "c3",
                "semantic_role": "unknown",
                "presentation_kind": "unknown",
                "disposition": "review_required",
                "route_candidate": "review_only",
                "effective_route_candidate": "review_only",
                "needs_role_review": True,
                "hard_constraints_passed": False,
                "confidence": 0.2,
                "relations": [],
            },
        ]
        metrics = compute_metrics(cases, predictions)
        self.assertEqual(metrics["verified_case_count"], 2)
        self.assertEqual(metrics["verified_real_gold_case_count"], 2)
        self.assertEqual(metrics["contract_fixture_count"], 1)
        self.assertEqual(metrics["role_exact_match_accuracy"], 0.5)
        self.assertEqual(metrics["false_safe_rate"], 0.5)
        self.assertEqual(metrics["error_capture_rate"], 0.0)
        self.assertEqual(metrics["confusion_matrix"]["knowledge"]["exercise"], 1)
        self.assertEqual(metrics["critical_misroutes"][0]["reasons"], ["knowledge_to_question_splitter"])


if __name__ == "__main__":
    unittest.main()
