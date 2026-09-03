#!/usr/bin/env python3
"""Rebuild deterministic synthetic contract fixtures.

The generated package is for validator tests only and must never be presented
as a production Release Seed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "minimal_valid"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def payload_hash() -> str:
    names = (
        "questions.jsonl",
        "question_relations.jsonl",
        "source_documents.jsonl",
        "source_regions.jsonl",
        "rejected_questions.jsonl",
    )
    paths = [PACKAGE / name for name in names]
    paths.extend(sorted(path for path in (PACKAGE / "assets").rglob("*") if path.is_file()))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(PACKAGE).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    assets = PACKAGE / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    source_bytes = b'{"fixture":"synthetic-contract-only","questionId":"q-001"}\n'
    source_asset = assets / "manual-source.json"
    source_asset.write_bytes(source_bytes)
    asset_sha = hashlib.sha256(source_bytes).hexdigest()
    declared_hash = hashlib.sha256(b"shared-foundation-placeholder:q-001").hexdigest()
    question = {
        "externalKey": "manual_seed:fixture:q-001",
        "sourceSystem": "manual_seed",
        "sourceKey": f"fixture-batch:{asset_sha}:record:q-001",
        "contentHash": declared_hash,
        "taggerInputHash": declared_hash,
        "originalFileSha256": asset_sha,
        "sourceLocator": {"kind": "businessId", "value": "q-001"},
        "sourceDocumentKey": "fixture-document-001",
        "sourceRegionKey": "fixture-region-001",
        "original": {
            "prompt": "合成合同样例：1 + 1 = ?",
            "material": None,
            "options": [
                {"key": "A", "text": "1"},
                {"key": "B", "text": "2"}
            ],
            "answer": "B",
            "explanation": "仅用于结构校验。",
            "formulaRefs": [],
            "imageRefs": []
        },
        "difficultyStars": 1,
        "primaryKnowledgeTag": "fixture/math/arithmetic",
        "secondaryKnowledgeTags": [],
        "tagging": {
            "confidence": 1.0,
            "taggerName": "synthetic-fixture-tagger",
            "taggerVersion": "1.0.0",
            "taggerInputHash": declared_hash,
            "needsHumanReview": False
        },
        "review": {
            "reviewStatus": "approved",
            "reviewerId": "fixture-reviewer",
            "reviewedAt": "2026-09-01T00:00:00Z",
            "reviewPolicyVersion": "fixture-policy-v1"
        }
    }
    source_document = {
        "sourceDocumentKey": "fixture-document-001",
        "sourceSystem": "manual_seed",
        "originalFileSha256": asset_sha,
        "assetPath": "assets/manual-source.json",
        "assetSha256": asset_sha,
        "mediaType": "application/json"
    }
    source_region = {
        "sourceRegionKey": "fixture-region-001",
        "sourceDocumentKey": "fixture-document-001",
        "locator": {"kind": "businessId", "value": "q-001"}
    }
    write_jsonl(PACKAGE / "questions.jsonl", [question])
    write_jsonl(PACKAGE / "question_relations.jsonl", [])
    write_jsonl(PACKAGE / "source_documents.jsonl", [source_document])
    write_jsonl(PACKAGE / "source_regions.jsonl", [source_region])
    write_jsonl(PACKAGE / "rejected_questions.jsonl", [])
    content_sha = payload_hash()
    batch_id = "synthetic-contract-fixture-001"
    release_version = "fixture-v1"
    manifest = {
        "schemaVersion": "teachbase.release-seed.v1",
        "batchId": batch_id,
        "releaseVersion": release_version,
        "generatedAt": "2026-09-01T00:00:00Z",
        "questionCount": 1,
        "approvedQuestionCount": 1,
        "rejectedQuestionCount": 0,
        "pendingReviewQuestionCount": 0,
        "sourceSystems": ["manual_seed"],
        "contentSha256": content_sha,
        "assetCount": 1,
        "taggerName": "synthetic-fixture-tagger",
        "taggerVersion": "1.0.0",
        "taggerInputHash": declared_hash,
        "reviewedBy": "fixture-reviewer",
        "reviewedAt": "2026-09-01T00:00:00Z",
        "reviewPolicyVersion": "fixture-policy-v1"
    }
    write_json(PACKAGE / "manifest.json", manifest)
    write_json(PACKAGE / "validation_report.json", {
        "batchId": batch_id,
        "releaseVersion": release_version,
        "packageContentSha256": content_sha,
        "validatorName": "fixture-builder",
        "validatorVersion": "1.0.0",
        "validatedAt": "2026-09-01T00:00:00Z",
        "passed": True,
        "errorCount": 0
    })
    write_json(PACKAGE / "review_report.json", {
        "batchId": batch_id,
        "releaseVersion": release_version,
        "packageContentSha256": content_sha,
        "reviewerId": "fixture-reviewer",
        "reviewedAt": "2026-09-01T00:00:00Z",
        "reviewPolicyVersion": "fixture-policy-v1",
        "reviewMode": "full",
        "sampleSize": 1,
        "approvedQuestionCount": 1,
        "rejectedQuestionCount": 0,
        "issueCounts": {}
    })


if __name__ == "__main__":
    main()
