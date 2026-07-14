from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_semantic_role_adapter_shadow as shadow_runner
from tools.semantic_shadow_compare import compare_artifact_sets


READY_ROOT = ROOT / "outputs" / "pipeline_baseline_snapshot" / "control_plane_20260714_v02" / "deterministic_english_mock_p5_6"
READY_DOC_ROOT = READY_ROOT / "docs" / "english"
REVIEW_ROOT = ROOT / "outputs" / "pipeline_baseline_snapshot" / "semantic_shadow_review_path_20260714_v01"
REVIEW_DOC_ROOT = REVIEW_ROOT / "docs" / "synthetic_review"
READY_ARTIFACTS = [
    "docs/english/assignments.json",
    "docs/english/semantic_nodes.json",
    "docs/english/audit_report.json",
    "legacy_bridge_questions.json",
    "review_repair_pool.json",
]
REVIEW_ARTIFACTS = [
    "docs/synthetic_review/assignments.json",
    "docs/synthetic_review/semantic_nodes.json",
    "docs/synthetic_review/audit_report.json",
    "legacy_bridge_questions.json",
    "review_repair_pool.json",
]


def copy_core_artifacts(src_root: Path, rels: list[str], dst_root: Path) -> None:
    for rel in rels:
        src = src_root / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


class SemanticRoleShadowIsolationTests(unittest.TestCase):
    def test_review_path_baseline_has_review_and_quarantine_coverage(self) -> None:
        manifest = json.loads((REVIEW_ROOT / "baseline_manifest.json").read_text(encoding="utf-8-sig"))
        metrics = manifest["metrics"]
        self.assertEqual(manifest["baseline_type"], "deterministic")
        self.assertFalse(manifest["paid_vlm_used"])
        self.assertEqual(manifest["actual_vlm_calls"], 0)
        self.assertGreater(metrics["review_status"]["NEEDS_REVIEW"], 0)
        self.assertGreater(metrics["review_status"]["QUARANTINED"], 0)
        self.assertGreater(metrics["review_repair_pool_count"], 0)
        self.assertIn("page_bottom_may_continue", metrics["review_reasons"])
        self.assertIn("orphan_unresolved", metrics["review_reasons"])

    def test_ready_path_experiments_off_canonical_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            current_root = Path(td) / "ready_current"
            copy_core_artifacts(READY_ROOT, READY_ARTIFACTS, current_root)
            original_resolver = shadow_runner.resolve_document_profile
            original_adapter = shadow_runner.run_semantic_role_adapter_shadow
            shadow_runner.resolve_document_profile = lambda **_: (_ for _ in ()).throw(AssertionError("resolver_called"))
            shadow_runner.run_semantic_role_adapter_shadow = lambda **_: (_ for _ in ()).throw(AssertionError("adapter_called"))
            try:
                result = shadow_runner.run_shadow(
                    stable_root=READY_ROOT,
                    doc_root=READY_DOC_ROOT,
                    current_root=current_root,
                    out_root=Path(td) / "shadow",
                    enable_shadow=False,
                )
            finally:
                shadow_runner.resolve_document_profile = original_resolver
                shadow_runner.run_semantic_role_adapter_shadow = original_adapter
            self.assertFalse(result["shadow_enabled"])
            self.assertFalse(result["document_profile_resolver_called"])
            self.assertFalse(result["semantic_role_adapter_called"])
            self.assertFalse(result["visual_semantic_assignments_v03_called"])
            self.assertTrue(result["non_interference"]["equality"], result)
            self.assertEqual(result["non_interference"]["compared_artifact_count"], 5)

    def test_review_path_experiments_off_canonical_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            current_root = Path(td) / "review_current"
            copy_core_artifacts(REVIEW_ROOT, REVIEW_ARTIFACTS, current_root)
            result = shadow_runner.run_shadow(
                stable_root=REVIEW_ROOT,
                doc_root=REVIEW_DOC_ROOT,
                current_root=current_root,
                out_root=Path(td) / "shadow",
                enable_shadow=False,
            )
            self.assertTrue(result["non_interference"]["equality"], result)
            self.assertEqual(result["non_interference"]["mismatch_json_paths"], [])

    def test_shadow_on_writes_only_allowed_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            current_root = Path(td) / "review_current"
            out_root = Path(td) / "semantic_role_shadow"
            copy_core_artifacts(REVIEW_ROOT, REVIEW_ARTIFACTS, current_root)
            result = shadow_runner.run_shadow(
                stable_root=REVIEW_ROOT,
                doc_root=REVIEW_DOC_ROOT,
                current_root=current_root,
                out_root=out_root,
                run_id="unit_shadow_on",
                enable_shadow=True,
            )
            sidecar_dir = out_root / "unit_shadow_on"
            self.assertEqual(set(path.name for path in sidecar_dir.iterdir()), set(shadow_runner.ALLOWED_SIDECARS))
            for path in sidecar_dir.iterdir():
                self.assertIn(sidecar_dir.resolve(), [path.resolve(), *path.resolve().parents])
            self.assertTrue(result["non_interference"]["equality"], result)

    def test_review_reasons_and_repair_pool_non_interference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            current_root = Path(td) / "review_current"
            copy_core_artifacts(REVIEW_ROOT, REVIEW_ARTIFACTS, current_root)
            report = compare_artifact_sets(REVIEW_ROOT, current_root, REVIEW_ARTIFACTS, roots=[ROOT, REVIEW_ROOT, current_root])
            repair_pool = json.loads((current_root / "review_repair_pool.json").read_text(encoding="utf-8-sig"))
            reasons = [
                reason
                for item in repair_pool["items"]
                for reason in item.get("review_reasons", [])
            ]
            self.assertTrue(report["equality"], report)
            self.assertEqual(reasons, ["page_bottom_may_continue", "orphan_unresolved"])
            self.assertEqual(len(repair_pool["items"]), 2)

    def test_registry_declares_shadow_output_ownership(self) -> None:
        registry = json.loads((ROOT / "config" / "pipeline_registry.yaml").read_text(encoding="utf-8-sig"))
        pipelines = {item["pipeline_id"]: item for item in registry["pipelines"]}
        shadow = pipelines["semantic_role_shadow"]
        self.assertEqual(shadow["status"], "shadow")
        self.assertEqual(shadow["owned_output_roots"], ["outputs/semantic_role_shadow"])
        self.assertEqual(shadow["database_write_policy"]["policy"], "forbidden")
        self.assertEqual(shadow["runtime_import_policy"]["policy"], "forbidden")
        self.assertEqual(shadow["release_gate_policy"], "no_effect")
        self.assertEqual(shadow["feature_flags"], ["semantic_role_adapter_shadow"])


if __name__ == "__main__":
    unittest.main()
