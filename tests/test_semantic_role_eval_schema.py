from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_semantic_role_effectiveness_eval import DEFAULT_CASES, REQUIRED_FIELDS, validate_cases
from tools.semantic_profile_config import load_semantic_profile_configs, semantic_enums


class SemanticRoleEvalSchemaTests(unittest.TestCase):
    def test_fixture_cases_satisfy_required_fields_and_enums(self) -> None:
        cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8-sig"))
        errors = validate_cases(cases)
        self.assertEqual(errors, [])
        configs = load_semantic_profile_configs()
        enums = semantic_enums(configs)
        for case in cases:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, case)
            self.assertIn(case["expected_semantic_role"], enums["semantic_roles"])
            self.assertIn(case["expected_presentation_kind"], enums["presentation_kinds"])
            self.assertIn(case["expected_disposition"], enums["dispositions"])
            self.assertIn(case["expected_route_candidate"], enums["routes"])

    def test_verified_cases_require_gold_evidence(self) -> None:
        case = json.loads(DEFAULT_CASES.read_text(encoding="utf-8-sig"))[0]
        case["gold_evidence"] = []
        errors = validate_cases([case])
        self.assertIn(f"{case['case_id']}.verified_requires_gold_evidence", errors)


if __name__ == "__main__":
    unittest.main()
