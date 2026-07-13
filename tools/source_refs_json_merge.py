from __future__ import annotations

from question_visual_structure_contract import SCHEMA_VERSION


def merge_source_refs_json(existing: dict | None, question_visual_structure: dict) -> tuple[dict, list[str]]:
    merged = dict(existing or {})
    flags: list[str] = []
    try:
        schema_versions = dict(merged.get("schema_versions") or {})
        schema_versions["question_visual_structure"] = question_visual_structure.get("schema_version", SCHEMA_VERSION)
        merged["schema_versions"] = schema_versions
        merged["question_visual_structure"] = question_visual_structure
    except Exception:
        flags.append("source_refs_merge_conflict")
        return dict(existing or {}), flags
    return merged, flags
