from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

import vision_prompt_store
from question_visual_structure_contract import (
    IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD,
    OPTION_ATTACH_CONFIDENCE_THRESHOLD,
    normalize_review_flags,
)


API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260428"
PUBLIC_FIGURE_MIN_SIDE = 72
PUBLIC_FIGURE_MAX_ASPECT = 3.2
PUBLIC_FIGURE_MIN_HEIGHT_RATIO = 0.055
PUBLIC_FIGURE_MIN_WIDTH_RATIO = 0.08

OPTION_KEYS = ["A", "B", "C", "D"]
MARKER_RE = re.compile(r"(?:^|\s|\n)(?:[（(]?([A-D])[）)]?[.、]?)")


def _read_image_meta(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.width, img.height


def _image_to_data_url(path: Path) -> str:
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _pil_image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_object_not_found")
    return json.loads(clean[start : end + 1])


def _normalize_bbox(value: object) -> dict:
    if not isinstance(value, dict):
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    return {
        "x": int(value.get("x", 0) or 0),
        "y": int(value.get("y", 0) or 0),
        "w": int(value.get("w", 0) or 0),
        "h": int(value.get("h", 0) or 0),
    }


def _option_bbox_coordinate_mode(block: dict, image_width: int, image_height: int) -> str:
    raw_boxes: list[dict] = []
    for key in ("label_bbox", "option_bbox", "text_bbox"):
        value = block.get(key)
        if isinstance(value, dict):
            raw_boxes.append(_normalize_bbox(value))
    for value in block.get("image_bboxes", []) or []:
        if isinstance(value, dict):
            raw_boxes.append(_normalize_bbox(value))
    if not raw_boxes:
        return "pixel"

    declared_w = int(block.get("image_width", 0) or 0)
    declared_h = int(block.get("image_height", 0) or 0)
    if declared_w == 1000 or declared_h == 1000:
        return "normalized_1000"

    max_right = max(item["x"] + item["w"] for item in raw_boxes)
    max_bottom = max(item["y"] + item["h"] for item in raw_boxes)
    # Doubao-style grounding often comes back in a 0-1000 canvas even when the
    # prompt asks for pixels. If any option bbox exceeds the real image bounds,
    # use the normalized interpretation instead of letting C/D vanish at crop time.
    if (max_right > image_width or max_bottom > image_height) and max(max_right, max_bottom) <= 1100:
        return "normalized_1000"
    return "pixel"


def _normalize_option_bbox(value: object, *, mode: str, image_width: int, image_height: int) -> dict:
    raw = _normalize_bbox(value)
    if mode == "normalized_1000":
        x = int(round(raw["x"] * image_width / 1000.0))
        y = int(round(raw["y"] * image_height / 1000.0))
        w = int(round(raw["w"] * image_width / 1000.0))
        h = int(round(raw["h"] * image_height / 1000.0))
    else:
        x, y, w, h = raw["x"], raw["y"], raw["w"], raw["h"]

    result = {
        "x": max(x, 0),
        "y": max(y, 0),
        "w": max(w, 0),
        "h": max(h, 0),
    }
    if isinstance(value, dict):
        flags = normalize_review_flags(value.get("review_flags", []) or [])
        if mode == "normalized_1000":
            flags = normalize_review_flags(flags + ["model_bbox_normalized_1000"])
            result["raw_model_bbox_json"] = raw
            result["bbox_coordinate_mode"] = mode
        confidence = value.get("confidence")
        if confidence is not None:
            result["confidence"] = round(float(confidence or 0.0), 4)
        detector_source = str(value.get("detector_source", "") or "").strip()
        result["detector_source"] = detector_source or "vision_model_option"
        result["review_flags"] = flags
    return result


def _normalize_option_block(
    block: dict,
    bbox_space: str,
    image_width: int,
    image_height: int,
    *,
    force_coordinate_mode: str | None = None,
) -> dict:
    review_flags = normalize_review_flags(block.get("review_flags", []) or [])
    confidence = float(block.get("confidence", 0.0) or 0.0)
    coordinate_mode = force_coordinate_mode or _option_bbox_coordinate_mode(block, image_width, image_height)
    if coordinate_mode == "normalized_1000":
        review_flags = normalize_review_flags(review_flags + ["option_bbox_normalized_1000"])
    if confidence < OPTION_ATTACH_CONFIDENCE_THRESHOLD and "option_anchor_low_confidence" not in review_flags:
        review_flags.append("option_anchor_low_confidence")
    return {
        "option_key": str(block.get("option_key", "") or "").upper(),
        "option_order": int(block.get("option_order", 0) or 0),
        "label_bbox": _normalize_option_bbox(block.get("label_bbox"), mode=coordinate_mode, image_width=image_width, image_height=image_height),
        "option_bbox": _normalize_option_bbox(block.get("option_bbox"), mode=coordinate_mode, image_width=image_width, image_height=image_height),
        "text_bbox": _normalize_option_bbox(block.get("text_bbox"), mode=coordinate_mode, image_width=image_width, image_height=image_height),
        "image_bboxes": [
            _normalize_option_bbox(item, mode=coordinate_mode, image_width=image_width, image_height=image_height)
            for item in (block.get("image_bboxes", []) or [])
            if isinstance(item, dict)
        ],
        "bbox_space": bbox_space,
        "image_width": image_width,
        "image_height": image_height,
        "layout_type": str(block.get("layout_type", "") or "unknown"),
        "confidence": round(confidence, 4),
        "bbox_coordinate_mode": coordinate_mode,
        "review_flags": review_flags,
    }


def _call_model(api_key: str, model: str, image_path: Path, bbox_space: str, hint_text: str = "") -> dict:
    bundle = vision_prompt_store.get_option_anchor_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "BBOX_SPACE": bbox_space or "stem_image",
            "HINT_TEXT": hint_text or "- none",
        },
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_to_data_url(image_path)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_inline_figure_model(api_key: str, model: str, image_path: Path, bbox_space: str, hint_text: str = "") -> dict:
    bundle = vision_prompt_store.get_inline_figure_prompt_bundle()
    image_width, image_height = _read_image_meta(image_path)
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "BBOX_SPACE": bbox_space or "stem_image",
            "IMAGE_WIDTH": str(image_width),
            "IMAGE_HEIGHT": str(image_height),
            "HINT_TEXT": hint_text or "- none",
        },
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_to_data_url(image_path)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_inline_figure_model_on_image(
    api_key: str,
    model: str,
    image: Image.Image,
    *,
    bbox_space: str,
    hint_text: str = "",
) -> dict:
    bundle = vision_prompt_store.get_inline_figure_prompt_bundle()
    image_width, image_height = image.size
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "BBOX_SPACE": bbox_space or "stem_image",
            "IMAGE_WIDTH": str(image_width),
            "IMAGE_HEIGHT": str(image_height),
            "HINT_TEXT": hint_text or "- none",
        },
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_inline_figure_refine_model(api_key: str, model: str, crop_image: Image.Image) -> dict:
    bundle = vision_prompt_store.get_inline_figure_refine_prompt_bundle()
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": bundle["user_template"]},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(crop_image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_option_figure_refine_model(api_key: str, model: str, image: Image.Image, option_key: str) -> dict:
    bundle = vision_prompt_store.get_option_figure_refine_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {"OPTION_KEY": str(option_key or "").upper()},
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_analysis_figure_rescan_model(api_key: str, model: str, image: Image.Image, image_presence: str) -> dict:
    bundle = vision_prompt_store.get_analysis_figure_rescan_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {"IMAGE_PRESENCE": str(image_presence or "analysis_figure")},
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _call_public_figure_rescan_model(
    api_key: str,
    model: str,
    image: Image.Image,
    *,
    image_presence: str,
    target_scope: str,
) -> dict:
    bundle = vision_prompt_store.get_public_figure_rescan_prompt_bundle()
    prompt = vision_prompt_store.render_template(
        bundle["user_template"],
        {
            "IMAGE_PRESENCE": str(image_presence or "public_figure"),
            "TARGET_SCOPE": str(target_scope or "stem"),
        },
    )
    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _pil_image_to_data_url(image)}},
                ],
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network_error: {exc}") from exc
    payload = json.loads(raw)
    return _extract_json_block(payload["choices"][0]["message"]["content"])


def _heuristic_detect(option_keys: list[str], bbox_space: str, image_width: int, image_height: int) -> dict:
    if not option_keys:
        return {
            "option_visual_blocks": [],
            "stem_image_bboxes": [],
            "unassigned_image_bboxes": [],
            "global_review_flags": ["option_anchor_missing"],
        }
    count = len(option_keys)
    top = int(image_height * 0.35)
    remain_h = max(image_height - top, 1)
    layout_type = "two_column" if count == 4 and image_width > image_height * 0.75 else "vertical"
    blocks: list[dict] = []
    if layout_type == "two_column":
        cell_w = image_width // 2
        cell_h = remain_h // 2
        for idx, key in enumerate(option_keys[:4]):
            row = idx // 2
            col = idx % 2
            x = col * cell_w
            y = top + row * cell_h
            blocks.append(
                {
                    "option_key": key,
                    "option_order": idx + 1,
                    "label_bbox": {"x": x + 12, "y": y + 10, "w": 26, "h": 24},
                    "option_bbox": {"x": x, "y": y, "w": cell_w, "h": cell_h},
                    "text_bbox": {"x": x + 12, "y": y + 10, "w": max(cell_w - 24, 1), "h": min(48, cell_h)},
                    "image_bboxes": [],
                    "layout_type": layout_type,
                    "confidence": 0.42,
                    "review_flags": ["option_anchor_low_confidence"],
                }
            )
    else:
        cell_h = remain_h // max(count, 1)
        for idx, key in enumerate(option_keys):
            y = top + idx * cell_h
            blocks.append(
                {
                    "option_key": key,
                    "option_order": idx + 1,
                    "label_bbox": {"x": 12, "y": y + 10, "w": 26, "h": 24},
                    "option_bbox": {"x": 0, "y": y, "w": image_width, "h": cell_h},
                    "text_bbox": {"x": 12, "y": y + 10, "w": max(image_width - 24, 1), "h": min(48, cell_h)},
                    "image_bboxes": [],
                    "layout_type": layout_type,
                    "confidence": 0.42,
                    "review_flags": ["option_anchor_low_confidence"],
                }
            )
    return {
        "option_visual_blocks": [
            _normalize_option_block(block, bbox_space, image_width, image_height) for block in blocks
        ],
        "stem_image_bboxes": [],
        "unassigned_image_bboxes": [],
        "global_review_flags": ["option_anchor_low_confidence"],
    }


