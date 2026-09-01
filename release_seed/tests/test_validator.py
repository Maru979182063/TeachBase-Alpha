from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_SEED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_SEED))

from validator import validate_package  # noqa: E402


FIXTURE = RELEASE_SEED / "fixtures" / "minimal_valid"


class ValidatorTests(unittest.TestCase):
    def copy_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        package = Path(temporary.name) / "package"
        shutil.copytree(FIXTURE, package)
        return temporary, package

    def rewrite_json(self, path: Path, mutate) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def rewrite_first_jsonl(self, path: Path, mutate) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        value = json.loads(lines[0])
        mutate(value)
        lines[0] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_minimal_fixture_is_valid(self) -> None:
        result = validate_package(FIXTURE)
        self.assertTrue(result.passed, result.errors)
        self.assertEqual(1, result.counts["approvedQuestions"])

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        temporary, package = self.copy_fixture()
        self.addCleanup(temporary.cleanup)
        self.rewrite_json(package / "manifest.json", lambda value: value.update(contentSha256="0" * 64))
        result = validate_package(package)
        self.assertFalse(result.passed)
        self.assertTrue(any("contentSha256 does not match" in error for error in result.errors))

    def test_difficulty_out_of_range_and_missing_knowledge_are_rejected(self) -> None:
        temporary, package = self.copy_fixture()
        self.addCleanup(temporary.cleanup)
        self.rewrite_first_jsonl(
            package / "questions.jsonl",
            lambda value: (value.update(difficultyStars=6), value.pop("primaryKnowledgeTag")),
        )
        result = validate_package(package)
        self.assertFalse(result.passed)
        self.assertTrue(any("difficultyStars" in error for error in result.errors))
        self.assertTrue(any("primaryKnowledgeTag" in error for error in result.errors))

    def test_absolute_asset_path_is_rejected(self) -> None:
        temporary, package = self.copy_fixture()
        self.addCleanup(temporary.cleanup)
        self.rewrite_first_jsonl(
            package / "source_documents.jsonl",
            lambda value: value.update(assetPath="C:/private/manual-source.json"),
        )
        result = validate_package(package)
        self.assertFalse(result.passed)
        self.assertTrue(any("portable assets/ path" in error for error in result.errors))

    def test_missing_or_changed_asset_is_rejected(self) -> None:
        temporary, package = self.copy_fixture()
        self.addCleanup(temporary.cleanup)
        (package / "assets" / "manual-source.json").write_bytes(b"changed")
        result = validate_package(package)
        self.assertFalse(result.passed)
        self.assertTrue(any("asset SHA-256 mismatch" in error for error in result.errors))

    def test_unknown_relation_reference_is_rejected(self) -> None:
        temporary, package = self.copy_fixture()
        self.addCleanup(temporary.cleanup)
        relation = {
            "fromExternalKey": "manual_seed:fixture:q-001",
            "toExternalKey": "missing-question",
            "relationType": "variant",
        }
        (package / "question_relations.jsonl").write_text(
            json.dumps(relation) + "\n", encoding="utf-8"
        )
        result = validate_package(package)
        self.assertFalse(result.passed)
        self.assertTrue(any("unknown question" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
