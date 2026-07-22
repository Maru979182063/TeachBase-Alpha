from __future__ import annotations

import json
from typing import Any

from english_text_first_normalizer.common import FIELD_REF_KEYS, ORDINARY_STATUS, VISUAL_STATUS, group_ref_list, unique_refs


def fallback_record(doc_id: str, group: dict[str, Any], prompt_version: str, reason: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    group_refs = group_ref_list(group)
    visual_refs = unique_refs(group.get("visual_block_refs", []))
    writing_refs = unique_refs(
        [
            block["block_ref"]
            for block in blocks
            if block.get("block_ref") in group_refs
            and (
                block.get("visual_form") == "writing_surface"
                or block.get("content_role") == "response_surface"
                or block.get("preservation_reason") == "writing_surface_needed"
            )
        ]
    )
    classified = set(
        unique_refs(group.get("anchor_block_refs", []))
        + unique_refs(group.get("solution_block_refs", []))
        + unique_refs(group.get("analysis_block_refs", []))
        + unique_refs(group.get("translation_block_refs", []))
        + unique_refs(group.get("context_block_refs", []))
        + visual_refs
        + writing_refs
    )
    return {
        "schema": "normalized_group_record_v0.1",
        "doc_id": doc_id,
        "document_group_id": group["document_group_id"],
        "prompt_version": prompt_version,
        "record_kind": "fallback_unknown_fields",
        "field_refs": {
            "stem_refs": unique_refs(group.get("anchor_block_refs", [])),
            "option_refs": [],
            "passage_refs": [],
            "answer_refs": unique_refs(group.get("solution_block_refs", [])),
            "analysis_refs": unique_refs(group.get("analysis_block_refs", [])),
            "translation_refs": unique_refs(group.get("translation_block_refs", [])),
            "context_refs": unique_refs(group.get("context_block_refs", [])),
            "instruction_refs": [],
            "example_refs": [],
            "visual_refs": visual_refs,
            "writing_surface_refs": writing_refs,
            "rubric_refs": [],
            "other_evidence_refs": [ref for ref in group_refs if ref not in classified],
        },
        "field_status": {
            "stem": "present" if group.get("anchor_block_refs") else "uncertain",
            "options": "uncertain",
            "passage": "uncertain",
            "answer": "present" if group.get("solution_block_refs") else "missing",
            "analysis": "present" if group.get("analysis_block_refs") else "missing",
            "translation": "present" if group.get("translation_block_refs") else "missing",
            "context": "present" if group.get("context_block_refs") else "uncertain",
            "visual_asset": "required" if visual_refs else "not_required",
            "writing_surface": "required" if writing_refs else "not_required",
        },
        "open_issues": [{"code": "normalizer_model_failed", "message": reason, "source_block_refs": group_refs}],
        "normalizer_warnings": [],
    }


def validate_record(payload: dict[str, Any], *, doc_id: str, group: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    allowed_refs = set(group_ref_list(group))
    if payload.get("schema") != "normalized_group_record_v0.1":
        errors.append({"path": "$.schema", "message": "schema must be normalized_group_record_v0.1"})
    if payload.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if payload.get("document_group_id") != group.get("document_group_id"):
        errors.append({"path": "$.document_group_id", "message": "document_group_id mismatch"})
    if payload.get("prompt_version") != prompt_version:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})
    if not isinstance(payload.get("record_kind"), str) or not payload.get("record_kind", "").strip():
        errors.append({"path": "$.record_kind", "message": "record_kind must be non-empty string"})

    field_refs = payload.get("field_refs")
    if not isinstance(field_refs, dict):
        errors.append({"path": "$.field_refs", "message": "field_refs must be object"})
        field_refs = {}
    seen_refs: list[str] = []
    for key in FIELD_REF_KEYS:
        refs = field_refs.get(key)
        if not isinstance(refs, list):
            errors.append({"path": f"$.field_refs.{key}", "message": "must be array"})
            continue
        for index, ref in enumerate(refs):
            if not isinstance(ref, str) or not ref:
                errors.append({"path": f"$.field_refs.{key}[{index}]", "message": "must be non-empty string"})
                continue
            seen_refs.append(ref)
            if ref not in allowed_refs:
                errors.append({"path": f"$.field_refs.{key}[{index}]", "message": f"ref {ref} is not in document_group"})

    unclassified_refs = sorted(set(group_ref_list(group)) - set(seen_refs))
    if unclassified_refs:
        warnings.append({"path": "$.field_refs", "message": "some group refs were not classified", "refs": unclassified_refs})

    status = payload.get("field_status")
    if not isinstance(status, dict):
        errors.append({"path": "$.field_status", "message": "field_status must be object"})
        status = {}
    for key in ["stem", "options", "passage", "answer", "analysis", "translation", "context"]:
        if status.get(key) not in ORDINARY_STATUS:
            errors.append({"path": f"$.field_status.{key}", "message": f"invalid status {status.get(key)!r}"})
    for key in ["visual_asset", "writing_surface"]:
        if status.get(key) not in VISUAL_STATUS:
            errors.append({"path": f"$.field_status.{key}", "message": f"invalid status {status.get(key)!r}"})

    for list_key in ["open_issues", "normalizer_warnings"]:
        value = payload.get(list_key)
        if not isinstance(value, list):
            errors.append({"path": f"$.{list_key}", "message": "must be array"})
            continue
        for item_index, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append({"path": f"$.{list_key}[{item_index}]", "message": "must be object"})
                continue
            if not isinstance(item.get("code"), str):
                errors.append({"path": f"$.{list_key}[{item_index}].code", "message": "must be string"})
            if not isinstance(item.get("message"), str):
                errors.append({"path": f"$.{list_key}[{item_index}].message", "message": "must be string"})
            refs = item.get("source_block_refs")
            if not isinstance(refs, list):
                errors.append({"path": f"$.{list_key}[{item_index}].source_block_refs", "message": "must be array"})
            else:
                for ref in refs:
                    if ref not in allowed_refs:
                        errors.append({"path": f"$.{list_key}[{item_index}].source_block_refs", "message": f"ref {ref} is not in document_group"})
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def repair_protocol_shape(payload: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    repaired = json.loads(json.dumps(payload, ensure_ascii=False))
    field_refs = repaired.setdefault("field_refs", {})
    for key in FIELD_REF_KEYS:
        value = field_refs.get(key)
        field_refs[key] = unique_refs(value if isinstance(value, list) else [])

    status = repaired.setdefault("field_status", {})
    default_by_ref = {
        "stem": "present" if field_refs["stem_refs"] else "missing",
        "options": "present" if field_refs["option_refs"] else "not_applicable",
        "passage": "present" if field_refs["passage_refs"] else "not_applicable",
        "answer": "present" if field_refs["answer_refs"] else "missing",
        "analysis": "present" if field_refs["analysis_refs"] else "missing",
        "translation": "present" if field_refs["translation_refs"] else "missing",
        "context": "present" if field_refs["context_refs"] else "not_applicable",
    }
    for key, default in default_by_ref.items():
        if status.get(key) not in ORDINARY_STATUS:
            status[key] = default
    if status.get("visual_asset") not in VISUAL_STATUS:
        status["visual_asset"] = "required" if field_refs["visual_refs"] or group.get("visual_block_refs") else "not_required"
    if status.get("writing_surface") not in VISUAL_STATUS:
        status["writing_surface"] = "required" if field_refs["writing_surface_refs"] else "not_required"

    for list_key in ["open_issues", "normalizer_warnings"]:
        value = repaired.get(list_key)
        if not isinstance(value, list):
            repaired[list_key] = []
            continue
        normalized_items = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                normalized_items.append(
                    {
                        "code": str(item.get("code") or f"{list_key}_{index + 1}"),
                        "message": str(item.get("message") or ""),
                        "source_block_refs": unique_refs(item.get("source_block_refs") if isinstance(item.get("source_block_refs"), list) else []),
                    }
                    | {k: v for k, v in item.items() if k not in {"code", "message", "source_block_refs"}}
                )
            elif isinstance(item, str):
                normalized_items.append({"code": f"{list_key}_{index + 1}", "message": item, "source_block_refs": []})
        repaired[list_key] = normalized_items
    return repaired
