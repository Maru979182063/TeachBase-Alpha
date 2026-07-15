from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_semantic_role_effectiveness_eval import OUTPUT_FILES, run_eval


class SemanticRoleEffectivenessRunTests(unittest.TestCase):
    def test_runner_writes_expected_outputs_without_external_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            exit_code, summary = run_eval(out_root=Path(td), cases_path=ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "fixture_cases.json", run_id="unit_eval", candidate_target=12)
            self.assertIn(exit_code, {0, 10, 20})
            out_dir = Path(td) / "unit_eval"
            for name in OUTPUT_FILES:
                self.assertTrue((out_dir / name).exists(), name)
            self.assertTrue((out_dir / "review_pack" / "index.html").exists())
            manifest = json.loads((out_dir / "evaluation_manifest.json").read_text(encoding="utf-8-sig"))
            self.assertFalse(manifest["model_invoked"])
            self.assertFalse(manifest["paid_model_invoked"])
            self.assertFalse(manifest["database_write_attempted"])
            self.assertFalse(manifest["runtime_import_attempted"])
            self.assertFalse(manifest["business_mutation_allowed"])
            self.assertEqual(summary["verified_case_count"], 12)


if __name__ == "__main__":
    unittest.main()
