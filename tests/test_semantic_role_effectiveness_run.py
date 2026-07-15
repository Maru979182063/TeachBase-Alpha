from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_semantic_role_effectiveness_eval import OUTPUT_FILES, run_eval, write_candidate_manifest


class SemanticRoleEffectivenessRunTests(unittest.TestCase):
    def test_runner_writes_expected_outputs_without_external_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            exit_code, summary = run_eval(out_root=Path(td), cases_path=ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "fixture_cases.json", run_id="unit_eval")
            self.assertEqual(exit_code, 20)
            self.assertEqual(summary["status"], "SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED")
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
            self.assertEqual(summary["verified_real_gold_case_count"], 0)
            self.assertEqual(summary["contract_fixture_count"], 12)

    def test_candidate_discovery_is_manifest_driven_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "candidate_root"
            nested = root / "run_a"
            nested.mkdir(parents=True)
            semantic_nodes = nested / "semantic_nodes.json"
            semantic_nodes.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"node_id": "node_b", "node_type": "question", "review_status": "NEEDS_REVIEW", "fragments": [{"page": 2}], "text_stub": "B"},
                            {"node_id": "node_a", "node_type": "content_block", "review_status": "AUDITED_READY", "fragments": [{"page": 1}], "text_stub": "A"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manifest_a = write_candidate_manifest([root], Path(td) / "candidate_manifest_a.json")
            manifest_b = write_candidate_manifest([root], Path(td) / "candidate_manifest_b.json")

            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual([row["node_id"] for row in manifest_a["candidates"]], ["node_a", "node_b"])
            for row in manifest_a["candidates"]:
                self.assertRegex(row["source_artifact_sha256"], r"^[0-9a-f]{64}$")

            exit_code, summary = run_eval(
                out_root=Path(td),
                cases_path=ROOT / "tests" / "fixtures" / "semantic_role_effectiveness_v01" / "fixture_cases.json",
                run_id="unit_eval_with_manifest",
                candidate_manifest_path=Path(td) / "candidate_manifest_a.json",
            )
            self.assertEqual(exit_code, 20)
            self.assertEqual(summary["candidate_case_count"], 14)


if __name__ == "__main__":
    unittest.main()
