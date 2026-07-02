from __future__ import annotations

import re
from typing import Iterable


SCHEMA_VERSION = "question_visual_structure.v1.1"

OPTION_ATTACH_CONFIDENCE_THRESHOLD = 0.75
IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD = 0.75

ASSET_ROLES = [
    "question",
    "stem",
    "analysis",
    "option",
    "evidence",
]

PLACEMENT_SCOPES = [
    "after_stem",
    "after_analysis",
    "option_inline",
    "evidence_only",
]

BBOX_SPACES = [
    "question_image",
    "stem_image",
    "analysis_image",
    "option_crop",
]

BLOCK_SCOPES = [
    "stem",
    "option",
    "answer",
    "analysis",
    "evidence",
]

BLOCK_TYPES = [
    "markdown",
    "image",
]

ATTACH_STATUSES = [
    "no_image",
    "attached",
    "not_attached_low_confidence",
    "not_attached_unassigned",
    "not_attached_public_stem_image",
    "not_attached_conflict",
]

FILE_STATUSES = [
    "planned",
    "materialized",
    "failed",
]

REVIEW_FLAGS = [
    "option_anchor_missing",
    "option_anchor_low_confidence",
    "option_asset_unassigned",
    "option_asset_suspicious_crop",
    "option_layout_unknown",
    "option_count_mismatch",
    "option_image_count_mismatch",
    "fallback_to_stem_image",
    "bbox_space_missing",
    "bbox_space_invalid",
    "asset_id_missing",
    "asset_materialize_failed",
    "legacy_structure_mismatch",
    "public_stem_image_detected",
    "public_analysis_image_detected",
    "cross_option_image_detected",
    "source_refs_merge_conflict",
    "bbox_audit_suspect",
    "bbox_audit_invalid",
    "detector_source_missing",
    "planner_where_normalized",
    "figure_detection_zero_assets",
    "fallback_figure_detection_used",
    "inline_figure_refine_shrink_rejected",
    "inline_figure_refine_model_failed",
    "inline_figure_refine_bbox_invalid",
    "inline_figure_refine_all_rejected",
    "inline_figure_refine_all_rejected_keep_coarse",
    "public_figure_model_not_run_missing_api_key",
    "public_figure_model_call_failed",
    "public_figure_model_empty",
    "public_figure_model_not_run",
    "question_image_boxes_kept_for_analysis_reclassify",
    "stem_zero_asset_rescan",
    "stem_zero_asset_rescan_attempted",
    "stem_zero_asset_rescan_failed",
    "analysis_zero_asset_rescan",
    "analysis_zero_asset_rescan_attempted",
    "analysis_zero_asset_rescan_failed",
    "number_line",
    "bbox_needs_review",
    "option_crop_safe_union",
    "option_figure_refine_attempted",
    "option_figure_refine_model_failed",
    "option_figure_refine_invalid",
    "option_figure_refine_bbox_invalid",
    "option_figure_refine_rejected_keep_coarse",
    "asset_ownership_relinked_to_stem",
    "asset_ownership_relinked_to_analysis",
    "final_asset_quality_missing_local_path",
    "final_asset_quality_model_not_run_missing_api_key",
    "final_asset_quality_model_invalid_figure",
    "final_asset_quality_bbox_invalid",
    "final_asset_quality_shrink_rejected_keep_current",
    "final_asset_quality_checked_no_change",
    "final_asset_quality_refined_by_model",
    "final_asset_quality_model_failed",
    "final_asset_quality_model_skipped",
    "asset_package_missing_expected_figure",
    "asset_package_option_image_count_mismatch",
    "asset_package_many_crops_review",
    "asset_package_headless_crop_risk",
    "asset_package_wrong_scope_risk",
]


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(text or "").strip())
    slug = slug.strip("._-")
    return slug or "item"


def normalize_review_flags(flags: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in flags or []:
        flag = str(raw or "").strip()
        if not flag or flag not in REVIEW_FLAGS or flag in seen:
            continue
        seen.add(flag)
        result.append(flag)
    return result


def make_stable_asset_id(
    question_uid: str,
    role: str,
    option_key: str | None = None,
    ordinal: int = 1,
) -> str:
    role_value = str(role or "").strip().lower()
    option_value = str(option_key or "").strip().upper()
    question_part = safe_slug(question_uid)
    if option_value:
        return f"qa_{question_part}_{role_value}_{option_value}_{ordinal:03d}"
    return f"qa_{question_part}_{role_value}_{ordinal:03d}"


def make_storage_key(
    question_uid: str,
    role: str,
    option_key: str | None = None,
    ordinal: int = 1,
    suffix: str = ".png",
    runtime_run_id: str = "",
    content_hash: str = "",
) -> str:
    role_value = str(role or "").strip().lower()
    option_value = str(option_key or "").strip().upper()
    question_part = safe_slug(question_uid)
    version_part = safe_slug(runtime_run_id or content_hash)
    ext = suffix if str(suffix or "").startswith(".") else f".{suffix}"
    base_prefix = f"question_assets/{question_part}"
    # Use a run/content segment when available so reruns do not overwrite a
    # previously reviewed visual bundle under the same question uid.
    if version_part:
        base_prefix = f"{base_prefix}/{version_part}"
    if option_value:
        return f"{base_prefix}/options/{option_value}/{ordinal:03d}{ext}"
    return f"{base_prefix}/{role_value}/{ordinal:03d}{ext}"


def make_display_ref(asset_id: str) -> str:
    return f"asset://{asset_id}"


def _valid_bbox(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("x", "y", "w", "h"):
        item = value.get(key)
        if not isinstance(item, (int, float)):
            return False
    return True


def validate_visual_asset(asset: dict) -> list[str]:
    flags: list[str] = []
    if str(asset.get("asset_role", "") or "") not in ASSET_ROLES:
        flags.append("asset_id_missing")
    if str(asset.get("placement_scope", "") or "") not in PLACEMENT_SCOPES:
        flags.append("option_asset_unassigned")
    bbox_space = str(asset.get("bbox_space", "") or "")
    if not bbox_space:
        flags.append("bbox_space_missing")
    elif bbox_space not in BBOX_SPACES:
        flags.append("bbox_space_invalid")
    if not str(asset.get("asset_id", "") or "").strip():
        flags.append("asset_id_missing")
    bbox_json = asset.get("bbox_json")
    if bbox_json is not None and bbox_json != {} and not _valid_bbox(bbox_json):
        flags.append("bbox_space_invalid")
    return normalize_review_flags(flags)


def validate_content_block(block: dict) -> list[str]:
    flags: list[str] = []
    if str(block.get("scope", "") or "") not in BLOCK_SCOPES:
        flags.append("legacy_structure_mismatch")
    if str(block.get("block_type", "") or "") not in BLOCK_TYPES:
        flags.append("legacy_structure_mismatch")
    if block.get("block_type") == "image" and not str(block.get("asset_id", "") or "").strip():
        flags.append("asset_id_missing")
    return normalize_review_flags(flags)


def validate_option(option: dict) -> list[str]:
    flags: list[str] = []
    if not str(option.get("option_key", "") or "").strip():
        flags.append("option_anchor_missing")
    bbox_space = str(option.get("bbox_space", "") or "")
    if not bbox_space:
        flags.append("bbox_space_missing")
    elif bbox_space not in BBOX_SPACES:
        flags.append("bbox_space_invalid")
    bbox_json = option.get("bbox_json")
    if bbox_json is not None and bbox_json != {} and not _valid_bbox(bbox_json):
        flags.append("bbox_space_invalid")
    return normalize_review_flags(flags)
