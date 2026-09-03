#!/usr/bin/env python3
"""Offline structural validator for a TeachBase Release Seed V1 package.

This module deliberately avoids semantic label judgment.  It validates the
portable package contract, provenance, references, declared review binding and
byte-level package hashes.  Per-question content-hash calculation is deferred
to the shared question/hash foundation and is therefore format-checked only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "teachbase.release-seed.v1"
VALIDATOR_NAME = "teachbase-release-seed-offline-validator"
VALIDATOR_VERSION = "1.0.0"
PAYLOAD_FILES = (
    "questions.jsonl",
    "question_relations.jsonl",
    "source_documents.jsonl",
    "source_regions.jsonl",
    "rejected_questions.jsonl",
)
REQUIRED_PATHS = (
    "manifest.json",
    *PAYLOAD_FILES,
    "assets",
    "validation_report.json",
    "review_report.json",
)


@dataclass
class ValidationResult:
    package: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    computed_content_sha256: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    deferred_checks: list[str] = field(
        default_factory=lambda: [
            "per-question contentHash recomputation (shared hash foundation pending)",
            "taxonomy membership/semantic correctness (shared taxonomy foundation pending)",
            "database idempotency, recovery and search verification (Java Seed Loader deferred)",
        ]
    )

    def error(self, message: str) -> None:
        self.passed = False
        self.errors.append(message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "validatorName": VALIDATOR_NAME,
            "validatorVersion": VALIDATOR_VERSION,
            "package": self.package,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "computedContentSha256": self.computed_content_sha256,
            "counts": self.counts,
            "deferredChecks": self.deferred_checks,
        }


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def is_portable_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    first = path.parts[0] if path.parts else ""
    return not path.is_absolute() and ".." not in path.parts and ":" not in first


def read_json(path: Path, result: ValidationResult) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result.error(f"{path.name}: cannot read UTF-8 JSON: {exc}")
        return None


def read_jsonl(path: Path, result: ValidationResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        result.error(f"{path.name}: cannot read UTF-8 JSONL: {exc}")
        return rows
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            result.error(f"{path.name}:{line_number}: blank lines are not allowed")
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            result.error(f"{path.name}:{line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            result.error(f"{path.name}:{line_number}: each line must be an object")
            continue
        rows.append(value)
    return rows


def payload_content_sha256(package_dir: Path) -> str:
    """Hash the immutable payload as ordered path/byte pairs.

    Manifest and reports are excluded to avoid a self-referential digest.  JSONL
    order is fixed by PAYLOAD_FILES; assets are ordered by portable relative path.
    """

    digest = hashlib.sha256()
    payload_paths = [package_dir / name for name in PAYLOAD_FILES]
    assets_dir = package_dir / "assets"
    if assets_dir.is_dir():
        payload_paths.extend(sorted(path for path in assets_dir.rglob("*") if path.is_file()))
    for path in payload_paths:
        relative = path.relative_to(package_dir).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def require_fields(
    value: dict[str, Any], fields: Iterable[str], context: str, result: ValidationResult
) -> None:
    for name in fields:
        if name not in value:
            result.error(f"{context}: missing required field '{name}'")


def validate_manifest(manifest: Any, result: ValidationResult) -> None:
    if not isinstance(manifest, dict):
        result.error("manifest.json: root must be an object")
        return
    require_fields(
        manifest,
        (
            "schemaVersion",
            "batchId",
            "releaseVersion",
            "generatedAt",
            "questionCount",
            "approvedQuestionCount",
            "rejectedQuestionCount",
            "pendingReviewQuestionCount",
            "sourceSystems",
            "contentSha256",
            "assetCount",
            "taggerName",
            "taggerVersion",
            "taggerInputHash",
            "reviewedBy",
            "reviewedAt",
            "reviewPolicyVersion",
        ),
        "manifest.json",
        result,
    )
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        result.error(f"manifest.json: schemaVersion must be '{SCHEMA_VERSION}'")
    for name in (
        "questionCount",
        "approvedQuestionCount",
        "rejectedQuestionCount",
        "pendingReviewQuestionCount",
        "assetCount",
    ):
        value = manifest.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            result.error(f"manifest.json: {name} must be a non-negative integer")
    if isinstance(manifest.get("questionCount"), int) and manifest["questionCount"] > 500:
        result.error("manifest.json: questionCount exceeds the 500-question batch limit")
    if not is_sha256(manifest.get("contentSha256")):
        result.error("manifest.json: contentSha256 must be a lowercase SHA-256 hex string")
    if not is_sha256(manifest.get("taggerInputHash")):
        result.error("manifest.json: taggerInputHash must be a lowercase SHA-256 hex string")
    systems = manifest.get("sourceSystems")
    if not isinstance(systems, list) or not systems or any(not isinstance(item, str) or not item for item in systems):
        result.error("manifest.json: sourceSystems must be a non-empty string array")


def validate_question(row: dict[str, Any], index: int, result: ValidationResult) -> None:
    context = f"questions.jsonl:{index}"
    require_fields(
        row,
        (
            "externalKey",
            "sourceSystem",
            "sourceKey",
            "contentHash",
            "taggerInputHash",
            "originalFileSha256",
            "sourceLocator",
            "original",
            "difficultyStars",
            "primaryKnowledgeTag",
            "secondaryKnowledgeTags",
            "tagging",
            "review",
        ),
        context,
        result,
    )
    for name in ("externalKey", "sourceSystem", "sourceKey", "primaryKnowledgeTag"):
        if not isinstance(row.get(name), str) or not row.get(name):
            result.error(f"{context}: {name} must be a non-empty string")
    for name in ("contentHash", "taggerInputHash", "originalFileSha256"):
        if not is_sha256(row.get(name)):
            result.error(f"{context}: {name} must be a lowercase SHA-256 hex string")
    difficulty = row.get("difficultyStars")
    if not isinstance(difficulty, int) or isinstance(difficulty, bool) or not 1 <= difficulty <= 5:
        result.error(f"{context}: difficultyStars must be an integer from 1 to 5")
    secondary = row.get("secondaryKnowledgeTags")
    if not isinstance(secondary, list) or any(not isinstance(item, str) or not item for item in secondary):
        result.error(f"{context}: secondaryKnowledgeTags must be a string array")
    locator = row.get("sourceLocator")
    if not isinstance(locator, dict) or not locator:
        result.error(f"{context}: sourceLocator must be a non-empty object")
    original = row.get("original")
    if not isinstance(original, dict) or not isinstance(original.get("prompt"), str) or not original.get("prompt"):
        result.error(f"{context}: original.prompt must be a non-empty string")
    tagging = row.get("tagging")
    if not isinstance(tagging, dict):
        result.error(f"{context}: tagging must be an object")
    else:
        require_fields(
            tagging,
            ("confidence", "taggerName", "taggerVersion", "taggerInputHash", "needsHumanReview"),
            f"{context}.tagging",
            result,
        )
        confidence = tagging.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            result.error(f"{context}.tagging: confidence must be between 0 and 1")
        if tagging.get("taggerInputHash") != row.get("taggerInputHash"):
            result.error(f"{context}.tagging: taggerInputHash must match the question declaration")
        if tagging.get("needsHumanReview") is not False:
            result.error(f"{context}.tagging: approved questions must have needsHumanReview=false")
    review = row.get("review")
    if not isinstance(review, dict):
        result.error(f"{context}: review must be an object")
    else:
        require_fields(
            review,
            ("reviewStatus", "reviewerId", "reviewedAt", "reviewPolicyVersion"),
            f"{context}.review",
            result,
        )
        if review.get("reviewStatus") != "approved":
            result.error(f"{context}.review: questions.jsonl may contain only approved records")
    image_refs = original.get("imageRefs", []) if isinstance(original, dict) else []
    if not isinstance(image_refs, list):
        result.error(f"{context}: original.imageRefs must be an array when present")
    else:
        for image_index, image in enumerate(image_refs, start=1):
            if not isinstance(image, dict):
                result.error(f"{context}: imageRefs[{image_index}] must be an object")
                continue
            if not is_portable_relative_path(image.get("path")) or not str(image.get("path", "")).startswith("assets/"):
                result.error(f"{context}: imageRefs[{image_index}].path must be a portable assets/ path")
            if not is_sha256(image.get("sha256")):
                result.error(f"{context}: imageRefs[{image_index}].sha256 must be lowercase SHA-256")


def ensure_unique(rows: list[dict[str, Any]], field_name: str, file_name: str, result: ValidationResult) -> None:
    seen: set[Any] = set()
    for index, row in enumerate(rows, start=1):
        value = row.get(field_name)
        if value in seen:
            result.error(f"{file_name}:{index}: duplicate {field_name} '{value}'")
        seen.add(value)


def validate_package(package_dir: Path) -> ValidationResult:
    package_dir = package_dir.resolve()
    result = ValidationResult(package=package_dir.name)
    for relative in REQUIRED_PATHS:
        if not (package_dir / relative).exists():
            result.error(f"missing required path: {relative}")
    if result.errors:
        return result

    manifest = read_json(package_dir / "manifest.json", result)
    validation_report = read_json(package_dir / "validation_report.json", result)
    review_report = read_json(package_dir / "review_report.json", result)
    questions = read_jsonl(package_dir / "questions.jsonl", result)
    relations = read_jsonl(package_dir / "question_relations.jsonl", result)
    documents = read_jsonl(package_dir / "source_documents.jsonl", result)
    regions = read_jsonl(package_dir / "source_regions.jsonl", result)
    rejected = read_jsonl(package_dir / "rejected_questions.jsonl", result)

    validate_manifest(manifest, result)
    for index, question in enumerate(questions, start=1):
        validate_question(question, index, result)
    for index, row in enumerate(rejected, start=1):
        context = f"rejected_questions.jsonl:{index}"
        require_fields(
            row,
            ("externalKey", "sourceSystem", "sourceKey", "reviewStatus", "rejectionReasons"),
            context,
            result,
        )
        if row.get("reviewStatus") != "rejected":
            result.error(f"{context}: reviewStatus must be 'rejected'")
        reasons = row.get("rejectionReasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(reason, str) or not reason for reason in reasons):
            result.error(f"{context}: rejectionReasons must be a non-empty string array")
    ensure_unique(questions, "externalKey", "questions.jsonl", result)
    ensure_unique(questions, "sourceKey", "questions.jsonl", result)
    ensure_unique(documents, "sourceDocumentKey", "source_documents.jsonl", result)
    ensure_unique(regions, "sourceRegionKey", "source_regions.jsonl", result)

    question_keys = {row.get("externalKey") for row in questions}
    document_keys = {row.get("sourceDocumentKey") for row in documents}
    region_keys = {row.get("sourceRegionKey") for row in regions}
    for index, relation in enumerate(relations, start=1):
        require_fields(relation, ("fromExternalKey", "toExternalKey", "relationType"), f"question_relations.jsonl:{index}", result)
        if relation.get("fromExternalKey") not in question_keys or relation.get("toExternalKey") not in question_keys:
            result.error(f"question_relations.jsonl:{index}: relation references an unknown question")
    for index, document in enumerate(documents, start=1):
        require_fields(document, ("sourceDocumentKey", "sourceSystem", "originalFileSha256", "assetPath", "assetSha256"), f"source_documents.jsonl:{index}", result)
        asset_path = document.get("assetPath")
        if not is_portable_relative_path(asset_path) or not str(asset_path or "").startswith("assets/"):
            result.error(f"source_documents.jsonl:{index}: assetPath must be a portable assets/ path")
        if not is_sha256(document.get("originalFileSha256")) or not is_sha256(document.get("assetSha256")):
            result.error(f"source_documents.jsonl:{index}: file hashes must be lowercase SHA-256")
    for index, region in enumerate(regions, start=1):
        require_fields(region, ("sourceRegionKey", "sourceDocumentKey", "locator"), f"source_regions.jsonl:{index}", result)
        if region.get("sourceDocumentKey") not in document_keys:
            result.error(f"source_regions.jsonl:{index}: sourceDocumentKey is unknown")
    for index, question in enumerate(questions, start=1):
        document_key = question.get("sourceDocumentKey")
        region_key = question.get("sourceRegionKey")
        if document_key is not None and document_key not in document_keys:
            result.error(f"questions.jsonl:{index}: sourceDocumentKey is unknown")
        if region_key is not None and region_key not in region_keys:
            result.error(f"questions.jsonl:{index}: sourceRegionKey is unknown")

    asset_files = sorted(path for path in (package_dir / "assets").rglob("*") if path.is_file())
    referenced_assets: list[tuple[str, str, str]] = []
    for index, document in enumerate(documents, start=1):
        referenced_assets.append((f"source_documents.jsonl:{index}", document.get("assetPath"), document.get("assetSha256")))
    for index, question in enumerate(questions, start=1):
        original = question.get("original", {})
        for image_index, image in enumerate(original.get("imageRefs", []) if isinstance(original, dict) else [], start=1):
            if isinstance(image, dict):
                referenced_assets.append((f"questions.jsonl:{index}.imageRefs[{image_index}]", image.get("path"), image.get("sha256")))
    for context, relative, expected_hash in referenced_assets:
        if not is_portable_relative_path(relative):
            continue
        asset = package_dir / str(relative)
        if not asset.is_file():
            result.error(f"{context}: referenced asset does not exist: {relative}")
        elif is_sha256(expected_hash) and hashlib.sha256(asset.read_bytes()).hexdigest() != expected_hash:
            result.error(f"{context}: asset SHA-256 mismatch: {relative}")

    if all((package_dir / name).is_file() for name in PAYLOAD_FILES):
        result.computed_content_sha256 = payload_content_sha256(package_dir)
    if isinstance(manifest, dict):
        expected_count = len(questions) + len(rejected)
        count_checks = {
            "questionCount": expected_count,
            "approvedQuestionCount": len(questions),
            "rejectedQuestionCount": len(rejected),
            "assetCount": len(asset_files),
        }
        for field_name, actual in count_checks.items():
            if manifest.get(field_name) != actual:
                result.error(f"manifest.json: {field_name}={manifest.get(field_name)!r}, expected {actual}")
        if manifest.get("pendingReviewQuestionCount") != 0:
            result.error("manifest.json: a frozen package cannot contain pending-review questions")
        if manifest.get("contentSha256") != result.computed_content_sha256:
            result.error("manifest.json: contentSha256 does not match the immutable payload")
        declared_systems = set(manifest.get("sourceSystems", [])) if isinstance(manifest.get("sourceSystems"), list) else set()
        actual_systems = {row.get("sourceSystem") for row in questions + rejected if row.get("sourceSystem")}
        if declared_systems != actual_systems:
            result.error("manifest.json: sourceSystems does not match payload source systems")

    for name, report in (("validation_report.json", validation_report), ("review_report.json", review_report)):
        if not isinstance(report, dict):
            result.error(f"{name}: root must be an object")
            continue
        require_fields(report, ("batchId", "releaseVersion", "packageContentSha256"), name, result)
        if isinstance(manifest, dict):
            if report.get("batchId") != manifest.get("batchId") or report.get("releaseVersion") != manifest.get("releaseVersion"):
                result.error(f"{name}: batch/release binding does not match manifest")
            if report.get("packageContentSha256") != manifest.get("contentSha256"):
                result.error(f"{name}: packageContentSha256 does not match manifest")
    if isinstance(validation_report, dict):
        require_fields(validation_report, ("validatorName", "validatorVersion", "validatedAt", "passed", "errorCount"), "validation_report.json", result)
        if validation_report.get("passed") is not True or validation_report.get("errorCount") != 0:
            result.error("validation_report.json: frozen package must declare passed=true and errorCount=0")
    if isinstance(review_report, dict):
        require_fields(
            review_report,
            ("reviewerId", "reviewedAt", "reviewPolicyVersion", "reviewMode", "sampleSize", "approvedQuestionCount", "rejectedQuestionCount", "issueCounts"),
            "review_report.json",
            result,
        )
        if isinstance(manifest, dict):
            for name in ("reviewerId", "reviewedAt", "reviewPolicyVersion"):
                manifest_name = {"reviewerId": "reviewedBy"}.get(name, name)
                if review_report.get(name) != manifest.get(manifest_name):
                    result.error(f"review_report.json: {name} does not match manifest")
            for name in ("approvedQuestionCount", "rejectedQuestionCount"):
                if review_report.get(name) != manifest.get(name):
                    result.error(f"review_report.json: {name} does not match manifest")

    result.counts = {
        "approvedQuestions": len(questions),
        "rejectedQuestions": len(rejected),
        "relations": len(relations),
        "sourceDocuments": len(documents),
        "sourceRegions": len(regions),
        "assets": len(asset_files),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Release Seed package directory")
    parser.add_argument("--report", type=Path, help="Optional path for the validation result JSON")
    args = parser.parse_args(argv)
    result = validate_package(args.package)
    rendered = json.dumps(result.as_dict(), ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
