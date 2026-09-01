from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


RELEASE_SEED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_SEED))

from merge_enrichments_v1 import MergeContractError, merge_records  # noqa: E402


HASH = "1" * 64
SOURCE = {
    "externalKey": "manual_seed:batch:q-001",
    "sourceSystem": "manual_seed",
    "sourceKey": "batch:filehash:business:q-001",
    "contentHash": "2" * 64,
    "taggerInputHash": HASH,
    "original": {"prompt": "原题不得改写", "answer": "A"},
}
KNOWLEDGE = {
    "externalKey": SOURCE["externalKey"],
    "primaryKnowledgeTag": "math/algebra",
    "secondaryKnowledgeTags": [],
    "confidence": 0.9,
    "taggerName": "knowledge-tagger",
    "taggerVersion": "1.0",
    "taggerInputHash": HASH,
    "needsHumanReview": False,
}
DIFFICULTY = {
    "externalKey": SOURCE["externalKey"],
    "difficultyStars": 3,
    "confidence": 0.8,
    "taggerName": "difficulty-tagger",
    "taggerVersion": "1.0",
    "taggerInputHash": HASH,
    "needsHumanReview": False,
}


class MergeEnrichmentTests(unittest.TestCase):
    def test_complete_merge_preserves_source_and_never_approves(self) -> None:
        original = copy.deepcopy(SOURCE)
        merged, report = merge_records([SOURCE], [KNOWLEDGE], [DIFFICULTY])
        self.assertEqual(original["original"], merged[0]["original"])
        self.assertEqual("pending_review", merged[0]["releaseSeedDisposition"])
        self.assertEqual(0, report["approvedCount"])

    def test_missing_output_stays_pending_without_defaults(self) -> None:
        merged, report = merge_records([SOURCE], [], [DIFFICULTY])
        self.assertNotIn("knowledge", merged[0]["enrichment"])
        self.assertEqual([SOURCE["externalKey"]], report["missingKnowledgeExternalKeys"])
        self.assertEqual([SOURCE["externalKey"]], report["needsHumanReviewExternalKeys"])

    def test_body_fields_from_model_are_rejected(self) -> None:
        modified = dict(KNOWLEDGE)
        modified["original"] = {"prompt": "模型改写后的题干"}
        with self.assertRaisesRegex(MergeContractError, "protected source fields"):
            merge_records([SOURCE], [modified], [DIFFICULTY])

    def test_mismatched_tagger_input_hash_is_rejected(self) -> None:
        modified = dict(DIFFICULTY)
        modified["taggerInputHash"] = "3" * 64
        with self.assertRaisesRegex(MergeContractError, "does not match"):
            merge_records([SOURCE], [KNOWLEDGE], [modified])


if __name__ == "__main__":
    unittest.main()
