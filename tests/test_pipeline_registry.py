from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_pipeline_registry import validate_registry


class PipelineRegistryTests(unittest.TestCase):
    def test_current_registry_validates(self) -> None:
        result = validate_registry(
            ROOT / "config" / "pipeline_registry.yaml",
            ROOT / "config" / "pipeline_feature_flags.yaml",
            ROOT,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["pipeline_count"], 4)
        registry = json.loads((ROOT / "config" / "pipeline_registry.yaml").read_text(encoding="utf-8-sig"))
        entries = {item["pipeline_id"]: item for item in registry["pipelines"]}
        english = entries["english_text_first_v05"]
        self.assertEqual(english["status"], "experimental")
        self.assertFalse(english["runtime_import_policy"]["default_enabled"])
        self.assertFalse(english["database_write_policy"]["default_enabled"])

    def test_duplicate_pipeline_id_fails(self) -> None:
        registry_path = ROOT / "config" / "pipeline_registry.yaml"
        flags_path = ROOT / "config" / "pipeline_feature_flags.yaml"
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        registry["pipelines"].append(dict(registry["pipelines"][0]))
        with tempfile.TemporaryDirectory() as td:
            temp_registry = Path(td) / "pipeline_registry.yaml"
            temp_registry.write_text(json.dumps(registry), encoding="utf-8")
            result = validate_registry(temp_registry, flags_path, ROOT)
        self.assertFalse(result["ok"])
        self.assertTrue(any(error["code"] == "duplicate_pipeline_id" for error in result["errors"]))

    def test_feature_flags_default_false(self) -> None:
        flags = json.loads((ROOT / "config" / "pipeline_feature_flags.yaml").read_text(encoding="utf-8-sig"))
        self.assertTrue(flags["defaults_are_safe"])
        for flag_id, flag in flags["flags"].items():
            self.assertIs(flag["default"], False, flag_id)


if __name__ == "__main__":
    unittest.main()