def _extract_option_keys(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in MARKER_RE.finditer(text or ""):
        key = str(match.group(1) or "").upper()
        if key in OPTION_KEYS and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def detect_option_anchors(
    question: dict,
    gating_result: dict,
    *,
    api_key: str = "",
    model: str = "",
) -> dict:
    if not bool(gating_result.get("should_run_option_detection", False)):
        return {
            "option_visual_blocks": [],
            "stem_image_bboxes": [],
            "unassigned_image_bboxes": [],
            "global_review_flags": [],
        }

    stem_path_raw = str(question.get("stem_image", "") or "").strip()
    question_path_raw = str(question.get("question_image", "") or "").strip()
    image_path = Path(stem_path_raw or question_path_raw)
    if not image_path.exists():
        return {
            "option_visual_blocks": [],
            "stem_image_bboxes": [],
            "unassigned_image_bboxes": [],
            "global_review_flags": ["option_anchor_missing"],
        }

    bbox_space = "stem_image" if stem_path_raw else "question_image"
    width, height = _read_image_meta(image_path)
    hint_text = "\n".join(
        part for part in (
            str(question.get("stem_text", "") or ""),
            str(question.get("transcription_ocr", "") or ""),
        ) if part.strip()
    )

    detection: dict | None = None
    option_keys = _extract_option_keys(hint_text)
    api_key_value = str(api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    model_name = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if api_key_value:
        try:
            detection = _call_model(api_key_value, model_name, image_path, bbox_space, hint_text)
        except Exception:
            detection = None

    if detection is None:
        detection = _heuristic_detect(option_keys, bbox_space, width, height)
        detection["detector"] = "heuristic_fallback"
    else:
        raw_blocks = detection.get("options", []) or detection.get("option_visual_blocks", []) or []
        raw_blocks = [
            block
            for block in raw_blocks
            if isinstance(block, dict) and str(block.get("option_key", "") or "").upper() in OPTION_KEYS
        ]
        coordinate_modes = [
            _option_bbox_coordinate_mode(block, width, height)
            for block in raw_blocks
        ]
        force_coordinate_mode = "normalized_1000" if "normalized_1000" in coordinate_modes else None
        detection = {
            "option_visual_blocks": [
                _normalize_option_block(block, bbox_space, width, height, force_coordinate_mode=force_coordinate_mode)
                for block in raw_blocks
            ],
            # Keep option detection focused on option-scoped layout only.
            "stem_image_bboxes": [],
            "unassigned_image_bboxes": [],
            "global_review_flags": normalize_review_flags(detection.get("global_review_flags", []) or []),
            "detector": "vision_model",
        }
        if detection["option_visual_blocks"]:
            with Image.open(image_path) as img:
                refined_blocks = _refine_option_blocks_with_model(
                    img.convert("RGB"),
                    detection["option_visual_blocks"],
                    api_key=api_key_value,
                    model=model_name,
                )
            if refined_blocks:
                detection["option_visual_blocks"] = refined_blocks
                detection["detector"] = "vision_model+option_refine_model"
        if not detection["option_visual_blocks"]:
            detection["global_review_flags"] = normalize_review_flags(
                list(detection.get("global_review_flags", [])) + ["option_anchor_missing"]
            )
    return detection


def _refine_option_blocks_with_model(
    image: Image.Image,
    blocks: list[dict],
    *,
    api_key: str,
    model: str,
) -> list[dict]:
    if not api_key or not blocks:
        return blocks

    image_width, image_height = image.size
    refined_blocks: list[dict] = []
    for block in blocks:
        updated_block = dict(block)
        option_key = str(block.get("option_key", "") or "").upper()
        refined_image_bboxes: list[dict] = []
        for box in block.get("image_bboxes", []) or []:
            if not isinstance(box, dict):
                continue
            x = int(box.get("x", 0) or 0)
            y = int(box.get("y", 0) or 0)
            w = int(box.get("w", 0) or 0)
            h = int(box.get("h", 0) or 0)
            if w <= 0 or h <= 0:
                continue

            if option_key:
                try:
                    target_payload = _call_option_figure_refine_model(api_key, model, image, option_key)
                    if bool(target_payload.get("is_valid_figure", True)):
                        raw_target_bbox = target_payload.get("bbox", {})
                        target_candidate = _normalize_bbox(raw_target_bbox)
                        target_canvas_w = int(target_payload.get("image_width", 1000) or 1000)
                        target_canvas_h = int(target_payload.get("image_height", 1000) or 1000)
                        if target_candidate["w"] > 0 and target_candidate["h"] > 0 and target_canvas_w > 0 and target_canvas_h > 0:
                            tx1 = round(target_candidate["x"] / target_canvas_w * image_width)
                            ty1 = round(target_candidate["y"] / target_canvas_h * image_height)
                            tx2 = round((target_candidate["x"] + target_candidate["w"]) / target_canvas_w * image_width)
                            ty2 = round((target_candidate["y"] + target_candidate["h"]) / target_canvas_h * image_height)
                            tx1 = max(0, min(tx1, image_width - 1))
                            ty1 = max(0, min(ty1, image_height - 1))
                            tx2 = max(tx1 + 1, min(tx2, image_width))
                            ty2 = max(ty1 + 1, min(ty2, image_height))
                            targeted = {
                                **box,
                                "x": tx1,
                                "y": ty1,
                                "w": tx2 - tx1,
                                "h": ty2 - ty1,
                                "pre_refine_bbox_json": {"x": x, "y": y, "w": w, "h": h},
                                "refine_model_bbox_json": dict(raw_target_bbox) if isinstance(raw_target_bbox, dict) else raw_target_bbox,
                                "figure_refine_source": "option_target_refine_model",
                                "figure_refine_confidence": float(target_payload.get("confidence", 0.0) or 0.0),
                                "review_flags": normalize_review_flags(
                                    list(box.get("review_flags", []) or []) + list(target_payload.get("review_flags", []) or [])
                                ),
                            }
                            if _looks_figure_like_bbox(targeted, image_width=image_width, image_height=image_height):
                                refined_image_bboxes.append(targeted)
                                continue
                except Exception:
                    pass

            # Refine inside the full option region when available. If the
            # first-stage image bbox is already wrong, a small crop around it
            # cannot recover missing axes/curves.
            context_box = _normalize_bbox(block.get("option_bbox", {}))
            if context_box["w"] <= 0 or context_box["h"] <= 0:
                context_box = {"x": x, "y": y, "w": w, "h": h}
            cx = int(context_box.get("x", 0) or 0)
            cy = int(context_box.get("y", 0) or 0)
            cw = int(context_box.get("w", 0) or 0)
            ch = int(context_box.get("h", 0) or 0)
            pad_x = max(24, int(cw * 0.06))
            pad_y = max(18, int(ch * 0.06))
            x1 = max(cx - pad_x, 0)
            y1 = max(cy - pad_y, 0)
            x2 = min(cx + cw + pad_x, image_width)
            y2 = min(cy + ch + pad_y, image_height)
            if x2 <= x1 or y2 <= y1:
                refined_image_bboxes.append(box)
                continue

            crop = image.crop((x1, y1, x2, y2))
            try:
                payload = _call_inline_figure_refine_model(api_key, model, crop)
            except Exception:
                kept = dict(box)
                kept["review_flags"] = normalize_review_flags(
                    list(kept.get("review_flags", []) or []) + ["option_figure_refine_model_failed"]
                )
                refined_image_bboxes.append(kept)
                continue

            if not bool(payload.get("is_valid_figure", True)):
                kept = dict(box)
                kept["review_flags"] = normalize_review_flags(
                    list(kept.get("review_flags", []) or []) + ["option_figure_refine_invalid"]
                )
                refined_image_bboxes.append(kept)
                continue

            raw_bbox = payload.get("bbox", {})
            candidate = _normalize_bbox(raw_bbox)
            canvas_w = int(payload.get("image_width", 1000) or 1000)
            canvas_h = int(payload.get("image_height", 1000) or 1000)
            if candidate["w"] <= 0 or candidate["h"] <= 0 or canvas_w <= 0 or canvas_h <= 0:
                kept = dict(box)
                kept["review_flags"] = normalize_review_flags(
                    list(kept.get("review_flags", []) or []) + ["option_figure_refine_bbox_invalid"]
                )
                refined_image_bboxes.append(kept)
                continue

            crop_w = x2 - x1
            crop_h = y2 - y1
            nx1 = x1 + round(candidate["x"] / canvas_w * crop_w)
            ny1 = y1 + round(candidate["y"] / canvas_h * crop_h)
            nx2 = x1 + round((candidate["x"] + candidate["w"]) / canvas_w * crop_w)
            ny2 = y1 + round((candidate["y"] + candidate["h"]) / canvas_h * crop_h)
            nx1 = max(0, min(nx1, image_width - 1))
            ny1 = max(0, min(ny1, image_height - 1))
            nx2 = max(nx1 + 1, min(nx2, image_width))
            ny2 = max(ny1 + 1, min(ny2, image_height))

            updated = {
                **box,
                "x": nx1,
                "y": ny1,
                "w": nx2 - nx1,
                "h": ny2 - ny1,
                "pre_refine_bbox_json": {"x": x, "y": y, "w": w, "h": h},
                "refine_crop_bbox_json": {"x": x1, "y": y1, "w": crop_w, "h": crop_h},
                "refine_model_bbox_json": dict(raw_bbox) if isinstance(raw_bbox, dict) else raw_bbox,
                "figure_refine_source": "option_refine_model",
                "figure_refine_confidence": float(payload.get("confidence", 0.0) or 0.0),
                "review_flags": normalize_review_flags(
                    list(box.get("review_flags", []) or []) + list(payload.get("review_flags", []) or [])
                ),
            }

            pre_area = max(w * h, 1)
            new_area = max((nx2 - nx1) * (ny2 - ny1), 1)
            left_shift = nx1 - x
            top_shift = ny1 - y
            shrink_too_much = new_area / pre_area < 0.55
            shifted_too_much = left_shift > max(28, int(w * 0.18)) or top_shift > max(24, int(h * 0.16))
            if shrink_too_much or shifted_too_much:
                kept = dict(box)
                kept["rejected_refine_bbox_json"] = {
                    "x": nx1,
                    "y": ny1,
                    "w": nx2 - nx1,
                    "h": ny2 - ny1,
                    "area_ratio": round(new_area / pre_area, 4),
                    "left_shift": left_shift,
                    "top_shift": top_shift,
                }
                kept["refine_crop_bbox_json"] = {"x": x1, "y": y1, "w": crop_w, "h": crop_h}
                kept["refine_model_bbox_json"] = dict(raw_bbox) if isinstance(raw_bbox, dict) else raw_bbox
                kept["figure_refine_source"] = "option_refine_model_rejected"
                kept["figure_refine_confidence"] = float(payload.get("confidence", 0.0) or 0.0)
                kept["review_flags"] = normalize_review_flags(
                    list(box.get("review_flags", []) or []) + ["option_figure_refine_rejected_keep_coarse"]
                )
                refined_image_bboxes.append(kept)
                continue

            refined_image_bboxes.append(updated)

        updated_block["image_bboxes"] = refined_image_bboxes
        updated_block["review_flags"] = normalize_review_flags(
            list(updated_block.get("review_flags", []) or []) + ["option_figure_refine_attempted"]
        )
        refined_blocks.append(updated_block)
    return refined_blocks


def _normalize_public_image_bbox(item: object) -> dict:
    if not isinstance(item, dict):
        return {}
    normalized = _normalize_bbox(item)
    normalized["confidence"] = round(float(item.get("confidence", 0.0) or 0.0), 4)
    normalized["review_flags"] = normalize_review_flags(item.get("review_flags", []) or [])
    detector_source = str(item.get("detector_source", "") or "").strip()
    if detector_source:
        normalized["detector_source"] = detector_source
    if normalized["confidence"] < IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD and "option_anchor_low_confidence" not in normalized["review_flags"]:
        normalized["review_flags"] = normalize_review_flags(list(normalized["review_flags"]) + ["option_anchor_low_confidence"])
    return normalized


def _scale_model_canvas_boxes(
    items: list[dict],
    *,
    model_image_width: int,
    model_image_height: int,
    image_width: int,
    image_height: int,
    image: Image.Image | None = None,
) -> list[dict]:
    if not items:
        return items

    def transform(source: str, scale_x: float, scale_y: float) -> list[dict]:
        scaled: list[dict] = []
        for item in items:
            raw_bbox = {
                "x": int(item.get("x", 0) or 0),
                "y": int(item.get("y", 0) or 0),
                "w": int(item.get("w", 0) or 0),
                "h": int(item.get("h", 0) or 0),
            }
            x = int(round(raw_bbox["x"] * scale_x))
            y = int(round(raw_bbox["y"] * scale_y))
            w = int(round(raw_bbox["w"] * scale_x))
            h = int(round(raw_bbox["h"] * scale_y))
            flags = list(item.get("review_flags", []) or [])
            if source == "model_canvas":
                flags.append("model_canvas_scaled")
            elif source == "normalized_1000":
                flags.append("model_bbox_normalized_1000")
            scaled.append(
                {
                    **item,
                    "x": max(x, 0),
                    "y": max(y, 0),
                    "w": max(w, 1),
                    "h": max(h, 1),
                    "review_flags": normalize_review_flags(flags),
                    "raw_model_bbox_json": raw_bbox,
                    "bbox_coordinate_mode": source,
                    "model_image_width": model_image_width,
                    "model_image_height": model_image_height,
                }
            )
        return scaled

    candidates: list[tuple[str, list[dict]]] = [
        ("pixel", transform("pixel", 1.0, 1.0)),
    ]
    if model_image_width > 0 and model_image_height > 0 and (
        model_image_width != image_width or model_image_height != image_height
    ):
        candidates.append(
            (
                "model_canvas",
                transform(
                    "model_canvas",
                    image_width / max(model_image_width, 1),
                    image_height / max(model_image_height, 1),
                ),
            )
        )
    # Several vision APIs/models emit grounding boxes in a 0-1000 coordinate
    # space even when the surrounding JSON echoes the original image size.
    # Keep this as an explicit candidate instead of assuming the declared size.
    candidates.append(
        (
            "normalized_1000",
            transform("normalized_1000", image_width / 1000.0, image_height / 1000.0),
        )
    )

    if image is None:
        # Deterministic fallback: if any raw box exceeds the real image bounds,
        # the 0-1000 interpretation is safer than treating it as pixels.
        max_right = max(int(item.get("x", 0) or 0) + int(item.get("w", 0) or 0) for item in items)
        max_bottom = max(int(item.get("y", 0) or 0) + int(item.get("h", 0) or 0) for item in items)
        if max_right > image_width or max_bottom > image_height:
            return candidates[-1][1]
        return candidates[0][1]

    def red_ratio(crop: Image.Image) -> float:
        if crop.width <= 0 or crop.height <= 0:
            return 1.0
        pixels = crop.convert("RGB").load()
        red = 0
        total = crop.width * crop.height
        for yy in range(crop.height):
            for xx in range(crop.width):
                r, g, b = pixels[xx, yy]
                if r >= 150 and g <= 120 and b <= 120 and r - max(g, b) >= 45:
                    red += 1
        return red / max(total, 1)

    def score_box(box: dict) -> float:
        x = int(box.get("x", 0) or 0)
        y = int(box.get("y", 0) or 0)
        w = int(box.get("w", 0) or 0)
        h = int(box.get("h", 0) or 0)
        if w <= 0 or h <= 0:
            return -100.0
        x2 = x + w
        y2 = y + h
        out_of_bounds = max(0, -x) + max(0, -y) + max(0, x2 - image_width) + max(0, y2 - image_height)
        cx1 = max(x, 0)
        cy1 = max(y, 0)
        cx2 = min(x2, image_width)
        cy2 = min(y2, image_height)
        if cx2 <= cx1 or cy2 <= cy1:
            return -100.0
        crop = image.crop((cx1, cy1, cx2, cy2))
        bounds = _find_dark_bounds(crop, 0, 0, crop.width, crop.height, threshold=220)
        if bounds is None:
            return -20.0
        bx1, by1, bx2, by2 = bounds
        fg_w = bx2 - bx1
        fg_h = by2 - by1
        fg_area_ratio = (fg_w * fg_h) / max(crop.width * crop.height, 1)
        edge_touch_penalty = sum(
            1
            for value in (
                bx1,
                by1,
                crop.width - bx2,
                crop.height - by2,
            )
            if value <= 1
        )
        # Prefer crops that contain a real sparse figure and avoid red teacher
        # explanation text. Extremely large text-heavy regions score poorly.
        score = 0.0
        score += min(fg_area_ratio, 0.82) * 6.0
        score -= red_ratio(crop) * 18.0
        score -= edge_touch_penalty * 0.7
        score -= out_of_bounds / max(image_width + image_height, 1) * 12.0
        if crop.width > image_width * 0.45 or crop.height > image_height * 0.55:
            score -= 1.4
        return score

    def score_set(candidate_items: list[dict]) -> float:
        if not candidate_items:
            return -100.0
        scores = [score_box(item) for item in candidate_items]
        # Do not let one good box hide several broken boxes.
        return (sum(scores) / len(scores)) + min(scores) * 0.35

    best_name, best_items = max(candidates, key=lambda pair: score_set(pair[1]))
    if best_name != "pixel":
        return best_items
    # If the raw pixel interpretation contains impossible boxes but scoring was
    # inconclusive, still avoid propagating impossible pixel coordinates.
    max_right = max(int(item.get("x", 0) or 0) + int(item.get("w", 0) or 0) for item in items)
    max_bottom = max(int(item.get("y", 0) or 0) + int(item.get("h", 0) or 0) for item in items)
    if max_right > image_width or max_bottom > image_height:
        return candidates[-1][1]
    return best_items


def _segment_runs(
    values: list[float],
    *,
    threshold: float,
    min_len: int,
    max_gap: int,
) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = -1
    end = -1
    for idx, value in enumerate(values):
        if value >= threshold:
            if start < 0:
                start = idx
            end = idx
            continue
        if start < 0:
            continue
        if idx - end - 1 <= max_gap:
            continue
        if end - start + 1 >= min_len:
            runs.append((start, end))
        start = -1
        end = -1
    if start >= 0 and end - start + 1 >= min_len:
        runs.append((start, end))
    return runs


def _find_dark_bounds(image: Image.Image, x1: int, y1: int, x2: int, y2: int, threshold: int = 215) -> tuple[int, int, int, int] | None:
    gray = image.convert("L")
    pixels = gray.load()
    width, height = gray.size
    left = right = top = bottom = None
    for y in range(max(y1, 0), min(y2, height)):
        for x in range(max(x1, 0), min(x2, width)):
            if pixels[x, y] < threshold:
                if left is None or x < left:
                    left = x
                if right is None or x > right:
                    right = x
                if top is None or y < top:
                    top = y
                if bottom is None or y > bottom:
                    bottom = y
    if None in {left, right, top, bottom}:
        return None
    return int(left), int(top), int(right) + 1, int(bottom) + 1


def _looks_figure_like_bbox(
    bbox: dict,
    *,
    image_width: int,
    image_height: int,
) -> bool:
    width = int(bbox.get("w", 0) or 0)
    height = int(bbox.get("h", 0) or 0)
    if width <= 0 or height <= 0:
        return False
    min_height = max(PUBLIC_FIGURE_MIN_SIDE, int(image_height * PUBLIC_FIGURE_MIN_HEIGHT_RATIO))
    min_width = max(PUBLIC_FIGURE_MIN_SIDE, int(image_width * PUBLIC_FIGURE_MIN_WIDTH_RATIO))
    if height < min_height or width < min_width:
        review_flags = set(str(item) for item in (bbox.get("review_flags", []) or []))
        if "number_line" not in review_flags:
            return False
    aspect = width / max(height, 1)
    review_flags = set(str(item) for item in (bbox.get("review_flags", []) or []))
    if "number_line" in review_flags:
        return 2.4 <= aspect <= 18.0 and width >= min_width and height >= 18
    if aspect > PUBLIC_FIGURE_MAX_ASPECT or aspect < 0.22:
        return False
    if width > int(image_width * 0.92) and height < int(image_height * 0.14):
        return False
    return True


def _colored_pixel_ratios(image: Image.Image, bbox: dict) -> dict[str, float]:
    x1 = max(int(bbox.get("x", 0) or 0), 0)
    y1 = max(int(bbox.get("y", 0) or 0), 0)
    x2 = min(x1 + int(bbox.get("w", 0) or 0), image.size[0])
    y2 = min(y1 + int(bbox.get("h", 0) or 0), image.size[1])
    if x2 <= x1 or y2 <= y1:
        return {"red": 0.0, "blue": 0.0}
    crop = image.convert("RGB").crop((x1, y1, x2, y2))
    pixels = crop.load()
    red = 0
    blue = 0
    total = crop.size[0] * crop.size[1]
    for yy in range(crop.size[1]):
        for xx in range(crop.size[0]):
            r, g, b = pixels[xx, yy]
            if r > 150 and g < 125 and b < 125:
                red += 1
            if b > 145 and r < 120 and g < 170:
                blue += 1
    return {"red": red / max(total, 1), "blue": blue / max(total, 1)}


def _dark_row_runs_for_bbox(image: Image.Image, bbox: dict, threshold: int = 220) -> list[tuple[int, int]]:
    x1 = max(int(bbox.get("x", 0) or 0), 0)
    y1 = max(int(bbox.get("y", 0) or 0), 0)
    x2 = min(x1 + int(bbox.get("w", 0) or 0), image.size[0])
    y2 = min(y1 + int(bbox.get("h", 0) or 0), image.size[1])
    if x2 <= x1 or y2 <= y1:
        return []
    gray = image.convert("L").crop((x1, y1, x2, y2))
    pixels = gray.load()
    cw, ch = gray.size
    ratios: list[float] = []
    for yy in range(ch):
        dark = 0
        for xx in range(cw):
            if pixels[xx, yy] < threshold:
                dark += 1
        ratios.append(dark / max(cw, 1))
    return _segment_runs(ratios, threshold=0.012, min_len=3, max_gap=4)


def _looks_like_text_false_positive(image: Image.Image, bbox: dict) -> bool:
    width = int(bbox.get("w", 0) or 0)
    height = int(bbox.get("h", 0) or 0)
    if width <= 0 or height <= 0:
        return True

    ratios = _colored_pixel_ratios(image, bbox)
    row_runs = _dark_row_runs_for_bbox(image, bbox)
    if not row_runs:
        return True
    run_count = len(row_runs)
    total_run_height = sum(end - start + 1 for start, end in row_runs)
    text_stack_like = run_count >= 4 and total_run_height <= max(80, int(height * 0.55))

    # Teacher analysis text is often red. Real math figures can contain a little
    # red annotation, so only reject when it also looks like stacked text lines.
    if ratios["red"] >= 0.018 and (text_stack_like or height < 150):
        return True
    if ratios["red"] >= 0.003 and run_count >= 4:
        return True

    # Blue page headers/titles are not semantic in-question figures.
    if ratios["blue"] >= 0.012 and height < 180:
        return True

    # A wide shallow crop with many short dark line runs is almost always a text
    # paragraph or formula strip, not a drawable figure.
    aspect = width / max(height, 1)
    if aspect > 2.2 and text_stack_like:
        return True
    if height < 95 and run_count >= 3:
        return True
    return False


def _trim_colored_header_strip(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    if x2 <= x1 or y2 <= y1 or y2 - y1 < 120:
        return bbox

    crop = image.convert("RGB").crop((x1, y1, x2, min(y2, y1 + min(120, (y2 - y1) // 3))))
    pixels = crop.load()
    cw, ch = crop.size
    blue_rows: list[float] = []
    for yy in range(ch):
        blue = 0
        for xx in range(cw):
            r, g, b = pixels[xx, yy]
            if b > 145 and r < 135 and g < 185:
                blue += 1
        blue_rows.append(blue / max(cw, 1))
    runs = _segment_runs(blue_rows, threshold=0.01, min_len=3, max_gap=4)
    if not runs:
        return bbox
    _, end = runs[0]
    new_y1 = y1 + end + 6
    if new_y1 >= y2 - 72:
        return bbox
    return {
        **bbox,
        "y": new_y1,
        "h": y2 - new_y1,
        "review_flags": normalize_review_flags(
            list(bbox.get("review_flags", []) or []) + ["colored_header_trimmed"]
        ),
    }


def _trim_red_teacher_text_edges(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    if x2 <= x1 or y2 <= y1 or y2 - y1 < 90:
        return bbox

    crop = image.convert("RGB").crop((x1, y1, x2, y2))
    pixels = crop.load()
    cw, ch = crop.size
    red_rows: list[float] = []
    for yy in range(ch):
        red = 0
        for xx in range(cw):
            r, g, b = pixels[xx, yy]
            if r > 150 and g < 130 and b < 130:
                red += 1
        red_rows.append(red / max(cw, 1))

    runs = _segment_runs(red_rows, threshold=0.0035, min_len=2, max_gap=3)
    if not runs:
        return bbox

    updated = dict(bbox)
    top_limit = int(ch * 0.35)
    bottom_limit = int(ch * 0.65)
    top_runs = [(s, e) for s, e in runs if s <= top_limit]
    bottom_runs = [(s, e) for s, e in runs if e >= bottom_limit]

    if top_runs:
        _s, top_end = max(top_runs, key=lambda run: run[1])
        new_y1 = y1 + top_end + 5
        if new_y1 < y2 - 72:
            updated["y"] = new_y1
            updated["h"] = y2 - new_y1
            updated["review_flags"] = normalize_review_flags(
                list(updated.get("review_flags", []) or []) + ["red_teacher_text_top_trimmed"]
            )

    if bottom_runs:
        bottom_start, _e = min(bottom_runs, key=lambda run: run[0])
        new_y2 = y1 + bottom_start - 4
        current_y1 = int(updated.get("y", 0) or 0)
        if new_y2 > current_y1 + 72:
            updated["h"] = new_y2 - current_y1
            updated["review_flags"] = normalize_review_flags(
                list(updated.get("review_flags", []) or []) + ["red_teacher_text_bottom_trimmed"]
            )
    return updated


def _trim_bottom_text_block_after_gap(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    if x2 <= x1 or y2 <= y1 or y2 - y1 < 120:
        return bbox

    crop = image.convert("L").crop((x1, y1, x2, y2))
    pixels = crop.load()
    cw, ch = crop.size
    row_ratios: list[float] = []
    for yy in range(ch):
        dark = 0
        for xx in range(cw):
            if pixels[xx, yy] < 220:
                dark += 1
        row_ratios.append(dark / max(cw, 1))
    runs = _segment_runs(row_ratios, threshold=0.01, min_len=3, max_gap=3)
    if len(runs) < 3:
        return bbox

    for idx in range(1, len(runs)):
        prev_end = runs[idx - 1][1]
        start = runs[idx][0]
        gap = start - prev_end - 1
        if start < int(ch * 0.48) or gap < 8:
            continue
        tail = runs[idx:]
        tail_height = sum(e - s + 1 for s, e in tail)
        tail_line_count = len(tail)
        tail_has_wide_line = False
        for s, e in tail:
            bounds = _find_dark_bounds(image, x1, y1 + s, x2, y1 + e + 1)
            if bounds is None:
                continue
            bx1, _by1, bx2, _by2 = bounds
            if bx2 - bx1 >= cw * 0.34:
                tail_has_wide_line = True
                break
        if tail_line_count >= 2 and tail_height <= max(90, int(ch * 0.42)) and tail_has_wide_line:
            new_y2 = y1 + start - 4
            if new_y2 > y1 + 72:
                return {
                    **bbox,
                    "h": new_y2 - y1,
                    "review_flags": normalize_review_flags(
                        list(bbox.get("review_flags", []) or []) + ["bottom_text_block_trimmed"]
                    ),
                }
    return bbox


def _try_extend_caption(image: Image.Image, bbox: dict, max_extra: int = 64) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    gray = image.convert("L")
    width, height = gray.size
    if y2 >= height - 8:
        return bbox

    strip_h = min(max_extra, height - y2)
    strip = gray.crop((max(x1 - 16, 0), y2, min(x2 + 16, width), y2 + strip_h))
    pixels = strip.load()
    strip_w, strip_height = strip.size
    row_ratios: list[float] = []
    for y in range(strip_height):
        dark = 0
        for x in range(strip_w):
            if pixels[x, y] < 220:
                dark += 1
        row_ratios.append(dark / max(strip_w, 1))
    rows = _segment_runs(row_ratios, threshold=0.01, min_len=5, max_gap=4)
    bounds = None
    if rows:
        top_row, bottom_row = rows[0]
        if bottom_row - top_row + 1 <= 26:
            bounds = _find_dark_bounds(
                gray,
                max(x1 - 16, 0),
                y2 + top_row,
                min(x2 + 16, width),
                y2 + bottom_row + 1,
            )

    if bounds is None:
        center_x = (x1 + x2) // 2
        narrow_left = max(center_x - max(36, (x2 - x1) // 5), 0)
        narrow_right = min(center_x + max(36, (x2 - x1) // 5), width)
        centered_bounds = _find_dark_bounds(
            gray,
            narrow_left,
            y2,
            narrow_right,
            y2 + strip_h,
        )
        if centered_bounds is None:
            return bbox
        cbx1, cby1, cbx2, cby2 = centered_bounds
        if cby2 - cby1 > 28 or cbx2 - cbx1 > int((x2 - x1) * 0.4):
            return bbox
        bounds = centered_bounds

    bx1, by1, bx2, by2 = bounds
    caption_w = bx2 - bx1
    if caption_w > int((x2 - x1) * 0.75):
        return bbox
    if abs(((bx1 + bx2) / 2) - ((x1 + x2) / 2)) > max(36, (x2 - x1) * 0.22):
        return bbox
    updated = dict(bbox)
    updated["x"] = min(x1, bx1)
    updated["y"] = min(y1, by1)
    updated["w"] = max(x2, bx2) - updated["x"]
    updated["h"] = max(y2, by2) - updated["y"]
    return updated


def _pad_public_figure_bbox(
    image: Image.Image,
    bbox: dict,
    *,
    pad_left: int = 10,
    pad_right: int = 10,
    pad_top: int = 8,
    pad_bottom: int = 16,
) -> dict:
    width, height = image.size
    x1 = max(int(bbox.get("x", 0) or 0) - pad_left, 0)
    y1 = max(int(bbox.get("y", 0) or 0) - pad_top, 0)
    x2 = min(int(bbox.get("x", 0) or 0) + int(bbox.get("w", 0) or 0) + pad_right, width)
    y2 = min(int(bbox.get("y", 0) or 0) + int(bbox.get("h", 0) or 0) + pad_bottom, height)
    return {
        **bbox,
        "x": x1,
        "y": y1,
        "w": max(x2 - x1, 1),
        "h": max(y2 - y1, 1),
    }


def _trim_trailing_body_text(image: Image.Image, bbox: dict, max_scan: int = 112) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    gray = image.convert("L")
    width, height = gray.size

    updated = dict(bbox)
    for _ in range(3):
        x1 = int(updated.get("x", 0) or 0)
        y1 = int(updated.get("y", 0) or 0)
        x2 = x1 + int(updated.get("w", 0) or 0)
        y2 = y1 + int(updated.get("h", 0) or 0)
        crop_h = y2 - y1
        crop_w = x2 - x1
        if crop_h < 80 or crop_w < 80:
            return updated

        scan_h = min(max_scan, max(crop_h // 3, 48))
        strip_top = max(y2 - scan_h, y1)
        strip = gray.crop((x1, strip_top, x2, y2))
        sw, sh = strip.size
        pixels = strip.load()
        row_ratios: list[float] = []
        for yy in range(sh):
            dark = 0
            for xx in range(sw):
                if pixels[xx, yy] < 220:
                    dark += 1
            row_ratios.append(dark / max(sw, 1))
        runs = _segment_runs(row_ratios, threshold=0.01, min_len=4, max_gap=3)
        if not runs:
            return updated

        start, end = runs[-1]
        bounds = _find_dark_bounds(gray, x1, strip_top + start, x2, strip_top + end + 1)
        if bounds is None:
            return updated
        bx1, by1, bx2, by2 = bounds
        run_w = bx2 - bx1
        run_h = by2 - by1
        run_center = (bx1 + bx2) / 2
        box_center = (x1 + x2) / 2
        centered = abs(run_center - box_center) <= max(28, crop_w * 0.16)
        narrow = run_w <= crop_w * 0.42
        wide = run_w >= crop_w * 0.55

        # Trim only obvious trailing text lines, not figure axes or centered short captions.
        if 8 <= run_h <= 34 and wide and not (centered and narrow):
            new_y2 = max(by1 - 4, y1 + 40)
            if new_y2 >= y2:
                return updated
            updated["h"] = new_y2 - y1
            continue
        return updated
    return updated


def _trim_leading_body_text(image: Image.Image, bbox: dict, max_scan: int = 112) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    gray = image.convert("L")

    updated = dict(bbox)
    for _ in range(3):
        x1 = int(updated.get("x", 0) or 0)
        y1 = int(updated.get("y", 0) or 0)
        x2 = x1 + int(updated.get("w", 0) or 0)
        y2 = y1 + int(updated.get("h", 0) or 0)
        crop_h = y2 - y1
        crop_w = x2 - x1
        if crop_h < 80 or crop_w < 80:
            return updated

        scan_h = min(max_scan, max(crop_h // 3, 48))
        strip_bottom = min(y1 + scan_h, y2)
        strip = gray.crop((x1, y1, x2, strip_bottom))
        sw, sh = strip.size
        pixels = strip.load()
        row_ratios: list[float] = []
        for yy in range(sh):
            dark = 0
            for xx in range(sw):
                if pixels[xx, yy] < 220:
                    dark += 1
            row_ratios.append(dark / max(sw, 1))
        runs = _segment_runs(row_ratios, threshold=0.01, min_len=4, max_gap=3)
        if not runs:
            return updated

        start, end = runs[0]
        bounds = _find_dark_bounds(gray, x1, y1 + start, x2, y1 + end + 1)
        if bounds is None:
            return updated
        bx1, by1, bx2, by2 = bounds
        run_w = bx2 - bx1
        run_h = by2 - by1
        run_center = (bx1 + bx2) / 2
        box_center = (x1 + x2) / 2
        centered = abs(run_center - box_center) <= max(28, crop_w * 0.16)
        narrow = run_w <= crop_w * 0.42
        wide = run_w >= crop_w * 0.55

        # Trim only obvious leading text lines, not figure captions or centered axis labels.
        if 8 <= run_h <= 34 and wide and not (centered and narrow):
            new_y1 = min(by2 + 4, y2 - 40)
            if new_y1 <= y1:
                return updated
            updated["y"] = new_y1
            updated["h"] = y2 - new_y1
            continue
        return updated
    return updated


def _trim_isolated_top_caption(image: Image.Image, bbox: dict, max_scan: int = 120) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    gray = image.convert("L")
    crop_h = y2 - y1
    crop_w = x2 - x1
    if crop_h < 90 or crop_w < 90:
        return bbox

    scan_h = min(max_scan, max(crop_h // 2, 56))
    strip = gray.crop((x1, y1, x2, min(y1 + scan_h, y2)))
    sw, sh = strip.size
    pixels = strip.load()
    row_ratios: list[float] = []
    for yy in range(sh):
        dark = 0
        for xx in range(sw):
            if pixels[xx, yy] < 220:
                dark += 1
        row_ratios.append(dark / max(sw, 1))
    runs = _segment_runs(row_ratios, threshold=0.01, min_len=3, max_gap=3)
    if len(runs) < 2:
        return bbox

    (s1, e1), (s2, _e2) = runs[0], runs[1]
    gap = s2 - e1 - 1
    bounds = _find_dark_bounds(gray, x1, y1 + s1, x2, y1 + e1 + 1)
    if bounds is None:
        return bbox
    bx1, by1, bx2, by2 = bounds
    run_w = bx2 - bx1
    run_h = by2 - by1
    centered = abs(((bx1 + bx2) / 2) - ((x1 + x2) / 2)) <= max(26, crop_w * 0.18)
    if 6 <= run_h <= 22 and run_w <= crop_w * 0.35 and centered and gap >= 6:
        new_y1 = min(y1 + s2 - 2, y2 - 40)
        if new_y1 > y1:
            return {
                **bbox,
                "y": new_y1,
                "h": y2 - new_y1,
            }
    return bbox


def _tighten_candidate_bbox(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    gray = image.convert("L")
    crop = gray.crop((x1, y1, x2, y2))
    cw, ch = crop.size
    pixels = crop.load()

    row_ratios: list[float] = []
    for y in range(ch):
        dark = 0
        for x in range(cw):
            if pixels[x, y] < 220:
                dark += 1
        row_ratios.append(dark / max(cw, 1))
    row_runs = _segment_runs(row_ratios, threshold=0.03, min_len=max(16, ch // 10), max_gap=5)
    if not row_runs:
        return bbox

    def _row_score(run: tuple[int, int]) -> float:
        start, end = run
        segment = row_ratios[start : end + 1]
        return (end - start + 1) * (sum(segment) / max(len(segment), 1))

    row_start, row_end = max(row_runs, key=_row_score)

    col_ratios: list[float] = []
    band_h = row_end - row_start + 1
    for x in range(cw):
        dark = 0
        for y in range(row_start, row_end + 1):
            if pixels[x, y] < 220:
                dark += 1
        col_ratios.append(dark / max(band_h, 1))
    col_runs = _segment_runs(col_ratios, threshold=0.03, min_len=max(18, cw // 10), max_gap=6)
    if not col_runs:
        return bbox

    def _col_score(run: tuple[int, int]) -> float:
        start, end = run
        segment = col_ratios[start : end + 1]
        return (end - start + 1) * (sum(segment) / max(len(segment), 1))

    col_start, col_end = max(col_runs, key=_col_score)
    bounds = _find_dark_bounds(
        image,
        max(x1 + col_start - 10, 0),
        max(y1 + row_start - 10, 0),
        x1 + col_end + 11,
        y1 + row_end + 11,
    )
    if bounds is None:
        return bbox
    bx1, by1, bx2, by2 = bounds
    return {
        **bbox,
        "x": bx1,
        "y": by1,
        "w": bx2 - bx1,
        "h": by2 - by1,
    }


def _trim_isolated_left_label_components(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    if x2 <= x1 or y2 <= y1:
        return bbox

    gray = image.convert("L")
    crop = gray.crop((x1, y1, x2, y2))
    cw, ch = crop.size
    if cw < 64 or ch < 48:
        return bbox

    pixels = crop.load()
    dark = [[pixels[x, y] < 220 for x in range(cw)] for y in range(ch)]
    visited = [[False for _ in range(cw)] for _ in range(ch)]
    components: list[dict] = []

    for sy in range(ch):
        for sx in range(cw):
            if visited[sy][sx] or not dark[sy][sx]:
                continue
            stack = [(sx, sy)]
            visited[sy][sx] = True
            min_x = max_x = sx
            min_y = max_y = sy
            area = 0
            while stack:
                px, py = stack.pop()
                area += 1
                if px < min_x:
                    min_x = px
                if px > max_x:
                    max_x = px
                if py < min_y:
                    min_y = py
                if py > max_y:
                    max_y = py
                for ny in range(max(py - 1, 0), min(py + 2, ch)):
                    for nx in range(max(px - 1, 0), min(px + 2, cw)):
                        if visited[ny][nx] or not dark[ny][nx]:
                            continue
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            width = max_x - min_x + 1
            height = max_y - min_y + 1
            if area >= 2:
                components.append(
                    {
                        "x1": min_x,
                        "y1": min_y,
                        "x2": max_x + 1,
                        "y2": max_y + 1,
                        "w": width,
                        "h": height,
                        "area": area,
                    }
                )

    if not components:
        return bbox

    anchors = [
        comp
        for comp in components
        if comp["area"] >= 18 and (comp["w"] >= 18 or comp["h"] >= 18)
    ]
    if not anchors:
        return bbox

    anchor_left = min(comp["x1"] for comp in anchors)
    anchor_top = min(comp["y1"] for comp in anchors)
    anchor_right = max(comp["x2"] for comp in anchors)
    anchor_bottom = max(comp["y2"] for comp in anchors)
    keep_margin = max(18, min(cw, ch) // 9)
    kept: list[dict] = []
    trimmed = False

    for comp in components:
        small_text_like = (
            comp["area"] <= 180
            and comp["w"] <= 28
            and comp["h"] <= 32
        )
        isolated_left = comp["x2"] < anchor_left - 4
        near_anchor = not (
            comp["x1"] > anchor_right + keep_margin
            or comp["x2"] < anchor_left - keep_margin
            or comp["y1"] > anchor_bottom + keep_margin
            or comp["y2"] < anchor_top - keep_margin
        )
        if isolated_left and small_text_like and not near_anchor:
            trimmed = True
            continue
        kept.append(comp)

    if not trimmed or not kept:
        return bbox

    new_x1 = max(min(comp["x1"] for comp in kept) - 4, 0)
    new_y1 = max(min(comp["y1"] for comp in kept) - 4, 0)
    new_x2 = min(max(comp["x2"] for comp in kept) + 4, cw)
    new_y2 = min(max(comp["y2"] for comp in kept) + 4, ch)
    new_w = new_x2 - new_x1
    new_h = new_y2 - new_y1
    if new_w < max(48, int(cw * 0.45)) or new_h < max(40, int(ch * 0.45)):
        return bbox

    return {
        **bbox,
        "x": x1 + new_x1,
        "y": y1 + new_y1,
        "w": new_w,
        "h": new_h,
        "review_flags": normalize_review_flags(
            list(bbox.get("review_flags", []) or []) + ["isolated_left_label_trimmed"]
        ),
    }


def _trim_left_label_by_vertical_gap(image: Image.Image, bbox: dict) -> dict:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    if x2 <= x1 or y2 <= y1:
        return bbox
    crop_w = x2 - x1
    crop_h = y2 - y1
    if crop_w < 90 or crop_h < 60:
        return bbox

    gray = image.convert("L").crop((x1, y1, x2, y2))
    pixels = gray.load()
    col_ratios: list[float] = []
    for xx in range(crop_w):
        dark = 0
        for yy in range(crop_h):
            if pixels[xx, yy] < 220:
                dark += 1
        col_ratios.append(dark / max(crop_h, 1))

    runs = _segment_runs(col_ratios, threshold=0.012, min_len=3, max_gap=2)
    if len(runs) < 2:
        return bbox
    first_start, first_end = runs[0]
    second_start, _second_end = runs[1]
    first_width = first_end - first_start + 1
    gap = second_start - first_end - 1
    first_near_edge = first_start <= 12
    second_substantial = second_start <= max(70, int(crop_w * 0.38))
    if first_near_edge and first_width <= 34 and gap >= 7 and second_substantial:
        new_x1 = x1 + max(second_start - 6, 0)
        if new_x1 < x2 - 72:
            return {
                **bbox,
                "x": new_x1,
                "w": x2 - new_x1,
                "review_flags": normalize_review_flags(
                    list(bbox.get("review_flags", []) or []) + ["left_label_gap_trimmed"]
                ),
            }
    return bbox


def _split_candidate_columns(image: Image.Image, bbox: dict) -> list[dict]:
    x1 = int(bbox.get("x", 0) or 0)
    y1 = int(bbox.get("y", 0) or 0)
    x2 = x1 + int(bbox.get("w", 0) or 0)
    y2 = y1 + int(bbox.get("h", 0) or 0)
    crop = image.convert("L").crop((x1, y1, x2, y2))
    cw, ch = crop.size
    if cw < 280:
        return [bbox]
    pixels = crop.load()
    col_ratios: list[float] = []
    for x in range(cw):
        dark = 0
        for y in range(ch):
            if pixels[x, y] < 220:
                dark += 1
        col_ratios.append(dark / max(ch, 1))

    valley_threshold = min(0.012, max(min(col_ratios) + 0.004, 0.006))
    valley_runs: list[tuple[int, int]] = []
    start = -1
    for idx, value in enumerate(col_ratios):
        if value <= valley_threshold:
            if start < 0:
                start = idx
            continue
        if start >= 0:
            valley_runs.append((start, idx - 1))
            start = -1
    if start >= 0:
        valley_runs.append((start, len(col_ratios) - 1))

    usable_valleys = [
        (start, end)
        for start, end in valley_runs
        if end - start + 1 >= max(12, cw // 24)
        and start >= max(42, cw // 8)
        and end <= cw - max(42, cw // 8)
    ]
    if usable_valleys:
        usable_valleys.sort(key=lambda run: (run[1] - run[0] + 1), reverse=True)
        split_start, split_end = usable_valleys[0]
        segments = [
            (0, max(split_start - 1, 0)),
            (min(split_end + 1, cw - 1), cw - 1),
        ]
        results: list[dict] = []
        for seg_start, seg_end in segments:
            if seg_end - seg_start + 1 < max(56, cw // 5):
                continue
            bounds = _find_dark_bounds(
                image,
                max(x1 + seg_start - 10, 0),
                y1,
                min(x1 + seg_end + 11, image.size[0]),
                y2,
            )
            if bounds is None:
                continue
            bx1, by1, bx2, by2 = bounds
            results.append(
                {
                    **bbox,
                    "x": bx1,
                    "y": by1,
                    "w": bx2 - bx1,
                    "h": by2 - by1,
                }
            )
        if len(results) >= 2:
            return results

    col_runs = _segment_runs(col_ratios, threshold=0.02, min_len=max(24, cw // 8), max_gap=10)
    if len(col_runs) <= 1 or len(col_runs) > 4:
        return [bbox]

    results: list[dict] = []
    for col_start, col_end in col_runs:
        bounds = _find_dark_bounds(
            image,
            max(x1 + col_start - 10, 0),
            y1,
            min(x1 + col_end + 11, image.size[0]),
            y2,
        )
        if bounds is None:
            continue
        bx1, by1, bx2, by2 = bounds
        results.append(
            {
                **bbox,
                "x": bx1,
                "y": by1,
                "w": bx2 - bx1,
                "h": by2 - by1,
            }
        )
    return results or [bbox]


def _complete_sparse_grid_boxes(image: Image.Image, items: list[dict]) -> list[dict]:
    if len(items) != 3:
        return items
    centers_x = sorted((int(item["x"]) + int(item["w"]) / 2, idx) for idx, item in enumerate(items))
    centers_y = sorted((int(item["y"]) + int(item["h"]) / 2, idx) for idx, item in enumerate(items))
    left_x, right_x = centers_x[0][0], centers_x[-1][0]
    top_y, bottom_y = centers_y[0][0], centers_y[-1][0]
    if right_x - left_x < 120 or bottom_y - top_y < 70:
        return items

    rows = {
        "top": [items[idx] for value, idx in centers_y if value <= top_y + (bottom_y - top_y) * 0.3],
        "bottom": [items[idx] for value, idx in centers_y if value >= bottom_y - (bottom_y - top_y) * 0.3],
    }
    cols = {
        "left": [items[idx] for value, idx in centers_x if value <= left_x + (right_x - left_x) * 0.3],
        "right": [items[idx] for value, idx in centers_x if value >= right_x - (right_x - left_x) * 0.3],
    }
    if not rows["top"] or not rows["bottom"] or not cols["left"] or not cols["right"]:
        return items

    avg_w = int(sum(int(item["w"]) for item in items) / len(items))
    avg_h = int(sum(int(item["h"]) for item in items) / len(items))
    x_margin = max(24, avg_w // 4)
    y_margin = max(24, avg_h // 4)

    occupied: set[tuple[str, str]] = set()
    for item in items:
        cx = int(item["x"]) + int(item["w"]) / 2
        cy = int(item["y"]) + int(item["h"]) / 2
        col_key = "left" if abs(cx - left_x) <= abs(cx - right_x) else "right"
        row_key = "top" if abs(cy - top_y) <= abs(cy - bottom_y) else "bottom"
        occupied.add((row_key, col_key))

    all_slots = {("top", "left"), ("top", "right"), ("bottom", "left"), ("bottom", "right")}
    missing_slots = list(all_slots - occupied)
    if len(missing_slots) != 1:
        return items

    row_key, col_key = missing_slots[0]
    ref_row = rows[row_key][0]
    ref_col = cols[col_key][0]
    target_cx = int(ref_col["x"]) + int(ref_col["w"]) / 2
    target_cy = int(ref_row["y"]) + int(ref_row["h"]) / 2
    search_x1 = max(int(target_cx - avg_w / 2 - x_margin), 0)
    search_y1 = max(int(target_cy - avg_h / 2 - y_margin), 0)
    search_x2 = min(int(target_cx + avg_w / 2 + x_margin), image.size[0])
    search_y2 = min(int(target_cy + avg_h / 2 + y_margin), image.size[1])
    bounds = _find_dark_bounds(image, search_x1, search_y1, search_x2, search_y2)
    if bounds is None:
        return items
    bx1, by1, bx2, by2 = bounds
    candidate = {
        "x": bx1,
        "y": by1,
        "w": bx2 - bx1,
        "h": by2 - by1,
        "confidence": 0.66,
        "review_flags": ["option_anchor_low_confidence", "grid_completed_fallback"],
    }
    candidate = _tighten_candidate_bbox(image, candidate)
    if not _looks_figure_like_bbox(candidate, image_width=image.size[0], image_height=image.size[1]):
        return items
    return items + [candidate]


def _merge_nearby_boxes(items: list[dict], gap: int = 16) -> list[dict]:
    boxes = [
        {
            "x": int(item.get("x", 0) or 0),
            "y": int(item.get("y", 0) or 0),
            "w": int(item.get("w", 0) or 0),
            "h": int(item.get("h", 0) or 0),
            "confidence": float(item.get("confidence", 0.0) or 0.0),
            "review_flags": list(item.get("review_flags", []) or []),
        }
        for item in items
        if int(item.get("w", 0) or 0) > 0 and int(item.get("h", 0) or 0) > 0
    ]
    merged: list[dict] = []
    while boxes:
        current = boxes.pop(0)
        changed = True
        while changed:
            changed = False
            remaining: list[dict] = []
            cx1, cy1 = current["x"], current["y"]
            cx2, cy2 = current["x"] + current["w"], current["y"] + current["h"]
            for other in boxes:
                ox1, oy1 = other["x"], other["y"]
                ox2, oy2 = other["x"] + other["w"], other["y"] + other["h"]
                close = not (ox1 > cx2 + gap or ox2 < cx1 - gap or oy1 > cy2 + gap or oy2 < cy1 - gap)
                if close:
                    nx1, ny1 = min(cx1, ox1), min(cy1, oy1)
                    nx2, ny2 = max(cx2, ox2), max(cy2, oy2)
                    current["x"], current["y"] = nx1, ny1
                    current["w"], current["h"] = nx2 - nx1, ny2 - ny1
                    current["confidence"] = max(float(current.get("confidence", 0.0) or 0.0), float(other.get("confidence", 0.0) or 0.0))
                    current["review_flags"] = normalize_review_flags(list(current.get("review_flags", []) or []) + list(other.get("review_flags", []) or []))
                    cx1, cy1, cx2, cy2 = nx1, ny1, nx2, ny2
                    changed = True
                else:
                    remaining.append(other)
            boxes = remaining
        merged.append(current)
    return merged


def _heuristic_public_figure_regions(image_path: Path, source_field_name: str = "") -> list[dict]:
    with Image.open(image_path) as original:
        gray = original.convert("L")
        width, height = gray.size
        scale = 2 if max(width, height) >= 1400 else 1
        small = gray.resize((max(width // scale, 1), max(height // scale, 1))) if scale > 1 else gray
        sw, sh = small.size
        pixels = small.load()

        row_ratios: list[float] = []
        for y in range(sh):
            dark = 0
            for x in range(sw):
                if pixels[x, y] < 220:
                    dark += 1
            row_ratios.append(dark / max(sw, 1))

        row_runs = _segment_runs(
            row_ratios,
            threshold=0.012,
            min_len=max(18, int(sh * 0.02)),
            max_gap=10,
        )

        candidates: list[dict] = []
        for row_start, row_end in row_runs:
            band_h = row_end - row_start + 1
            if band_h < max(28, int(sh * 0.04)):
                continue
            col_ratios: list[float] = []
            for x in range(sw):
                dark = 0
                for y in range(row_start, row_end + 1):
                    if pixels[x, y] < 220:
                        dark += 1
                col_ratios.append(dark / max(band_h, 1))

            col_runs = _segment_runs(
                col_ratios,
                threshold=0.02,
                min_len=max(22, int(sw * 0.035)),
                max_gap=10,
            )
            for col_start, col_end in col_runs:
                bounds = _find_dark_bounds(
                    original,
                    max(col_start * scale - 12, 0),
                    max(row_start * scale - 12, 0),
                    min((col_end + 1) * scale + 12, width),
                    min((row_end + 1) * scale + 12, height),
                )
                if bounds is None:
                    continue
                x1, y1, x2, y2 = bounds
                candidate = {
                    "x": x1,
                    "y": y1,
                    "w": x2 - x1,
                    "h": y2 - y1,
                    "confidence": 0.72,
                    "review_flags": ["option_anchor_low_confidence"],
                }
                if not _looks_figure_like_bbox(candidate, image_width=width, image_height=height):
                    continue
                split_candidates = _split_candidate_columns(original, candidate)
                for part in split_candidates:
                    part = _tighten_candidate_bbox(original, part)
                    part = _try_extend_caption(original, part)
                    if not _looks_figure_like_bbox(part, image_width=width, image_height=height):
                        continue
                    candidates.append(part)

        merged = _merge_nearby_boxes(candidates, gap=18)
        refined = _sanitize_public_boxes(
            merged,
            image=original.copy(),
            image_width=width,
            image_height=height,
            source_field_name=source_field_name,
        )
    return [
        box
        for box in refined
        if _looks_figure_like_bbox(box, image_width=width, image_height=height)
    ]


def _dedupe_public_boxes(items: list[dict]) -> list[dict]:
    seen: set[tuple[int, int, int, int]] = set()
    result: list[dict] = []
    for item in items:
        key = (
            int(item.get("x", 0) or 0),
            int(item.get("y", 0) or 0),
            int(item.get("w", 0) or 0),
            int(item.get("h", 0) or 0),
        )
        if key in seen or key[2] <= 0 or key[3] <= 0:
            continue
        seen.add(key)
        result.append(item)
    return result


def _bbox_iou(a: dict, b: dict) -> float:
    ax1 = int(a.get("x", 0) or 0)
    ay1 = int(a.get("y", 0) or 0)
    ax2 = ax1 + int(a.get("w", 0) or 0)
    ay2 = ay1 + int(a.get("h", 0) or 0)
    bx1 = int(b.get("x", 0) or 0)
    by1 = int(b.get("y", 0) or 0)
    bx2 = bx1 + int(b.get("w", 0) or 0)
    by2 = by1 + int(b.get("h", 0) or 0)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(ax2 - ax1, 0) * max(ay2 - ay1, 0)
    area_b = max(bx2 - bx1, 0) * max(by2 - by1, 0)
    return inter / max(area_a + area_b - inter, 1)


def _dedupe_overlapping_public_boxes(items: list[dict], iou_threshold: float = 0.62) -> list[dict]:
    ordered = sorted(
        [dict(item) for item in items if int(item.get("w", 0) or 0) > 0 and int(item.get("h", 0) or 0) > 0],
        key=lambda item: float(item.get("confidence", 0.0) or 0.0),
        reverse=True,
    )
    kept: list[dict] = []
    for item in ordered:
        if any(_bbox_iou(item, existing) >= iou_threshold for existing in kept):
            continue
        kept.append(item)
    return sorted(kept, key=lambda item: (int(item.get("y", 0) or 0), int(item.get("x", 0) or 0)))


def _sanitize_public_boxes(
    items: list[dict],
    *,
    image: Image.Image,
    image_width: int,
    image_height: int,
    source_field_name: str = "",
) -> list[dict]:
    result: list[dict] = []
    for item in items:
        if not _looks_figure_like_bbox(item, image_width=image_width, image_height=image_height):
            continue
        split_candidates = _split_candidate_columns(image, item)
        for part in split_candidates:
            coordinate_mode = str(part.get("bbox_coordinate_mode", "") or "")
            if coordinate_mode in {"model_canvas", "normalized_1000"}:
                part = _trim_colored_header_strip(image, part)
                part = _pad_public_figure_bbox(
                    image,
                    part,
                    pad_left=24,
                    pad_right=12,
                    pad_top=10,
                    pad_bottom=10,
                )
                part = _trim_isolated_left_label_components(image, part)
                part = _trim_colored_header_strip(image, part)
                part = _trim_red_teacher_text_edges(image, part)
                part = _trim_left_label_by_vertical_gap(image, part)
                part = _trim_leading_body_text(image, part)
                part = _trim_isolated_top_caption(image, part)
                part = _trim_trailing_body_text(image, part)
                part = _trim_red_teacher_text_edges(image, part)
                part = _trim_bottom_text_block_after_gap(image, part)
                if _looks_like_text_false_positive(image, part):
                    continue
                if not _looks_figure_like_bbox(part, image_width=image_width, image_height=image_height):
                    continue
                result.append(part)
                continue
            part = _tighten_candidate_bbox(image, part)
            part = _trim_leading_body_text(image, part)
            part = _trim_isolated_top_caption(image, part)
            part = _trim_colored_header_strip(image, part)
            part = _trim_red_teacher_text_edges(image, part)
            part = _try_extend_caption(image, part)
            part = _pad_public_figure_bbox(image, part)
            part = _trim_trailing_body_text(image, part)
            part = _trim_bottom_text_block_after_gap(image, part)
            if source_field_name == "question_image":
                part = _pad_public_figure_bbox(
                    image,
                    part,
                    pad_left=12,
                    pad_right=12,
                    pad_top=26,
                    pad_bottom=0,
                )
            elif source_field_name == "stem_image":
                part = _pad_public_figure_bbox(
                    image,
                    part,
                    pad_left=10,
                    pad_right=10,
                    pad_top=24,
                    pad_bottom=8,
                )
            elif source_field_name == "analysis_image":
                part = _pad_public_figure_bbox(
                    image,
                    part,
                    pad_left=6,
                    pad_right=6,
                    pad_top=8,
                    pad_bottom=0,
                )
            part = _trim_colored_header_strip(image, part)
            part = _trim_red_teacher_text_edges(image, part)
            part = _trim_left_label_by_vertical_gap(image, part)
            part = _trim_bottom_text_block_after_gap(image, part)
            if _looks_like_text_false_positive(image, part):
                continue
            if not _looks_figure_like_bbox(part, image_width=image_width, image_height=image_height):
                continue
            result.append(part)
    result = _dedupe_public_boxes(result)
    result = _complete_sparse_grid_boxes(image, result)
    result = [
        item
        for item in result
        if _looks_figure_like_bbox(item, image_width=image_width, image_height=image_height)
        and not _looks_like_text_false_positive(image, item)
    ]
    return _dedupe_public_boxes(result)


def _refine_public_boxes_with_model(
    image: Image.Image,
    boxes: list[dict],
    *,
    api_key: str,
    model: str,
) -> list[dict]:
    if not api_key or not boxes:
        return boxes

    image_width, image_height = image.size
    refined: list[dict] = []
    for box in boxes:
        x1 = max(int(box.get("x", 0) or 0) - 36, 0)
        y1 = max(int(box.get("y", 0) or 0) - 36, 0)
        x2 = min(int(box.get("x", 0) or 0) + int(box.get("w", 0) or 0) + 36, image_width)
        y2 = min(int(box.get("y", 0) or 0) + int(box.get("h", 0) or 0) + 36, image_height)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image.crop((x1, y1, x2, y2))
        try:
            payload = _call_inline_figure_refine_model(api_key, model, crop)
        except Exception:
            kept = dict(box)
            kept["review_flags"] = normalize_review_flags(
                list(kept.get("review_flags", []) or []) + ["inline_figure_refine_model_failed"]
            )
            refined.append(kept)
            continue

        is_valid = bool(payload.get("is_valid_figure", True))
        if not is_valid:
            continue
        raw_bbox = payload.get("bbox", {})
        candidate = _normalize_bbox(raw_bbox)
        canvas_w = int(payload.get("image_width", 1000) or 1000)
        canvas_h = int(payload.get("image_height", 1000) or 1000)
        if candidate["w"] <= 0 or candidate["h"] <= 0 or canvas_w <= 0 or canvas_h <= 0:
            kept = dict(box)
            kept["review_flags"] = normalize_review_flags(
                list(kept.get("review_flags", []) or []) + ["inline_figure_refine_bbox_invalid"]
            )
            refined.append(kept)
            continue

        crop_w = x2 - x1
        crop_h = y2 - y1
        nx1 = x1 + round(candidate["x"] / canvas_w * crop_w)
        ny1 = y1 + round(candidate["y"] / canvas_h * crop_h)
        nx2 = x1 + round((candidate["x"] + candidate["w"]) / canvas_w * crop_w)
        ny2 = y1 + round((candidate["y"] + candidate["h"]) / canvas_h * crop_h)
        nx1 = max(0, min(nx1, image_width - 1))
        ny1 = max(0, min(ny1, image_height - 1))
        nx2 = max(nx1 + 1, min(nx2, image_width))
        ny2 = max(ny1 + 1, min(ny2, image_height))

        updated = {
            **box,
            "x": nx1,
            "y": ny1,
            "w": nx2 - nx1,
            "h": ny2 - ny1,
            "pre_refine_bbox_json": {
                "x": int(box.get("x", 0) or 0),
                "y": int(box.get("y", 0) or 0),
                "w": int(box.get("w", 0) or 0),
                "h": int(box.get("h", 0) or 0),
            },
            "refine_crop_bbox_json": {"x": x1, "y": y1, "w": crop_w, "h": crop_h},
            "refine_model_bbox_json": dict(raw_bbox) if isinstance(raw_bbox, dict) else raw_bbox,
            "figure_refine_source": "vision_model",
            "figure_refine_confidence": float(payload.get("confidence", 0.0) or 0.0),
            "review_flags": normalize_review_flags(
                list(box.get("review_flags", []) or []) + list(payload.get("review_flags", []) or [])
            ),
        }
        pre_w = max(int(box.get("w", 0) or 0), 1)
        pre_h = max(int(box.get("h", 0) or 0), 1)
        top_shift = ny1 - int(box.get("y", 0) or 0)
        left_shift = nx1 - int(box.get("x", 0) or 0)
        area_ratio = ((nx2 - nx1) * (ny2 - ny1)) / max(pre_w * pre_h, 1)
        shrink_too_much = area_ratio < 0.72
        shifted_too_much = top_shift > max(22, int(pre_h * 0.12)) or left_shift > max(22, int(pre_w * 0.12))
        if shrink_too_much or shifted_too_much:
            kept = dict(box)
            kept["pre_refine_bbox_json"] = {
                "x": int(box.get("x", 0) or 0),
                "y": int(box.get("y", 0) or 0),
                "w": int(box.get("w", 0) or 0),
                "h": int(box.get("h", 0) or 0),
            }
            kept["rejected_refine_bbox_json"] = {
                "x": nx1,
                "y": ny1,
                "w": nx2 - nx1,
                "h": ny2 - ny1,
                "top_shift": top_shift,
                "left_shift": left_shift,
                "area_ratio": round(area_ratio, 4),
            }
            kept["refine_crop_bbox_json"] = {"x": x1, "y": y1, "w": crop_w, "h": crop_h}
            kept["refine_model_bbox_json"] = dict(raw_bbox) if isinstance(raw_bbox, dict) else raw_bbox
            kept["figure_refine_source"] = "vision_model_rejected"
            kept["figure_refine_confidence"] = float(payload.get("confidence", 0.0) or 0.0)
            kept["review_flags"] = normalize_review_flags(
                list(box.get("review_flags", []) or []) + ["inline_figure_refine_shrink_rejected"]
            )
            refined.append(kept)
            continue
        if _looks_figure_like_bbox(updated, image_width=image_width, image_height=image_height) and not _looks_like_text_false_positive(image, updated):
            refined.append(updated)
    return _dedupe_public_boxes(refined)


def _detect_public_figures_in_vertical_tiles(
    image: Image.Image,
    *,
    api_key: str,
    model: str,
    bbox_space: str,
    hint_text: str = "",
) -> list[dict]:
    width, height = image.size
    if not api_key or height < 1300 or height < width * 1.55:
        return []

    tile_h = min(max(int(width * 1.25), 900), 1350)
    overlap = min(220, max(120, tile_h // 6))
    step = max(tile_h - overlap, 1)
    y_positions: list[int] = []
    y = 0
    while y < height:
        y_positions.append(y)
        if y + tile_h >= height:
            break
        y += step
    if y_positions and y_positions[-1] + tile_h < height:
        y_positions.append(max(height - tile_h, 0))

    boxes: list[dict] = []
    for tile_index, y1 in enumerate(y_positions, start=1):
        y2 = min(y1 + tile_h, height)
        if y2 - y1 < 240:
            continue
        tile = image.crop((0, y1, width, y2))
        try:
            payload = _call_inline_figure_model_on_image(
                api_key,
                model,
                tile,
                bbox_space=f"{bbox_space}_tile_{tile_index}",
                hint_text=hint_text,
            )
        except Exception:
            continue
        raw_boxes = [_normalize_public_image_bbox(item) for item in (payload.get("image_bboxes", []) or [])]
        scaled = _scale_model_canvas_boxes(
            [item for item in raw_boxes if item],
            model_image_width=int(payload.get("image_width", 0) or 0),
            model_image_height=int(payload.get("image_height", 0) or 0),
            image_width=width,
            image_height=y2 - y1,
            image=tile.copy(),
        )
        for item in scaled:
            mapped = dict(item)
            mapped["y"] = int(mapped.get("y", 0) or 0) + y1
            mapped["detector_source"] = "vision_model_tile"
            mapped["tile_bbox_json"] = {"x": 0, "y": y1, "w": width, "h": y2 - y1}
            mapped["tile_index"] = tile_index
            boxes.append(mapped)
    return _dedupe_overlapping_public_boxes(boxes)


def _should_run_vertical_tile_detection(image_width: int, image_height: int, boxes: list[dict]) -> bool:
    if image_height < 1300 or image_height < image_width * 1.55:
        return False
    if not boxes:
        return True
    if len(boxes) < 3:
        return True

    centers_y = [
        int(item.get("y", 0) or 0) + int(item.get("h", 0) or 0) / 2
        for item in boxes
        if int(item.get("w", 0) or 0) > 0 and int(item.get("h", 0) or 0) > 0
    ]
    if not centers_y:
        return True
    has_lower_half_figure = any(center >= image_height * 0.55 for center in centers_y)
    if not has_lower_half_figure:
        return True

    top = min(int(item.get("y", 0) or 0) for item in boxes)
    bottom = max(int(item.get("y", 0) or 0) + int(item.get("h", 0) or 0) for item in boxes)
    vertical_span = bottom - top
    return vertical_span < image_height * 0.38


def _same_long_source(question: dict) -> bool:
    question_image_raw = str(question.get("question_image", "") or "").strip()
    stem_image_raw = str(question.get("stem_image", "") or "").strip()
    analysis_image_raw = str(question.get("analysis_image", "") or "").strip()
    return bool(
        question_image_raw
        and stem_image_raw
        and analysis_image_raw
        and Path(question_image_raw) == Path(stem_image_raw) == Path(analysis_image_raw)
    )


def _should_use_panel_long_branch(
    question: dict,
    *,
    source_field: str,
    rescan_scope: str,
    image_width: int,
    image_height: int,
) -> bool:
    gate = question.get("image_need_gate") if isinstance(question.get("image_need_gate"), dict) else {}
    image_presence = str(gate.get("image_presence", "") or "").strip().lower()
    long_image = image_height >= 1300 or image_height >= image_width * 1.55
    planner_panel = "panel" in image_presence or image_presence in {"mixed", "graph", "geometry", "small_auxiliary_figure"}
    if _same_long_source(question):
        return True
    if source_field != "question_image":
        return False
    if long_image:
        return True
    if rescan_scope == "stem" and planner_panel:
        return True
    return False


def detect_public_figure_regions(
    question: dict,
    *,
    api_key: str = "",
    model: str = "",
    require_model: bool = False,
    allow_heuristic_fallback: bool = True,
) -> dict:
    api_key_value = str(api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    model_name = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    result = {
        "stem_image_bboxes": [],
        "analysis_image_bboxes": [],
        "global_review_flags": [],
        "detector": "not_run",
        "model_required": bool(require_model),
        "heuristic_fallback_allowed": bool(allow_heuristic_fallback),
    }
    if require_model and not api_key_value:
        result["global_review_flags"] = ["public_figure_model_not_run_missing_api_key"]
        return result

    image_targets: list[tuple[str, str, str]] = []
    stem_image_raw = str(question.get("stem_image", "") or "").strip()
    question_image_raw = str(question.get("question_image", "") or "").strip()
    analysis_image_raw = str(question.get("analysis_image", "") or "").strip()
    same_long_source = _same_long_source(question)
    if same_long_source:
        # Packaged samples can store the same long question crop in all three
        # fields. Probe the same container with both whole-question and stem
        # prompts, then merge by bbox overlap. This keeps recall for labeled
        # figures such as 图1/图2/图3 without image-similarity dedupe.
        image_targets.append(("question_image", "stem_image_bboxes", "question_image"))
        image_targets.append(("stem_image", "stem_image_bboxes", "question_image"))
    elif stem_image_raw:
        image_targets.append(("stem_image", "stem_image_bboxes", "stem_image"))
    elif question_image_raw:
        # Legacy or packaged samples may only preserve the whole question crop.
        # In that case, still attempt public-figure extraction from question_image.
        image_targets.append(("question_image", "stem_image_bboxes", "question_image"))
    if analysis_image_raw and not same_long_source:
        image_targets.append(("analysis_image", "analysis_image_bboxes", "analysis_image"))

    for field_name, bucket_name, output_bbox_space in image_targets:
        image_path_raw = str(question.get(field_name, "") or "").strip()
        if not image_path_raw:
            continue
        image_path = Path(image_path_raw)
        if not image_path.exists():
            continue
        width, height = _read_image_meta(image_path)
        hint_text = "\n".join(
            part
            for part in (
                str(question.get("stem_text", "") or ""),
                str(question.get("analysis_text", "") or "") if field_name == "analysis_image" else "",
                str(question.get("transcription_ocr", "") or ""),
            )
            if part.strip()
        )
        payload = {}
        model_attempted = False
        model_failed = False
        if api_key_value:
            try:
                model_attempted = True
                payload = _call_inline_figure_model(api_key_value, model_name, image_path, field_name, hint_text)
            except Exception:
                model_failed = True
                payload = {}
        detector_source = "vision_model"
        with Image.open(image_path) as original:
            boxes = [_normalize_public_image_bbox(item) for item in (payload.get("image_bboxes", []) or [])]
            boxes = _scale_model_canvas_boxes(
                [item for item in boxes if item],
                model_image_width=int(payload.get("image_width", 0) or 0),
                model_image_height=int(payload.get("image_height", 0) or 0),
                image_width=width,
                image_height=height,
                image=original.copy(),
            )
            normalized_boxes = _sanitize_public_boxes(
                boxes,
                image=original.copy(),
                image_width=width,
                image_height=height,
                source_field_name=field_name,
            )
            if api_key_value and _should_run_vertical_tile_detection(width, height, normalized_boxes):
                tile_boxes = _detect_public_figures_in_vertical_tiles(
                    original.copy(),
                    api_key=api_key_value,
                    model=model_name,
                    bbox_space=field_name,
                    hint_text=hint_text,
                )
                if tile_boxes:
                    tile_boxes = _sanitize_public_boxes(
                        tile_boxes,
                        image=original.copy(),
                        image_width=width,
                        image_height=height,
                        source_field_name=field_name,
                    )
                    normalized_boxes = _dedupe_overlapping_public_boxes(normalized_boxes + tile_boxes)
        safe_empty_fallback = bool(allow_heuristic_fallback) or (model_attempted and not model_failed)
        if not normalized_boxes and safe_empty_fallback:
            normalized_boxes = _dedupe_public_boxes(_heuristic_public_figure_regions(image_path, source_field_name=field_name))
            detector_source = "heuristic_fallback" if allow_heuristic_fallback else "vision_model_empty_safe_fallback"
        elif not normalized_boxes:
            detector_source = "vision_model_empty" if model_attempted else "model_not_run"
            if model_failed:
                result["global_review_flags"] = normalize_review_flags(
                    list(result.get("global_review_flags", [])) + ["public_figure_model_call_failed"]
                )
            elif model_attempted:
                result["global_review_flags"] = normalize_review_flags(
                    list(result.get("global_review_flags", [])) + ["public_figure_model_empty"]
                )
            else:
                result["global_review_flags"] = normalize_review_flags(
                    list(result.get("global_review_flags", [])) + ["public_figure_model_not_run"]
                )
        if normalized_boxes and api_key_value:
            with Image.open(image_path) as original:
                refined_boxes = _refine_public_boxes_with_model(
                    original.copy(),
                    normalized_boxes,
                    api_key=api_key_value,
                    model=model_name,
                )
            if refined_boxes:
                normalized_boxes = _dedupe_overlapping_public_boxes(refined_boxes, iou_threshold=0.86)
                detector_source = f"{detector_source}+refine_model"
            else:
                normalized_boxes = [
                    {
                        **item,
                        "review_flags": normalize_review_flags(
                            list(item.get("review_flags", []) or []) + ["inline_figure_refine_all_rejected_keep_coarse"]
                        ),
                    }
                    for item in normalized_boxes
                ]
                detector_source = f"{detector_source}+refine_model_empty_keep_coarse"
                result["global_review_flags"] = normalize_review_flags(
                    list(result.get("global_review_flags", [])) + ["inline_figure_refine_all_rejected"]
                )
        for item in normalized_boxes:
            item["bbox_space"] = output_bbox_space
            if item.get("figure_refine_source"):
                base_source = str(item.get("detector_source", "") or detector_source)
                if "refine_model" not in base_source:
                    base_source = f"{base_source}+refine_model"
                item["detector_source"] = base_source
            else:
                item["detector_source"] = str(item.get("detector_source", "") or detector_source)
        result[bucket_name] = _dedupe_overlapping_public_boxes(
            list(result.get(bucket_name, []) or []) + normalized_boxes,
            iou_threshold=0.82,
        )
        result["detector"] = detector_source
        result["global_review_flags"] = normalize_review_flags(
            list(result.get("global_review_flags", [])) + list(payload.get("global_review_flags", []) or [])
        )
    gate = question.get("image_need_gate") if isinstance(question.get("image_need_gate"), dict) else {}
    gate_where = {str(item or "").strip().lower() for item in (gate.get("where", []) if isinstance(gate.get("where", []), list) else [])}
    needs_figure_detection = bool(gate.get("needs_figure_detection"))
    stem_requested = needs_figure_detection and "stem" in gate_where
    analysis_requested = needs_figure_detection and (
        "analysis" in gate_where or "answer" in gate_where or "solution" in gate_where
    )
    has_stem_candidate = bool(result.get("stem_image_bboxes"))
    has_analysis_candidate = bool(result.get("analysis_image_bboxes")) or any(
        str(item.get("bbox_space", "") or "") == "question_image"
        for item in (result.get("stem_image_bboxes", []) or [])
    )
    zero_asset_rescan_requests: list[tuple[str, str, str, str]] = []
    if stem_requested and not has_stem_candidate:
        source_field = "question_image" if question_image_raw else ("stem_image" if stem_image_raw else "analysis_image")
        source_raw = question_image_raw or stem_image_raw or analysis_image_raw
        if source_raw:
            zero_asset_rescan_requests.append(("stem", "stem_image_bboxes", source_field, source_raw))
    if analysis_requested and not has_analysis_candidate:
        source_field = "analysis_image" if analysis_image_raw and not same_long_source else "question_image"
        source_raw = analysis_image_raw if source_field == "analysis_image" else (question_image_raw or stem_image_raw or analysis_image_raw)
        if source_raw:
            zero_asset_rescan_requests.append(("analysis", "analysis_image_bboxes" if source_field == "analysis_image" else "stem_image_bboxes", source_field, source_raw))

    for rescan_scope, bucket_name, source_field, source_raw in zero_asset_rescan_requests:
        image_presence = str(gate.get("image_presence", "") or f"{rescan_scope}_figure")
        if source_raw and Path(source_raw).exists():
            image_path = Path(source_raw)
            width, height = _read_image_meta(image_path)
            use_panel_long_branch = _should_use_panel_long_branch(
                question,
                source_field=source_field,
                rescan_scope=rescan_scope,
                image_width=width,
                image_height=height,
            )
            try:
                with Image.open(image_path) as original:
                    if rescan_scope == "analysis" and not use_panel_long_branch:
                        payload = _call_analysis_figure_rescan_model(
                            api_key_value,
                            model_name,
                            original.convert("RGB"),
                            image_presence,
                        )
                    else:
                        payload = _call_public_figure_rescan_model(
                            api_key_value,
                            model_name,
                            original.convert("RGB"),
                            image_presence=image_presence,
                            target_scope=rescan_scope,
                        )
                    raw_boxes = [_normalize_public_image_bbox(item) for item in (payload.get("image_bboxes", []) or [])]
                    if "number_line" in image_presence:
                        raw_boxes = [
                            {
                                **item,
                                "review_flags": normalize_review_flags(list(item.get("review_flags", []) or []) + ["number_line"]),
                            }
                            for item in raw_boxes
                        ]
                    rescanned = _scale_model_canvas_boxes(
                        [item for item in raw_boxes if item],
                        model_image_width=int(payload.get("image_width", 0) or 0),
                        model_image_height=int(payload.get("image_height", 0) or 0),
                        image_width=width,
                        image_height=height,
                        image=original.copy(),
                    )
                    accepted = []
                    for item in rescanned:
                        flags = set(str(flag) for flag in (item.get("review_flags", []) or []))
                        if not _looks_figure_like_bbox(item, image_width=width, image_height=height):
                            continue
                        if "number_line" not in flags and _looks_like_text_false_positive(original.copy(), item):
                            continue
                        accepted.append(
                            {
                                **item,
                                "bbox_space": "analysis_image" if source_field == "analysis_image" else "question_image",
                                "detector_source": f"{rescan_scope}_zero_asset_rescan_model",
                                "review_flags": normalize_review_flags(
                                    list(item.get("review_flags", []) or [])
                                    + [f"{rescan_scope}_zero_asset_rescan"]
                                    + (["long_image_branch"] if use_panel_long_branch else [])
                                ),
                            }
                        )
                    if not accepted and use_panel_long_branch and api_key_value and rescan_scope == "stem":
                        tile_boxes = _detect_public_figures_in_vertical_tiles(
                            original.copy(),
                            api_key=api_key_value,
                            model=model_name,
                            bbox_space=source_field,
                            hint_text=str(question.get("stem_text", "") or ""),
                        )
                        if tile_boxes:
                            tile_boxes = _sanitize_public_boxes(
                                tile_boxes,
                                image=original.copy(),
                                image_width=width,
                                image_height=height,
                                source_field_name=source_field,
                            )
                            accepted = [
                                {
                                    **item,
                                    "bbox_space": "analysis_image" if source_field == "analysis_image" else "question_image",
                                    "detector_source": f"{rescan_scope}_zero_asset_rescan_model+tile_fallback",
                                    "review_flags": normalize_review_flags(
                                        list(item.get("review_flags", []) or [])
                                        + [f"{rescan_scope}_zero_asset_rescan", "long_image_branch", "tile_fallback"]
                                    ),
                                }
                                for item in tile_boxes
                                if _looks_figure_like_bbox(item, image_width=width, image_height=height)
                                and not _looks_like_text_false_positive(original.copy(), item)
                            ]
                    if accepted:
                        refined_accepted = accepted
                        if api_key_value:
                            refined = _refine_public_boxes_with_model(
                                original.copy(),
                                accepted,
                                api_key=api_key_value,
                                model=model_name,
                            )
                            if refined:
                                refined_accepted = [
                                    {
                                        **item,
                                        "detector_source": f"{rescan_scope}_zero_asset_rescan_model+refine_model",
                                        "review_flags": normalize_review_flags(
                                            list(item.get("review_flags", []) or []) + [f"{rescan_scope}_zero_asset_rescan"]
                                        ),
                                    }
                                    for item in refined
                                ]
                            else:
                                refined_accepted = [
                                    {
                                        **item,
                                        "review_flags": normalize_review_flags(
                                            list(item.get("review_flags", []) or [])
                                            + [f"{rescan_scope}_zero_asset_rescan", "inline_figure_refine_all_rejected_keep_coarse"]
                                        ),
                                    }
                                    for item in accepted
                                ]
                        result[bucket_name] = _dedupe_overlapping_public_boxes(
                            list(result.get(bucket_name, []) or []) + refined_accepted,
                            iou_threshold=0.82,
                        )
                        result["detector"] = f"{rescan_scope}_zero_asset_rescan_model+refine_model"
                    result["global_review_flags"] = normalize_review_flags(
                        list(result.get("global_review_flags", []))
                        + list(payload.get("global_review_flags", []) or [])
                        + [f"{rescan_scope}_zero_asset_rescan_attempted"]
                    )
            except Exception:
                result["global_review_flags"] = normalize_review_flags(
                    list(result.get("global_review_flags", [])) + [f"{rescan_scope}_zero_asset_rescan_failed"]
                )
    return result
