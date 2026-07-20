from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "english_text_first_knowledge_structure_contract_v02"
QBANK_AS_IS_STATUSES = {"READY", "UNSUPPORTED_AS_IS", "NEEDS_REVIEW", "BLOCKED"}
DERIVATION_STATUSES = {"NOT_APPLICABLE", "CANDIDATE", "NEEDS_REVIEW", "READY_FOR_GENERATION"}
KNOWLEDGE_STATUSES = {
    "READY",
    "READY_WITH_SOURCE_REGIONS",
    "READY_WITH_ASSET",
    "NEEDS_REVIEW",
    "NEEDS_REVIEW_WITH_SOURCE_REGIONS",
    "BLOCKED",
}
FAITHFUL_STATUSES = {
    "READY",
    "READY_WITH_SOURCE_REGIONS",
    "READY_WITH_ASSET",
    "NEEDS_REVIEW",
    "NEEDS_REVIEW_WITH_SOURCE_REGIONS",
    "PRESERVE_PARTIAL_FRAGMENT",
    "BLOCKED",
}
KNOWLEDGE_ROLES = {
    "ANCHOR_NODE",
    "STRUCTURE_NODE",
    "PRESERVE_AS_CHILD_ACTIVITY",
    "PRESERVE_AS_REFERENCE",
    "LINKED_PRACTICE",
    "NOT_APPLICABLE",
}
PREDICATES = {
    "contains",
    "answers",
    "explained_by",
    "depends_on",
    "aligned_to",
    "practices",
    "uses_asset",
    "follows",
    "continues_on",
    "derived_from",
    "shares_context",
    "other",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def contract_schema() -> dict[str, Any]:
    bbox = {
        "type": "array",
        "minItems": 4,
        "maxItems": 4,
        "items": {"type": "number", "minimum": 0, "maximum": 1000},
    }
    confidence = {"type": "number", "minimum": 0, "maximum": 1}
    projection = {
        "type": "object",
        "required": ["status", "capability_level", "reason", "blocking_requirements"],
        "properties": {
            "status": {"type": "string"},
            "capability_level": {"type": "string"},
            "reason": {"type": "string"},
            "blocking_requirements": {"type": "array"},
        },
        "additionalProperties": True,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_VERSION}.schema.json",
        "type": "object",
        "required": ["schema", "documents", "model_calls", "validation_summary"],
        "properties": {
            "schema": {"const": f"{SCHEMA_VERSION}.projection"},
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "doc_id",
                        "requested_page_range_capture_status",
                        "source_page_images",
                        "source_bundles",
                        "source_regions",
                        "source_region_groups",
                        "asset_groups",
                        "semantic_objects",
                        "relations",
                        "uncertainties",
                        "model_call_refs",
                    ],
                    "properties": {
                        "doc_id": {"type": "string", "minLength": 1},
                        "requested_page_range_capture_status": {
                            "enum": ["COMPLETE", "PARTIAL", "UNKNOWN"]
                        },
                        "source_page_images": {"type": "array"},
                        "source_bundles": {"type": "array"},
                        "source_regions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "evidence_id",
                                    "source_bundle_id",
                                    "page_id",
                                    "page_number",
                                    "region_id",
                                    "bbox_norm1000",
                                    "role",
                                    "source_kind",
                                    "verification_status",
                                ],
                                "properties": {
                                    "evidence_id": {"type": "string", "minLength": 1},
                                    "source_bundle_id": {"type": "string"},
                                    "page_id": {"type": "string"},
                                    "page_number": {"type": "integer", "minimum": 1},
                                    "region_id": {"type": "string"},
                                    "bbox_norm1000": bbox,
                                    "role": {"type": "string"},
                                    "source_kind": {"enum": ["original_page", "derived_asset"]},
                                    "verification_status": {"enum": ["VERIFIED", "PROPOSED", "REJECTED"]},
                                },
                                "additionalProperties": True,
                            },
                        },
                        "semantic_objects": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "object_id",
                                    "open_description",
                                    "primary_role",
                                    "source_bundle_refs",
                                    "typed_evidence_refs",
                                    "source_region_group_refs",
                                    "asset_group_refs",
                                    "completeness",
                                    "projections",
                                    "human_review_status",
                                ],
                                "properties": {
                                    "object_id": {"type": "string", "minLength": 1},
                                    "open_description": {"type": "string"},
                                    "primary_role": {
                                        "type": "object",
                                        "required": ["label", "confidence"],
                                        "properties": {
                                            "label": {"type": "string"},
                                            "confidence": confidence,
                                        },
                                        "additionalProperties": True,
                                    },
                                    "source_bundle_refs": {"type": "array", "items": {"type": "string"}},
                                    "typed_evidence_refs": {"type": "array", "items": {"type": "string"}},
                                    "source_region_group_refs": {"type": "array", "items": {"type": "string"}},
                                    "asset_group_refs": {"type": "array", "items": {"type": "string"}},
                                    "completeness": {"type": "object"},
                                    "projections": {
                                        "type": "object",
                                        "required": [
                                            "qbank_projection",
                                            "derivation",
                                            "knowledge_structure",
                                            "faithful_material",
                                        ],
                                        "properties": {
                                            "qbank_projection": {"type": "object"},
                                            "derivation": {"type": "object"},
                                            "knowledge_structure": projection,
                                            "faithful_material": projection,
                                        },
                                    },
                                    "human_review_status": {"enum": ["NOT_REVIEWED", "REQUIRED", "ACCEPTED", "REJECTED"]},
                                },
                                "additionalProperties": True,
                            },
                        },
                    },
                    "additionalProperties": True,
                },
            },
            "model_calls": {"type": "array"},
            "validation_summary": {"type": "object"},
        },
        "additionalProperties": True,
    }


