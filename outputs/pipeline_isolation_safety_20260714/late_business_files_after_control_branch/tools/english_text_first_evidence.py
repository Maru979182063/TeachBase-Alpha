from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "tools" / "vendor"
if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))


@dataclass
class OcrLine:
    line_id: str
    page: int
    text: str
    score: float | None
    bbox_px: list[int]


@dataclass
class VisualObject:
    object_id: str
    page: int
    kind: str
    bbox_px: list[int]
    crop_path: str
    evidence: dict[str, Any]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    seen: set[int] = set()
    ordered: list[int] = []
    for page in pages:
        if page > 0 and page not in seen:
            ordered.append(page)
            seen.add(page)
    return ordered


def extract_text_layer(pdf_path: Path, pages: list[int]) -> dict[str, Any]:
    import fitz

    doc = fitz.open(pdf_path)
    page_rows: list[dict[str, Any]] = []
    total_chars = 0
    for page_no in pages:
        if page_no < 1 or page_no > doc.page_count:
            continue
        text = doc.load_page(page_no - 1).get_text("text") or ""
        char_count = len(text.strip())
        total_chars += char_count
        page_rows.append({"page": page_no, "char_count": char_count, "sample": text[:500]})
    doc.close()
    return {
        "pdf": str(pdf_path),
        "pages": page_rows,
        "total_chars": total_chars,
        "usable": total_chars >= 200,
    }


def render_pages(pdf_path: Path, pages: list[int], out_dir: Path, dpi: int = 180) -> list[dict[str, Any]]:
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    rendered: list[dict[str, Any]] = []
    for page_no in pages:
        if page_no < 1 or page_no > doc.page_count:
            continue
        page = doc.load_page(page_no - 1)
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        image_path = out_dir / f"page_{page_no:03d}.png"
        pix.save(image_path)
        rendered.append(
            {
                "page": page_no,
                "image_path": str(image_path),
                "width_px": pix.width,
                "height_px": pix.height,
                "dpi": dpi,
            }
        )
    doc.close()
    return rendered


def _box_to_bbox(box: Any) -> list[int]:
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def run_ocr(rendered_pages: list[dict[str, Any]]) -> tuple[list[OcrLine], dict[str, Any]]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    lines: list[OcrLine] = []
    meta_pages: list[dict[str, Any]] = []
    for page in rendered_pages:
        result, elapsed = engine(page["image_path"])
        page_lines = 0
        for item in result or []:
            if len(item) < 2:
                continue
            bbox = _box_to_bbox(item[0])
            text = str(item[1]).strip()
            if not text:
                continue
            score = float(item[2]) if len(item) > 2 and item[2] is not None else None
            page_lines += 1
            lines.append(
                OcrLine(
                    line_id=f"p{int(page['page']):03d}_l{page_lines:03d}",
                    page=int(page["page"]),
                    text=text,
                    score=score,
                    bbox_px=bbox,
                )
            )
        meta_pages.append(
            {
                "page": page["page"],
                "line_count": page_lines,
                "elapsed": elapsed,
                "image_path": page["image_path"],
            }
        )
    return lines, {"provider": "rapidocr_onnxruntime_vendor", "pages": meta_pages}


def write_page_text(path: Path, lines: list[OcrLine]) -> None:
    by_page: dict[int, list[OcrLine]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    chunks: list[str] = []
    for page_no in sorted(by_page):
        chunks.append(f"## Page {page_no}")
        for line in by_page[page_no]:
            chunks.append(f"{line.line_id} {line.text}")
        chunks.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(chunks), encoding="utf-8")


def _overlap_ratio(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area = max(1, (ax2 - ax1) * (ay2 - ay1))
    return inter / area


def detect_visual_objects(
    rendered_pages: list[dict[str, Any]],
    ocr_lines: list[OcrLine],
    out_dir: Path,
) -> list[VisualObject]:
    import cv2
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    objects: list[VisualObject] = []
    next_id = 1
    lines_by_page: dict[int, list[OcrLine]] = {}
    for line in ocr_lines:
        lines_by_page.setdefault(line.page, []).append(line)

    for page in rendered_pages:
        page_no = int(page["page"])
        image = cv2.imread(page["image_path"])
        if image is None:
            continue
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (24, 18))
        merged = cv2.dilate(mask, kernel, iterations=1)
        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < 20000 or area > width * height * 0.75:
                continue
            if w < 90 or h < 45:
                continue
            bbox = [x, y, x + w, y + h]
            overlapping_lines = [
                line for line in lines_by_page.get(page_no, []) if _overlap_ratio(bbox, line.bbox_px) > 0.25
            ]
            # Dense OCR regions are text blocks, not non-text assets.
            if len(overlapping_lines) >= 8 and h < height * 0.45:
                continue
            candidates.append((x, y, w, h))
        candidates = sorted(candidates, key=lambda item: (item[1], item[0]))
        for x, y, w, h in candidates[:12]:
            bbox = [x, y, x + w, y + h]
            crop = image[max(0, y - 4) : min(height, y + h + 4), max(0, x - 4) : min(width, x + w + 4)]
            crop_path = out_dir / f"visual_{next_id:03d}_p{page_no:03d}.png"
            cv2.imwrite(str(crop_path), crop)
            aspect = w / max(1, h)
            kind = "table_or_diagram" if aspect > 1.8 or h > 180 else "non_text_visual"
            objects.append(
                VisualObject(
                    object_id=f"v{next_id:03d}",
                    page=page_no,
                    kind=kind,
                    bbox_px=bbox,
                    crop_path=str(crop_path),
                    evidence={"area_px": int(w * h), "aspect_ratio": round(aspect, 3)},
                )
            )
            next_id += 1
    return objects


def draw_ocr_overlays(rendered_pages: list[dict[str, Any]], lines: list[OcrLine], out_dir: Path) -> None:
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    lines_by_page: dict[int, list[OcrLine]] = {}
    for line in lines:
        lines_by_page.setdefault(line.page, []).append(line)
    for page in rendered_pages:
        page_no = int(page["page"])
        image = Image.open(page["image_path"]).convert("RGB")
        draw = ImageDraw.Draw(image)
        for line in lines_by_page.get(page_no, []):
            draw.rectangle(line.bbox_px, outline=(220, 40, 40), width=2)
            draw.text((line.bbox_px[0], max(0, line.bbox_px[1] - 14)), line.line_id, fill=(220, 40, 40))
        image.save(out_dir / f"page_{page_no:03d}_ocr_overlay.png")


def line_dicts(lines: list[OcrLine]) -> list[dict[str, Any]]:
    return [asdict(line) for line in lines]


def visual_dicts(objects: list[VisualObject]) -> list[dict[str, Any]]:
    return [asdict(obj) for obj in objects]
