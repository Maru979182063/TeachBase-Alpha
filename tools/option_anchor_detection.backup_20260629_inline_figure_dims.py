from __future__ import annotations

import base64
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


def _normalize_option_block(block: dict, bbox_space: str, image_width: int, image_height: int) -> dict:
    review_flags = normalize_review_flags(block.get("review_flags", []) or [])
    confidence = float(block.get("confidence", 0.0) or 0.0)
    if confidence < OPTION_ATTACH_CONFIDENCE_THRESHOLD and "option_anchor_low_confidence" not in review_flags:
        review_flags.append("option_anchor_low_confidence")
    return {
        "option_key": str(block.get("option_key", "") or "").upper(),
        "option_order": int(block.get("option_order", 0) or 0),
        "label_bbox": _normalize_bbox(block.get("label_bbox")),
        "option_bbox": _normalize_bbox(block.get("option_bbox")),
        "text_bbox": _normalize_bbox(block.get("text_bbox")),
        "image_bboxes": [_normalize_bbox(item) for item in (block.get("image_bboxes", []) or []) if isinstance(item, dict)],
        "bbox_space": bbox_space,
        "image_width": image_width,
        "image_height": image_height,
        "layout_type": str(block.get("layout_type", "") or "unknown"),
        "confidence": round(confidence, 4),
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
        detection = {
            "option_visual_blocks": [
                _normalize_option_block(block, bbox_space, width, height)
                for block in raw_blocks
                if isinstance(block, dict) and str(block.get("option_key", "") or "").upper() in OPTION_KEYS
            ],
            # Keep option detection focused on option-scoped layout only.
            "stem_image_bboxes": [],
            "unassigned_image_bboxes": [],
            "global_review_flags": normalize_review_flags(detection.get("global_review_flags", []) or []),
            "detector": "vision_model",
        }
        if not detection["option_visual_blocks"]:
            detection["global_review_flags"] = normalize_review_flags(
                list(detection.get("global_review_flags", [])) + ["option_anchor_missing"]
            )
    return detection


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
) -> list[dict]:
    if model_image_width <= 0 or model_image_height <= 0:
        return items
    if model_image_width == image_width and model_image_height == image_height:
        return items
    scale_x = image_width / max(model_image_width, 1)
    scale_y = image_height / max(model_image_height, 1)
    scaled: list[dict] = []
    for item in items:
        x = int(round(int(item.get("x", 0) or 0) * scale_x))
        y = int(round(int(item.get("y", 0) or 0) * scale_y))
        w = int(round(int(item.get("w", 0) or 0) * scale_x))
        h = int(round(int(item.get("h", 0) or 0) * scale_y))
        flags = normalize_review_flags(
            list(item.get("review_flags", []) or []) + ["model_canvas_scaled"]
        )
        scaled.append(
            {
                **item,
                "x": max(x, 0),
                "y": max(y, 0),
                "w": max(w, 1),
                "h": max(h, 1),
                "review_flags": flags,
                "model_image_width": model_image_width,
                "model_image_height": model_image_height,
            }
        )
    return scaled


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
        return False
    aspect = width / max(height, 1)
    if aspect > PUBLIC_FIGURE_MAX_ASPECT or aspect < 0.22:
        return False
    if width > int(image_width * 0.92) and height < int(image_height * 0.14):
        return False
    return True


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
            part = _tighten_candidate_bbox(image, part)
            part = _trim_leading_body_text(image, part)
            part = _trim_isolated_top_caption(image, part)
            part = _try_extend_caption(image, part)
            part = _pad_public_figure_bbox(image, part)
            part = _trim_trailing_body_text(image, part)
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
            if not _looks_figure_like_bbox(part, image_width=image_width, image_height=image_height):
                continue
            result.append(part)
    result = _dedupe_public_boxes(result)
    result = _complete_sparse_grid_boxes(image, result)
    return _dedupe_public_boxes(result)


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

    image_targets: list[tuple[str, str]] = []
    stem_image_raw = str(question.get("stem_image", "") or "").strip()
    question_image_raw = str(question.get("question_image", "") or "").strip()
    if stem_image_raw:
        image_targets.append(("stem_image", "stem_image_bboxes"))
    elif question_image_raw:
        # Legacy or packaged samples may only preserve the whole question crop.
        # In that case, still attempt public-figure extraction from question_image.
        image_targets.append(("question_image", "stem_image_bboxes"))
    if str(question.get("analysis_image", "") or "").strip():
        image_targets.append(("analysis_image", "analysis_image_bboxes"))

    for field_name, bucket_name in image_targets:
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
        boxes = [_normalize_public_image_bbox(item) for item in (payload.get("image_bboxes", []) or [])]
        boxes = _scale_model_canvas_boxes(
            [item for item in boxes if item],
            model_image_width=int(payload.get("image_width", 0) or 0),
            model_image_height=int(payload.get("image_height", 0) or 0),
            image_width=width,
            image_height=height,
        )
        detector_source = "vision_model"
        with Image.open(image_path) as original:
            normalized_boxes = _sanitize_public_boxes(
                boxes,
                image=original.copy(),
                image_width=width,
                image_height=height,
                source_field_name=field_name,
            )
        if not normalized_boxes and allow_heuristic_fallback:
            normalized_boxes = _dedupe_public_boxes(_heuristic_public_figure_regions(image_path, source_field_name=field_name))
            detector_source = "heuristic_fallback"
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
        for item in normalized_boxes:
            item["bbox_space"] = field_name
            item["detector_source"] = str(item.get("detector_source", "") or detector_source)
        result[bucket_name] = normalized_boxes
        result["detector"] = detector_source
        result["global_review_flags"] = normalize_review_flags(
            list(result.get("global_review_flags", [])) + list(payload.get("global_review_flags", []) or [])
        )
    return result
