from __future__ import annotations

from pathlib import Path

from PIL import Image

from question_visual_structure_contract import (
    IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD,
    OPTION_ATTACH_CONFIDENCE_THRESHOLD,
    make_display_ref,
    make_stable_asset_id,
    make_storage_key,
    normalize_review_flags,
)


def _image_size(path: Path | None) -> tuple[int, int]:
    if path is None or not path.exists():
        return 0, 0
    with Image.open(path) as img:
        return img.width, img.height


def _detect_red_solution_boundary(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    try:
        with Image.open(path) as img:
            image = img.convert("RGB")
            width, height = image.size
            pixels = image.load()
            for y in range(max(80, int(height * 0.08)), height):
                red = 0
                for x in range(width):
                    r, g, b = pixels[x, y]
                    if r > 150 and g < 135 and b < 135 and r - max(g, b) > 35:
                        red += 1
                if red / max(width, 1) >= 0.006:
                    return y
    except Exception:
        return None
    return None


def _resolve_source_image(question: dict, bbox_space: str) -> tuple[str, Path | None]:
    role = "stem_image" if bbox_space == "stem_image" else "question_image"
    if bbox_space == "analysis_image":
        role = "analysis_image"
    raw = str(question.get(role, "") or "").strip()
    return role, Path(raw) if raw else None


def _infer_detector_source(bbox_json: dict) -> str:
    explicit = str(bbox_json.get("detector_source", "") or "").strip()
    if explicit:
        return explicit
    review_flags = set(bbox_json.get("review_flags", []) or [])
    confidence = float(bbox_json.get("confidence", 0.0) or 0.0)
    if abs(confidence - 0.72) < 1e-6 and "option_anchor_low_confidence" in review_flags:
        return "heuristic_fallback_inferred"
    return "unknown"


def _infer_public_figure_role(
    *,
    bbox: dict,
    bbox_space: str,
    source_image_role: str,
    source_path: Path | None,
    image_height: int,
) -> tuple[str, str, list[str]]:
    if bbox_space == "analysis_image" or source_image_role == "analysis_image":
        return "analysis", "after_analysis", ["public_analysis_image_detected"]
    if bbox_space != "question_image" or image_height <= 0:
        return "stem", "after_stem", ["public_stem_image_detected"]

    boundary_y = _detect_red_solution_boundary(source_path)
    if boundary_y is None:
        return "stem", "after_stem", ["public_stem_image_detected"]
    y = int(bbox.get("y", 0) or 0)
    h = int(bbox.get("h", 0) or 0)
    center_y = y + h / 2
    if center_y >= boundary_y:
        return "analysis", "after_analysis", ["public_analysis_image_detected", "question_image_analysis_region"]
    return "stem", "after_stem", ["public_stem_image_detected", "question_image_stem_region"]


def _make_asset(
    *,
    question_uid: str,
    role: str,
    ordinal: int,
    bbox_space: str,
    bbox_json: dict,
    image_width: int,
    image_height: int,
    source_image_role: str,
    option_key: str | None = None,
    candidate_option_key: str | None = None,
    confidence: float = 0.0,
    attach_status: str = "attached",
    placement_scope: str = "option_inline",
    review_flags: list[str] | None = None,
    detector_source: str = "",
    crop_policy: str = "",
    external_label_kind: str = "",
    external_label_text: str = "",
) -> dict:
    suffix = ".png"
    asset_id = make_stable_asset_id(question_uid, role, option_key=option_key, ordinal=ordinal)
    return {
        "asset_id": asset_id,
        "asset_role": role,
        "placement_scope": placement_scope,
        "option_key": option_key,
        "candidate_option_key": candidate_option_key,
        "storage_key": make_storage_key(question_uid, role, option_key=option_key, ordinal=ordinal, suffix=suffix),
        "display_ref": make_display_ref(asset_id),
        "mime_type": "image/png",
        "bbox_space": bbox_space,
        "bbox_json": bbox_json,
        "image_width": image_width,
        "image_height": image_height,
        "source_image_role": source_image_role,
        "page_no": int((question_uid.rsplit("_p", 1)[-1].split("_", 1)[0]) if "_p" in question_uid else 1),
        "confidence": round(float(confidence or 0.0), 4),
        "attach_status": attach_status,
        "materialized": False,
        "file_status": "planned",
        "review_flags": normalize_review_flags(review_flags or []),
        "detector_source": str(detector_source or "").strip() or "unknown",
        "crop_policy": str(crop_policy or "").strip() or "default",
        "external_label_kind": str(external_label_kind or "").strip(),
        "external_label_text": str(external_label_text or "").strip(),
    }


def build_staged_visual_assets(question: dict, detection: dict) -> list[dict]:
    question_uid = str(question.get("question_uid", "") or question.get("question_id", "")).strip() or "question"
    staged: list[dict] = []
    option_ordinals: dict[str, int] = {}
    evidence_ordinal = 1
    stem_figure_ordinal = 1
    analysis_figure_ordinal = 1

    for block in detection.get("option_visual_blocks", []) or []:
        option_key = str(block.get("option_key", "") or "").upper()
        bbox_space = str(block.get("bbox_space", "") or "")
        source_image_role, source_path = _resolve_source_image(question, bbox_space)
        width, height = _image_size(source_path)
        block_conf = float(block.get("confidence", 0.0) or 0.0)
        block_flags = list(block.get("review_flags", []) or [])
        for image_bbox in block.get("image_bboxes", []) or []:
            ordinal = option_ordinals.get(option_key, 0) + 1
            option_ordinals[option_key] = ordinal
            confidence = block_conf
            detector_source = _infer_detector_source(image_bbox if isinstance(image_bbox, dict) else {})
            attachable = (
                bool(option_key)
                and bbox_space in {"question_image", "stem_image", "analysis_image"}
                and confidence >= OPTION_ATTACH_CONFIDENCE_THRESHOLD
                and confidence >= IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD
                and "cross_option_image_detected" not in block_flags
                and "public_stem_image_detected" not in block_flags
            )
            if attachable:
                staged.append(
                    _make_asset(
                        question_uid=question_uid,
                        role="option",
                        option_key=option_key,
                        candidate_option_key=option_key,
                        ordinal=ordinal,
                        bbox_space=bbox_space,
                        bbox_json=image_bbox,
                        image_width=width or int(block.get("image_width", 0) or 0),
                        image_height=height or int(block.get("image_height", 0) or 0),
                        source_image_role=source_image_role,
                        confidence=confidence,
                        attach_status="attached",
                        placement_scope="option_inline",
                        review_flags=block_flags,
                        detector_source=detector_source,
                        crop_policy="figure_body_only",
                        external_label_kind="option_key",
                        external_label_text=option_key,
                    )
                )
            else:
                staged.append(
                    _make_asset(
                        question_uid=question_uid,
                        role="evidence",
                        option_key=None,
                        candidate_option_key=option_key or None,
                        ordinal=evidence_ordinal,
                        bbox_space=bbox_space or "stem_image",
                        bbox_json=image_bbox,
                        image_width=width or int(block.get("image_width", 0) or 0),
                        image_height=height or int(block.get("image_height", 0) or 0),
                        source_image_role=source_image_role or "stem_image",
                        confidence=confidence,
                        attach_status="not_attached_low_confidence" if confidence < OPTION_ATTACH_CONFIDENCE_THRESHOLD else "not_attached_conflict",
                        placement_scope="evidence_only",
                        review_flags=block_flags + ["option_asset_unassigned"],
                        detector_source=detector_source,
                        crop_policy="figure_body_only",
                        external_label_kind="option_key" if option_key else "",
                        external_label_text=option_key,
                    )
                )
                evidence_ordinal += 1

    for bbox in detection.get("unassigned_image_bboxes", []) or []:
        bbox_space = "stem_image"
        source_image_role, source_path = _resolve_source_image(question, bbox_space)
        width, height = _image_size(source_path)
        staged.append(
            _make_asset(
                question_uid=question_uid,
                role="evidence",
                option_key=None,
                candidate_option_key=None,
                ordinal=evidence_ordinal,
                bbox_space=bbox_space,
                bbox_json=bbox,
                image_width=width,
                image_height=height,
                source_image_role=source_image_role,
                confidence=0.5,
                attach_status="not_attached_unassigned",
                placement_scope="evidence_only",
                review_flags=["option_asset_unassigned"],
                detector_source=_infer_detector_source(bbox if isinstance(bbox, dict) else {}),
            )
        )
        evidence_ordinal += 1

    for bbox in detection.get("stem_image_bboxes", []) or []:
        bbox_space = str(bbox.get("bbox_space", "") or "stem_image")
        source_image_role, source_path = _resolve_source_image(question, bbox_space)
        width, height = _image_size(source_path)
        role, placement_scope, role_flags = _infer_public_figure_role(
            bbox=bbox if isinstance(bbox, dict) else {},
            bbox_space=bbox_space,
            source_image_role=source_image_role,
            source_path=source_path,
            image_height=height,
        )
        staged.append(
            _make_asset(
                question_uid=question_uid,
                role=role,
                option_key=None,
                candidate_option_key=None,
                ordinal=evidence_ordinal,
                bbox_space=bbox_space,
                bbox_json=bbox,
                image_width=width,
                image_height=height,
                source_image_role=source_image_role,
                confidence=0.8,
                attach_status="attached",
                placement_scope=placement_scope,
                review_flags=role_flags,
                detector_source=_infer_detector_source(bbox if isinstance(bbox, dict) else {}),
                crop_policy="figure_body_only",
            )
        )
        stem_figure_ordinal += 1
        evidence_ordinal += 1

    for bbox in detection.get("analysis_image_bboxes", []) or []:
        bbox_space = str(bbox.get("bbox_space", "") or "analysis_image")
        source_image_role, source_path = _resolve_source_image(question, bbox_space)
        width, height = _image_size(source_path)
        staged.append(
            _make_asset(
                question_uid=question_uid,
                role="analysis",
                option_key=None,
                candidate_option_key=None,
                ordinal=evidence_ordinal,
                bbox_space=bbox_space,
                bbox_json=bbox,
                image_width=width,
                image_height=height,
                source_image_role=source_image_role,
                confidence=float(bbox.get("confidence", 0.8) or 0.8),
                attach_status="attached",
                placement_scope="after_analysis",
                review_flags=list(bbox.get("review_flags", []) or []) + ["public_analysis_image_detected"],
                detector_source=_infer_detector_source(bbox if isinstance(bbox, dict) else {}),
                crop_policy="figure_body_only",
            )
        )
        analysis_figure_ordinal += 1
        evidence_ordinal += 1

    return staged
