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
            "stem_image_bboxes": [_normalize_bbox(item) for item in (detection.get("stem_image_bboxes", []) or []) if isinstance(item, dict)],
            "unassigned_image_bboxes": [_normalize_bbox(item) for item in (detection.get("unassigned_image_bboxes", []) or []) if isinstance(item, dict)],
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
    if normalized["confidence"] < IMAGE_ASSIGNMENT_CONFIDENCE_THRESHOLD and "option_anchor_low_confidence" not in normalized["review_flags"]:
        normalized["review_flags"] = normalize_review_flags(list(normalized["review_flags"]) + ["option_anchor_low_confidence"])
    return normalized


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


def _heuristic_public_figure_regions(image_path: Path) -> list[dict]:
    with Image.open(image_path) as img:
        gray = img.convert("L")
        width, height = gray.size
        scale = 4 if max(width, height) >= 1200 else 3 if max(width, height) >= 800 else 2
        small_w = max(width // scale, 1)
        small_h = max(height // scale, 1)
        small = gray.resize((small_w, small_h))
        pixels = small.load()
        dark = [[pixels[x, y] < 210 for x in range(small_w)] for y in range(small_h)]

    visited = [[False for _ in range(small_w)] for _ in range(small_h)]
    boxes: list[dict] = []
    neighbors = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    min_component = max(18, int((small_w * small_h) * 0.001))

    for sy in range(small_h):
        for sx in range(small_w):
            if visited[sy][sx] or not dark[sy][sx]:
                continue
            stack = [(sx, sy)]
            visited[sy][sx] = True
            count = 0
            min_x = max_x = sx
            min_y = max_y = sy
            while stack:
                x, y = stack.pop()
                count += 1
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                for dx, dy in neighbors:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < small_w and 0 <= ny < small_h and not visited[ny][nx] and dark[ny][nx]:
                        visited[ny][nx] = True
                        stack.append((nx, ny))
            if count < min_component:
                continue
            box = {
                "x": max(min_x * scale - 4, 0),
                "y": max(min_y * scale - 4, 0),
                "w": min((max_x - min_x + 1) * scale + 8, width),
                "h": min((max_y - min_y + 1) * scale + 8, height),
                "confidence": 0.56,
                "review_flags": ["option_anchor_low_confidence"],
            }
            boxes.append(box)

    merged = _merge_nearby_boxes(boxes, gap=max(10, scale * 4))
    result: list[dict] = []
    for box in merged:
        bw = int(box.get("w", 0) or 0)
        bh = int(box.get("h", 0) or 0)
        bx = int(box.get("x", 0) or 0)
        by = int(box.get("y", 0) or 0)
        if bw < max(40, width // 14) or bh < max(40, height // 14):
            continue
        if bw > int(width * 0.82) and bh < int(height * 0.14):
            continue
        if bx > int(width * 0.72) and bw < int(width * 0.15):
            continue
        if by < int(height * 0.08) and bh < int(height * 0.08):
            continue
        result.append(box)
    return result


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


def detect_public_figure_regions(
    question: dict,
    *,
    api_key: str = "",
    model: str = "",
) -> dict:
    api_key_value = str(api_key or os.environ.get("ARK_API_KEY", "") or "").strip()
    model_name = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    result = {
        "stem_image_bboxes": [],
        "analysis_image_bboxes": [],
        "global_review_flags": [],
    }
    if not api_key_value:
        return result

    for field_name, bucket_name in (("stem_image", "stem_image_bboxes"), ("analysis_image", "analysis_image_bboxes")):
        image_path_raw = str(question.get(field_name, "") or "").strip()
        if not image_path_raw:
            continue
        image_path = Path(image_path_raw)
        if not image_path.exists():
            continue
        hint_text = "\n".join(
            part
            for part in (
                str(question.get("stem_text", "") or ""),
                str(question.get("analysis_text", "") or "") if field_name == "analysis_image" else "",
                str(question.get("transcription_ocr", "") or ""),
            )
            if part.strip()
        )
        try:
            payload = _call_inline_figure_model(api_key_value, model_name, image_path, field_name, hint_text)
        except Exception:
            payload = {}
        boxes = [_normalize_public_image_bbox(item) for item in (payload.get("image_bboxes", []) or [])]
        normalized_boxes = _dedupe_public_boxes([item for item in boxes if item])
        if not normalized_boxes:
            normalized_boxes = _dedupe_public_boxes(_heuristic_public_figure_regions(image_path))
        result[bucket_name] = normalized_boxes
        result["global_review_flags"] = normalize_review_flags(
            list(result.get("global_review_flags", [])) + list(payload.get("global_review_flags", []) or [])
        )
    return result