def minimal_json_schema_errors(payload: Any) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(payload, dict):
        return [{"path": "$", "message": "payload must be object"}]
    for key in ("schema", "documents", "model_calls", "validation_summary"):
        if key not in payload:
            errors.append({"path": "$", "message": f"missing {key}"})
    if payload.get("schema") != f"{SCHEMA_VERSION}.projection":
        errors.append({"path": "$.schema", "message": "schema const mismatch"})
    if not isinstance(payload.get("documents"), list):
        errors.append({"path": "$.documents", "message": "documents must be array"})
        return errors
    for d_index, doc in enumerate(payload["documents"]):
        path = f"$.documents[{d_index}]"
        if not isinstance(doc, dict):
            errors.append({"path": path, "message": "document must be object"})
            continue
        for key in (
            "doc_id",
            "requested_page_range_capture_status",
            "source_page_images",
            "source_bundles",
            "source_regions",
            "source_region_groups",
            "asset_groups",
            "semantic_objects",
            "relations",
            "uncertainties",
            "model_call_refs",
        ):
            if key not in doc:
                errors.append({"path": path, "message": f"missing {key}"})
        if doc.get("requested_page_range_capture_status") not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
            errors.append({"path": path + ".requested_page_range_capture_status", "message": "invalid capture status"})
        for o_index, obj in enumerate(doc.get("semantic_objects", []) or []):
            opath = f"{path}.semantic_objects[{o_index}]"
            if not isinstance(obj, dict):
                errors.append({"path": opath, "message": "semantic object must be object"})
                continue
            for key in (
                "object_id",
                "open_description",
                "primary_role",
                "source_bundle_refs",
                "typed_evidence_refs",
                "source_region_group_refs",
                "asset_group_refs",
                "completeness",
                "projections",
                "human_review_status",
            ):
                if key not in obj:
                    errors.append({"path": opath, "message": f"missing {key}"})
            confidence = obj.get("primary_role", {}).get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                errors.append({"path": opath + ".primary_role.confidence", "message": "confidence must be 0..1"})
    return errors
