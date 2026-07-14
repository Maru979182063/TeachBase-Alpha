from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
VENDOR_DIR = THIS_DIR / "vendor"
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import fitz
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR


@dataclass
class OcrLine:
    line_id: str
    page: int
    order: int
    text: str
    confidence: float
    bbox_px: list[int]
    bbox_norm: list[float]


@dataclass
class VisualObject:
    object_id: str
    page: int
    object_type: str
    bbox_px: list[int]
    bbox_norm: list[float]
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    crop_path: str = ""


def norm_bbox(box: list[int], width: int, height: int) -> list[float]:
    return [
        round(box[0] / max(width, 1), 6),
        round(box[1] / max(height, 1), 6),
        round(box[2] / max(width, 1), 6),
        round(box[3] / max(height, 1), 6),
    ]


def union_box(boxes: list[list[int]]) -> list[int]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def overlap_ratio(a: list[int], b: list[int]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    smaller = min(max(1, (a[2] - a[0]) * (a[3] - a[1])), max(1, (b[2] - b[0]) * (b[3] - b[1])))
    return inter / smaller


def render_pages(pdf_path: Path, pages: list[int], out_dir: Path, dpi: int) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    doc = fitz.open(str(pdf_path))
    rendered: dict[int, Path] = {}
    for page_no in pages:
        if page_no < 1 or page_no > doc.page_count:
            continue
        pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        path = out_dir / f"p{page_no:03d}.png"
        pix.save(str(path))
        rendered[page_no] = path
    return rendered


def run_ocr(page_images: dict[int, Path]) -> tuple[list[OcrLine], dict[str, Any]]:
    engine_start = time.time()
    engine = RapidOCR()
    meta = {"engine": "tools/vendor rapidocr_onnxruntime", "init_seconds": round(time.time() - engine_start, 3), "pages": []}
    lines: list[OcrLine] = []
    for page_no, image_path in page_images.items():
        image = Image.open(image_path).convert("RGB")
        started = time.time()
        result, _ = engine(str(image_path))
        page_lines: list[OcrLine] = []
        for raw in result or []:
            if len(raw) < 3:
                continue
            box, text, score = raw
            clean = re.sub(r"\s+", " ", str(text or "")).strip()
            if not clean:
                continue
            xs = [float(pt[0]) for pt in box]
            ys = [float(pt[1]) for pt in box]
            bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
            page_lines.append(
                OcrLine(
                    line_id="",
                    page=page_no,
                    order=0,
                    text=clean,
                    confidence=round(float(score or 0), 4),
                    bbox_px=bbox,
                    bbox_norm=norm_bbox(bbox, image.width, image.height),
                )
            )
        page_lines.sort(key=lambda item: (item.bbox_px[1], item.bbox_px[0]))
        for index, line in enumerate(page_lines, start=1):
            line.order = index
            line.line_id = f"p{page_no:03d}_l{index:03d}"
        lines.extend(page_lines)
        meta["pages"].append({"page": page_no, "line_count": len(page_lines), "ocr_seconds": round(time.time() - started, 3)})
    return lines, meta


def classify_line(text: str) -> str:
    stripped = str(text or "").strip()
    lowered = stripped.lower()
    ascii_words = len(re.findall(r"[A-Za-z]{3,}", stripped))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    if not stripped:
        return "empty"
    if any(key in stripped for key in ["课程目标", "知识梳理", "知识导入", "例题讲解", "强化训练"]):
        return "heading"
    if any(key in stripped for key in ["答案", "[answer]", "answer:"]):
        return "answer"
    if any(key in stripped for key in ["解析", "翻译", "analysis", "translation"]):
        return "analysis"
    if re.match(r"^\s*\d{1,2}[\.)、]?\s+", stripped) or ("?" in stripped and len(stripped) < 140):
        return "question"
    if re.match(r"^\s*[A-D][\.)、]\s*", stripped):
        return "option"
    if ascii_words >= 7 and chinese_chars <= max(2, ascii_words // 4):
        return "passage"
    if re.search(r"/[A-Za-z0-9' :.\-]+/", stripped) or lowered in {"subconscious", "activation", "worsened", "direction", "method"}:
        return "vocabulary"
    return "body"


def detect_visual_objects(page_images: dict[int, Path], out_dir: Path) -> list[VisualObject]:
    objects: list[VisualObject] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import cv2
        import numpy as np
    except Exception:
        return objects
    for page_no, image_path in page_images.items():
        raw = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        height, width = img.shape[:2]
        inv = cv2.threshold(img, 190, 255, cv2.THRESH_BINARY_INV)[1]
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 28), 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, height // 55)))
        horizontal = cv2.morphologyEx(inv, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
        vertical = cv2.morphologyEx(inv, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
        grid = cv2.add(horizontal, vertical)
        contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[list[int]] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area_ratio = (w * h) / max(width * height, 1)
            if area_ratio < 0.012 or w < width * 0.22 or h < height * 0.035:
                continue
            if y < height * 0.04 or y + h > height * 0.985:
                continue
            candidates.append([x, y, x + w, y + h])
        candidates.sort(key=lambda box: (box[1], box[0]))
        kept: list[list[int]] = []
        for box in candidates:
            if any(overlap_ratio(box, other) > 0.65 for other in kept):
                continue
            kept.append(box)
        src = Image.open(image_path).convert("RGB")
        for idx, box in enumerate(kept, start=1):
            object_id = f"p{page_no:03d}_vo{idx:03d}"
            crop = src.crop(tuple(box))
            crop_path = out_dir / f"{object_id}.png"
            crop.save(crop_path)
            objects.append(
                VisualObject(
                    object_id=object_id,
                    page=page_no,
                    object_type="table_or_frame_candidate",
                    bbox_px=box,
                    bbox_norm=norm_bbox(box, width, height),
                    confidence=0.62,
                    evidence={"detector": "cv_horizontal_vertical_line_probe"},
                    crop_path=str(crop_path),
                )
            )
    return objects


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_page_text(path: Path, lines: list[OcrLine]) -> None:
    by_page: dict[int, list[OcrLine]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    chunks = []
    for page in sorted(by_page):
        chunks.append(f"## Page {page}\n")
        chunks.extend(line.text for line in by_page[page])
        chunks.append("")
    path.write_text("\n".join(chunks), encoding="utf-8")


def draw_ocr_overlays(page_images: dict[int, Path], lines: list[OcrLine], visual_objects: list[VisualObject], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    for page_no, image_path in page_images.items():
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for obj in [item for item in visual_objects if item.page == page_no]:
            draw.rectangle(tuple(obj.bbox_px), outline=(230, 145, 0), width=5)
            draw.text((obj.bbox_px[0], max(0, obj.bbox_px[1] - 22)), obj.object_id, fill=(230, 145, 0), font=font)
        for line in [item for item in lines if item.page == page_no]:
            color = (30, 120, 220)
            role = classify_line(line.text)
            if role == "passage":
                color = (35, 150, 80)
            elif role in {"answer", "analysis"}:
                color = (210, 50, 80)
            elif role == "question":
                color = (120, 70, 210)
            draw.rectangle(tuple(line.bbox_px), outline=color, width=2)
        img.thumbnail((1300, 1800))
        img.save(out_dir / f"p{page_no:03d}_ocr_overlay.jpg", quality=90)


def parse_pages(raw: str) -> list[int]:
    pages: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))
