#!/usr/bin/env python3
"""Join manual source records with difficulty/knowledge enrichment outputs.

The adapter performs exact-key joins and provenance checks only.  It never
modifies original question fields and never promotes a record to approved.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


PROTECTED_SOURCE_FIELDS = {
    "sourceSystem",
    "sourceKey",
    "contentHash",
    "originalFileSha256",
    "sourceLocator",
    "original",
    "prompt",
    "stem",
    "material",
    "options",
    "answer",
    "explanation",
    "formulaRefs",
    "imageRefs",
}
KNOWLEDGE_FIELDS = {
    "primaryKnowledgeTag",
    "secondaryKnowledgeTags",
    "confidence",
    "taggerName",
    "taggerVersion",
    "taggerInputHash",
    "needsHumanReview",
}
DIFFICULTY_FIELDS = {
    "difficultyStars",
    "confidence",
    "taggerName",
    "taggerVersion",
    "taggerInputHash",
    "needsHumanReview",
}


class MergeContractError(ValueError):
    pass


def read_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise MergeContractError(f"{path.name}: JSON root must be an object array")
        return value
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise MergeContractError(f"{path.name}:{line_number}: JSONL row must be an object")
        records.append(value)
    return records


def index_by_external_key(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records, start=1):
        external_key = record.get("externalKey")
        if not isinstance(external_key, str) or not external_key:
            raise MergeContractError(f"{label}:{index}: externalKey is required")
        if external_key in indexed:
            raise MergeContractError(f"{label}:{index}: duplicate externalKey '{external_key}'")
        indexed[external_key] = record
    return indexed


def validate_enrichment(
    record: dict[str, Any],
    allowed_fields: set[str],
    label: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    forbidden = sorted(PROTECTED_SOURCE_FIELDS.intersection(record))
    if forbidden:
        raise MergeContractError(f"{label}: enrichment attempts to supply protected source fields: {forbidden}")
    unexpected = sorted(set(record) - allowed_fields - {"externalKey"})
    if unexpected:
        raise MergeContractError(f"{label}: unexpected enrichment fields: {unexpected}")
    declared_hash = record.get("taggerInputHash")
    source_hash = source.get("taggerInputHash")
    if not isinstance(source_hash, str) or not source_hash:
        raise MergeContractError(f"{label}: source record does not declare taggerInputHash")
    if declared_hash != source_hash:
        raise MergeContractError(f"{label}: taggerInputHash does not match the source declaration")
    return {key: copy.deepcopy(value) for key, value in record.items() if key != "externalKey"}


def merge_records(
    source_records: list[dict[str, Any]],
    knowledge_records: list[dict[str, Any]],
    difficulty_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_index = index_by_external_key(source_records, "source")
    knowledge_index = index_by_external_key(knowledge_records, "knowledge")
    difficulty_index = index_by_external_key(difficulty_records, "difficulty")
    unknown = sorted((set(knowledge_index) | set(difficulty_index)) - set(source_index))
    if unknown:
        raise MergeContractError(f"enrichment contains unknown externalKey values: {unknown}")

    merged: list[dict[str, Any]] = []
    missing_knowledge: list[str] = []
    missing_difficulty: list[str] = []
    needs_human_review: list[str] = []
    for external_key, source in source_index.items():
        candidate = copy.deepcopy(source)
        candidate["releaseSeedDisposition"] = "pending_review"
        candidate["enrichment"] = {}
        knowledge = knowledge_index.get(external_key)
        difficulty = difficulty_index.get(external_key)
        if knowledge is None:
            missing_knowledge.append(external_key)
        else:
            candidate["enrichment"]["knowledge"] = validate_enrichment(
                knowledge, KNOWLEDGE_FIELDS, f"knowledge[{external_key}]", source
            )
        if difficulty is None:
            missing_difficulty.append(external_key)
        else:
            candidate["enrichment"]["difficulty"] = validate_enrichment(
                difficulty, DIFFICULTY_FIELDS, f"difficulty[{external_key}]", source
            )
        flags = [
            item.get("needsHumanReview")
            for item in candidate["enrichment"].values()
            if isinstance(item, dict)
        ]
        is_incomplete = knowledge is None or difficulty is None
        if is_incomplete or any(flag is not False for flag in flags):
            needs_human_review.append(external_key)
        merged.append(candidate)

    report = {
        "schemaVersion": "teachbase.release-seed.enrichment-merge-report.v1",
        "sourceCount": len(source_records),
        "knowledgeMatchedCount": len(source_records) - len(missing_knowledge),
        "difficultyMatchedCount": len(source_records) - len(missing_difficulty),
        "pendingReviewCount": len(merged),
        "approvedCount": 0,
        "missingKnowledgeExternalKeys": missing_knowledge,
        "missingDifficultyExternalKeys": missing_difficulty,
        "needsHumanReviewExternalKeys": needs_human_review,
        "invariants": {
            "originalQuestionFieldsCopiedWithoutMutation": True,
            "approvalNeverAssignedByAdapter": True,
            "semanticDefaultsInjected": False,
            "taggerInputHashAlgorithmDeferredToSharedFoundation": True,
        },
    }
    return merged, report


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--difficulty", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        merged, report = merge_records(
            read_records(args.source), read_records(args.knowledge), read_records(args.difficulty)
        )
        write_jsonl(args.output, merged)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, MergeContractError) as exc:
        print(f"merge failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
