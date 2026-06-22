from __future__ import annotations

import json
import math
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image, ImageDraw, ImageFont


SCALE = float(os.environ.get("PDF_RENDER_SCALE", "1.6"))
QUESTION_KINDS = {"example", "practice", "advanced", "after_class"}
QUESTION_START = re.compile(r"^\s*(\d{1,2})\s*[．.、]\s*")


@dataclass
class Anchor:
    page: int
    kind: str
    label: str
    y: int
    x0: int
    y0: int
    x1: int
    y1: int
    source: str
    note: str = ""


@dataclass
class Segment:
    segment_id: str
    page: int
    kind: str
    label: str
    checkpoint: str
    x0: int
    y0: int
    x1: int
    y1: int
    crop_path: str = ""
    anchor_note: str = ""


@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


@dataclass
class ComponentGroup:
    group_id: str
    kind: str
    label: str
    checkpoint: str
    segments: list[Segment] = field(default_factory=list)


@dataclass
class QuestionSlice:
    question_id: str
    group_id: str
    checkpoint: str
    component_kind: str
    component_label: str
    local_number: int
    visual_pages: list[int]
    fragments: list[dict]
    text_preview: str
    crop_path: str = ""
    review_status: str = "VISUAL_REVIEWED_V02"
    review_note: str = ""
    text_preview_pdf: str = ""
    text_preview_ocr: str = ""
    text_preview_source: str = "pdf_text_layer"


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


OCR_ENGINE = None
OCR_UNAVAILABLE = False
SUMMARY_STOP_TOKENS = (
    "\u3010\u7b54\u6848",
    "\u7b54\u6848",
    "\u3010\u5206\u6790",
    "\u5206\u6790",
    "\u3010\u89e3\u7b54",
    "\u89e3\u7b54",
    "\u70b9\u8bc4",
)


def normalize_preview_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def looks_noisy_preview(text: str) -> bool:
    clean = normalize_preview_text(text)
    if not clean:
        return True
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", clean))
    latin_count = len(re.findall(r"[A-Za-z]", clean))
    digit_count = len(re.findall(r"\d", clean))
    math_symbol_count = len(re.findall(r"[=+\-*/^<>≤≥(){}\[\]|_]", clean))
    private_use_count = len(re.findall(r"[\uE000-\uF8FF]", clean))
    symbol_count = len(clean) - cjk_count - latin_count - digit_count
    noisy_hits = sum(clean.count(token) for token in ("\uFFFD",))
    sparse_readable = cjk_count <= 8 and len(clean) >= 24
    symbol_heavy = len(clean) >= 32 and symbol_count / max(len(clean), 1) > 0.24 and cjk_count < 20
    formula_noise = len(clean) >= 48 and math_symbol_count >= 7 and cjk_count < 48
    return noisy_hits >= 1 or private_use_count >= 1 or sparse_readable or symbol_heavy or formula_noise


def get_ocr_engine():
    global OCR_ENGINE, OCR_UNAVAILABLE
    if OCR_UNAVAILABLE:
        return None
    if OCR_ENGINE is not None:
        return OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR

        OCR_ENGINE = RapidOCR()
        return OCR_ENGINE
    except Exception:
        OCR_UNAVAILABLE = True
        return None


def trim_summary_tail(text: str) -> str:
    clean = normalize_preview_text(text)
    if not clean:
        return ""
    cut_index = len(clean)
    for token in SUMMARY_STOP_TOKENS:
        index = clean.find(token)
        if index > 0 and index < cut_index:
            cut_index = index
    clean = clean[:cut_index].strip()
    clean = re.sub(r"[\s,.;:，。；：、]+$", "", clean)
    return clean


def should_stop_ocr_summary(clean: str, text_count: int, y_ratio: float) -> bool:
    if not clean:
        return False
    if any(token in clean for token in SUMMARY_STOP_TOKENS):
        return text_count > 0
    if y_ratio > 0.72 and text_count > 0:
        return True
    return False


def trim_summary_head(text: str) -> str:
    clean = normalize_preview_text(text)
    if not clean:
        return ""
    match = re.search(r"\d+\s*[．.]", clean)
    if match and match.start() <= 80:
        clean = clean[match.start():]
    clean = re.sub(r"\b\d{1,3}\s*$", "", clean).strip()
    return clean


def render_pdf(pdf_path: str, pages_dir: Path) -> list[Path]:
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths: list[Path] = []
    for idx, page in enumerate(doc, start=1):
        out = pages_dir / f"page_{idx:03d}.png"
        pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False)
        pix.save(str(out))
        paths.append(out)
    return paths


def extract_lines(pdf_path: str) -> dict[int, list[Line]]:
    doc = fitz.open(pdf_path)
    by_page: dict[int, list[Line]] = {}
    for pi, page in enumerate(doc, start=1):
        lines: list[Line] = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for raw_line in block["lines"]:
                text = "".join(span["text"] for span in raw_line["spans"]).strip()
                text = re.sub(r"\s+", " ", text)
                if not text:
                    continue
                x0, y0, x1, y1 = raw_line["bbox"]
                lines.append(Line(pi, x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE, text))
        by_page[pi] = sorted(lines, key=lambda line: (line.y0, line.x0))
    return by_page


def blue_components(image: Image.Image) -> list[tuple[int, int, int, int, int]]:
    arr = np.asarray(image.convert("RGB"))
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    mask = (b > 145) & (r < 95) & (g < 160) & ((b - r) > 75)
    h, w = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    comps: list[tuple[int, int, int, int, int]] = []
    for yy in range(0, h, 2):
        xs = np.where(mask[yy] & ~visited[yy])[0]
        for sx in xs:
            if visited[yy, sx] or not mask[yy, sx]:
                continue
            stack = [(int(sx), yy)]
            visited[yy, sx] = True
            x0 = x1 = int(sx)
            y0 = y1 = yy
            count = 0
            while stack:
                x, y = stack.pop()
                count += 1
                x0 = min(x0, x)
                x1 = max(x1, x)
                y0 = min(y0, y)
                y1 = max(y1, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or nx >= w or ny < 0 or ny >= h:
                        continue
                    if visited[ny, nx] or not mask[ny, nx]:
                        continue
                    visited[ny, nx] = True
                    stack.append((nx, ny))
            bw, bh = x1 - x0 + 1, y1 - y0 + 1
            if count >= 200 and bw >= 45 and bh >= 14:
                comps.append((x0, y0, x1, y1, count))

    comps.sort(key=lambda c: (c[1], c[0]))
    merged: list[tuple[int, int, int, int, int]] = []
    for x0, y0, x1, y1, count in comps:
        placed = False
        for idx, old in enumerate(merged):
            ox0, oy0, ox1, oy1, oc = old
            same_band = abs(((y0 + y1) / 2) - ((oy0 + oy1) / 2)) < 45
            close_x = x0 <= ox1 + 250 and x1 >= ox0 - 80
            if same_band and close_x:
                merged[idx] = (min(ox0, x0), min(oy0, y0), max(ox1, x1), max(oy1, y1), oc + count)
                placed = True
                break
        if not placed:
            merged.append((x0, y0, x1, y1, count))
    return merged


def page_content_bounds(path: Path) -> tuple[int, int] | None:
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img)
    content = arr[125:, :, :]
    nonwhite = np.any(content < 238, axis=2)
    ys = np.where(nonwhite)[0]
    if len(ys) < 80:
        return None
    return max(80, int(ys.min()) + 115), min(img.height - 70, int(ys.max()) + 145)


def checkpoint_anchors(lines_by_page: dict[int, list[Line]]) -> list[Anchor]:
    anchors: list[Anchor] = []
    for page, lines in lines_by_page.items():
        for line in lines:
            if line.text.startswith("考点"):
                anchors.append(
                    Anchor(
                        page=page,
                        kind="checkpoint",
                        label=line.text,
                        y=max(0, int(line.y0) - 18),
                        x0=max(0, int(line.x0) - 10),
                        y0=max(0, int(line.y0) - 18),
                        x1=int(line.x1) + 10,
                        y1=int(line.y1) + 16,
                        source="text_aux_after_visual_review",
                        note="文字层只用于命名和辅助边界；最终需看页图确认。",
                    )
                )
    return anchors


def blue_anchors(page_paths: list[Path], checkpoint_pages: set[int]) -> list[Anchor]:
    raw: list[tuple[int, int, int, int, int, int]] = []
    for page, path in enumerate(page_paths, start=1):
        img = Image.open(path).convert("RGB")
        for x0, y0, x1, y1, count in blue_components(img):
            if y0 < 130 and x0 > 600:
                continue
            if y0 < 120:
                continue
            raw.append((page, x0, y0, x1, y1, count))

    anchors: list[Anchor] = []
    question_blue_positions = [row for row in raw if row[0] != 1]
    last_question_blue = max(question_blue_positions, default=None, key=lambda r: (r[0], r[2]))
    previous_question_kind = ""
    for page, x0, y0, x1, y1, _count in raw:
        if page == 1 and y0 < 260:
            kind, label = "course_goal", "课程目标"
        elif page == 1:
            kind, label = "knowledge", "知识梳理"
        elif last_question_blue and (page, y0) == (last_question_blue[0], last_question_blue[2]) and page not in checkpoint_pages:
            kind, label = "after_class", "课后落实"
        elif page in checkpoint_pages and y0 < 260:
            kind, label = "example", "例题讲解"
        elif previous_question_kind in {"", "practice"} and page in checkpoint_pages:
            kind, label = "example", "例题讲解"
        else:
            kind, label = "practice", "强化训练"

        if kind in QUESTION_KINDS:
            previous_question_kind = kind
        anchors.append(
            Anchor(
                page=page,
                kind=kind,
                label=label,
                y=y0,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                source="blue_component_visual_anchor",
                note="蓝色挂件视觉锚点。",
            )
        )
    return anchors


def detect_anchors(page_paths: list[Path], lines_by_page: dict[int, list[Line]]) -> list[Anchor]:
    checkpoints = checkpoint_anchors(lines_by_page)
    anchors = blue_anchors(page_paths, {a.page for a in checkpoints}) + checkpoints
    anchors.sort(key=lambda a: (a.page, a.y, a.x0))
    return anchors


def make_segments(page_paths: list[Path], anchors: list[Anchor]) -> list[Segment]:
    usable = [a for a in anchors if a.kind != "header_logo"]
    usable.sort(key=lambda a: (a.page, a.y, a.x0))
    page_sizes = {i + 1: Image.open(path).size for i, path in enumerate(page_paths)}
    content_bounds = {i + 1: page_content_bounds(path) for i, path in enumerate(page_paths)}
    segments: list[Segment] = []
    current_checkpoint = ""
    counter = 1
    for idx, anchor in enumerate(usable):
        if anchor.kind == "checkpoint":
            current_checkpoint = anchor.label
        next_anchor = usable[idx + 1] if idx + 1 < len(usable) else None
        end_page = next_anchor.page if next_anchor else len(page_paths)
        for page_idx in range(anchor.page, end_page + 1):
            bounds = content_bounds.get(page_idx)
            if bounds is None:
                continue
            w, h = page_sizes[page_idx]
            if page_idx == anchor.page:
                y0 = max(60, int(anchor.y0) - 18)
            else:
                y0 = bounds[0]
            if next_anchor and page_idx == next_anchor.page:
                y1 = min(h - 75, int(next_anchor.y) - 12)
            else:
                y1 = bounds[1]
            if y1 <= y0 + 60:
                continue
            label = anchor.label if page_idx == anchor.page else f"{anchor.label}（续）"
            segments.append(
                Segment(
                    segment_id=f"seg_{counter:03d}",
                    page=page_idx,
                    kind=anchor.kind,
                    label=label,
                    checkpoint=current_checkpoint,
                    x0=80,
                    y0=y0,
                    x1=w - 80,
                    y1=y1,
                    anchor_note=f"{anchor.source}; {anchor.note}",
                )
            )
            counter += 1
    return segments


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", value).strip("_")[:42] or "item"


def crop_segments(page_paths: list[Path], segments: list[Segment], crops_dir: Path) -> None:
    crops_dir.mkdir(parents=True, exist_ok=True)
    images = {i + 1: Image.open(path).convert("RGB") for i, path in enumerate(page_paths)}
    for seg in segments:
        crop = images[seg.page].crop((seg.x0, seg.y0, seg.x1, seg.y1))
        out = crops_dir / f"{seg.segment_id}_p{seg.page:03d}_{safe_name(seg.kind + '_' + seg.label)}.png"
        crop.save(out)
        seg.crop_path = str(out)


def annotate_pages(page_paths: list[Path], segments: list[Segment], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[Segment]] = {}
    for seg in segments:
        by_page.setdefault(seg.page, []).append(seg)
    colors = {
        "course_goal": (25, 118, 210),
        "knowledge": (0, 150, 136),
        "checkpoint": (85, 85, 85),
        "example": (57, 73, 171),
        "practice": (46, 125, 50),
        "advanced": (239, 124, 0),
        "after_class": (198, 40, 40),
    }
    font = load_font(22)
    out_paths: list[Path] = []
    for page, path in enumerate(page_paths, start=1):
        img = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        for seg in by_page.get(page, []):
            color = colors.get(seg.kind, (80, 80, 80))
            draw.rectangle([seg.x0, seg.y0, seg.x1, seg.y1], outline=(*color, 230), width=5)
            tag = f"{seg.segment_id} {seg.label}"
            draw.rectangle([seg.x0, max(0, seg.y0 - 34), min(seg.x0 + 330, seg.x1), seg.y0], fill=(*color, 220))
            draw.text((seg.x0 + 8, max(0, seg.y0 - 30)), tag, fill=(255, 255, 255), font=font)
        out = out_dir / f"annotated_p{page:03d}.png"
        img.save(out)
        out_paths.append(out)
    return out_paths


def contact_sheet(image_paths: list[Path], out_path: Path, thumb_size=(350, 495), cols=4) -> None:
    font = load_font(18)
    thumbs = []
    for p in image_paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail(thumb_size)
        canvas = Image.new("RGB", (thumb_size[0] + 30, thumb_size[1] + 55), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 8), p.stem, fill=(0, 0, 0), font=font)
        canvas.paste(im, ((canvas.width - im.width) // 2, 42))
        thumbs.append(canvas)
    if not thumbs:
        return
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * thumbs[0].width, rows * thumbs[0].height), (245, 245, 245))
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * thumb.width, (idx // cols) * thumb.height))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def base_label(label: str) -> str:
    return label.replace("（续）", "")


def build_groups(segments: list[Segment]) -> list[ComponentGroup]:
    groups: list[ComponentGroup] = []
    current: ComponentGroup | None = None
    counter = 1
    for seg in segments:
        if seg.kind not in QUESTION_KINDS:
            current = None
            continue
        is_continuation = "（续）" in seg.label
        normalized = base_label(seg.label)
        if not is_continuation or current is None or current.kind != seg.kind or current.label != normalized:
            current = ComponentGroup(
                group_id=f"cg_{counter:03d}",
                kind=seg.kind,
                label=normalized,
                checkpoint=seg.checkpoint,
                segments=[],
            )
            groups.append(current)
            counter += 1
        current.segments.append(seg)
    return groups


def line_overlaps(line: Line, seg: Segment) -> bool:
    return line.y1 >= seg.y0 and line.y0 <= seg.y1 and line.x1 >= seg.x0 and line.x0 <= seg.x1


def question_start_candidates(group: ComponentGroup, lines_by_page: dict[int, list[Line]]) -> list[dict]:
    starts: list[dict] = []
    for seg_idx, seg in enumerate(group.segments):
        for line in lines_by_page.get(seg.page, []):
            if not line_overlaps(line, seg):
                continue
            match = QUESTION_START.match(line.text)
            if not match:
                continue
            tail = line.text[match.end():].strip()
            # A denominator like "12．" or a formula fragment can sit in the
            # same left gutter as a real question number. Keep only starts that
            # visibly continue into a question stem. Some math PDFs split one
            # visual row into many text fragments, so look rightward on the same
            # row before rejecting a short tail such as "4．设".
            if len(tail) < 4:
                row_tail = "".join(
                    other.text
                    for other in lines_by_page.get(seg.page, [])
                    if abs(other.y0 - line.y0) < 9 and line.x1 <= other.x0 <= seg.x1
                )
                if len((tail + row_tail).strip()) < 4:
                    continue
            if line.x0 > seg.x0 + 125:
                continue
            if line.y0 < seg.y0 - 3 or line.y0 > seg.y1:
                continue
            starts.append(
                {
                    "page": seg.page,
                    "seg_idx": seg_idx,
                    "y": max(seg.y0, int(line.y0) - 12),
                    "number": int(match.group(1)),
                    "text": line.text,
                }
            )
    deduped: list[dict] = []
    for start in sorted(starts, key=lambda s: (s["seg_idx"], s["page"], s["y"])):
        if deduped and start["page"] == deduped[-1]["page"] and abs(start["y"] - deduped[-1]["y"]) < 12:
            continue
        deduped.append(start)
    return deduped


def preview_text(lines_by_page: dict[int, list[Line]], fragment: dict, limit: int = 220) -> str:
    texts = []
    x0, y0, x1, y1 = fragment["bbox_image"]
    for line in lines_by_page.get(fragment["page"], []):
        if line.y1 >= y0 and line.y0 <= y1 and line.x1 >= x0 and line.x0 <= x1:
            texts.append(line.text)
    return " ".join(texts).strip()[:limit]


def split_group(group: ComponentGroup, lines_by_page: dict[int, list[Line]], next_q: int) -> tuple[list[QuestionSlice], int]:
    starts = question_start_candidates(group, lines_by_page)
    if not starts:
        fragments = [
            {
                "page": seg.page,
                "bbox_image": [seg.x0, seg.y0, seg.x1, seg.y1],
                "parent_segment_id": seg.segment_id,
                "fragment_type": "component_without_question_anchor",
            }
            for seg in group.segments
        ]
        return [
            QuestionSlice(
                question_id=f"tq_{next_q:03d}",
                group_id=group.group_id,
                checkpoint=group.checkpoint,
                component_kind=group.kind,
                component_label=group.label,
                local_number=0,
                visual_pages=sorted({f["page"] for f in fragments}),
                fragments=fragments,
                text_preview=preview_text(lines_by_page, fragments[0]) if fragments else "",
                review_status="NEEDS_MANUAL_REVIEW",
                review_note="该组件没有清晰题号，保留整块给人工看。",
            )
        ], next_q + 1

    questions: list[QuestionSlice] = []
    for idx, start in enumerate(starts):
        next_start = starts[idx + 1] if idx + 1 < len(starts) else None
        start_seg_idx = start["seg_idx"]
        end_seg_idx = next_start["seg_idx"] if next_start else len(group.segments) - 1
        fragments = []
        for seg_idx in range(start_seg_idx, end_seg_idx + 1):
            seg = group.segments[seg_idx]
            fy0, fy1 = seg.y0, seg.y1
            if seg_idx == start_seg_idx:
                fy0 = max(seg.y0, int(start["y"]))
            if next_start and seg_idx == next_start["seg_idx"]:
                fy1 = min(seg.y1, max(fy0 + 55, int(next_start["y"]) - 10))
            if fy1 <= fy0 + 35:
                continue
            fragments.append(
                {
                    "page": seg.page,
                    "bbox_image": [seg.x0, fy0, seg.x1, fy1],
                    "parent_segment_id": seg.segment_id,
                    "fragment_type": "start" if seg_idx == start_seg_idx else "continuation",
                }
            )
        questions.append(
            QuestionSlice(
                question_id=f"tq_{next_q:03d}",
                group_id=group.group_id,
                checkpoint=group.checkpoint,
                component_kind=group.kind,
                component_label=group.label,
                local_number=start["number"],
                visual_pages=sorted({f["page"] for f in fragments}),
                fragments=fragments,
                text_preview=preview_text(lines_by_page, fragments[0]) if fragments else start["text"],
                review_status="VISUAL_REVIEWED_V02",
                review_note="题号位置负责起点；父组件视觉边界负责终点；红色答案解析和几何图随题保留。",
            )
        )
        next_q += 1
    return questions, next_q


def build_question_canvas(q: QuestionSlice, page_images: dict[int, Image.Image], with_labels: bool = True) -> Image.Image | None:
    font = load_font(20)
    parts: list[Image.Image] = []
    for frag in q.fragments:
        page_img = page_images[frag["page"]]
        x0, y0, x1, y1 = [int(v) for v in frag["bbox_image"]]
        crop = page_img.crop((x0, y0, x1, y1)).convert("RGB")
        if with_labels:
            label_h = 32
            labeled = Image.new("RGB", (crop.width, crop.height + label_h), "white")
            draw = ImageDraw.Draw(labeled)
            draw.rectangle([0, 0, crop.width, label_h], fill=(235, 242, 255))
            draw.text((8, 5), f"{q.question_id} p{frag['page']} {q.checkpoint} / {q.component_label} Q{q.local_number}", fill=(25, 65, 130), font=font)
            labeled.paste(crop, (0, label_h))
            parts.append(labeled)
        else:
            parts.append(crop)
    if not parts:
        return None
    width = max(p.width for p in parts)
    height = sum(p.height for p in parts) + (len(parts) - 1) * 12
    canvas = Image.new("RGB", (width, height), "white")
    y = 0
    for part in parts:
        canvas.paste(part, ((width - part.width) // 2, y))
        y += part.height + 12
    return canvas


def stitch_question(q: QuestionSlice, page_images: dict[int, Image.Image], out_path: Path) -> None:
    canvas = build_question_canvas(q, page_images, with_labels=True)
    if canvas is None:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    q.crop_path = str(out_path)


def ocr_preview_text(q: QuestionSlice, page_images: dict[int, Image.Image], limit: int = 220) -> str:
    engine = get_ocr_engine()
    if engine is None:
        return ""
    canvas = build_question_canvas(q, page_images, with_labels=False)
    if canvas is None:
        return ""
    try:
        result, _ = engine(canvas)
    except Exception:
        return ""
    if not result:
        return ""
    ordered = sorted(result, key=lambda item: ((item[0][0][1] + item[0][2][1]) / 2, (item[0][0][0] + item[0][1][0]) / 2))
    texts: list[str] = []
    canvas_height = max(canvas.height, 1)
    for item in ordered:
        if len(item) < 3:
            continue
        box, text, score = item
        if score < 0.55:
            continue
        clean = normalize_preview_text(text)
        if not clean:
            continue
        if clean.lower().startswith("tq_"):
            continue
        center_y = (box[0][1] + box[2][1]) / 2
        if should_stop_ocr_summary(clean, len(texts), center_y / canvas_height):
            break
        texts.append(clean)
    summary = trim_summary_head(trim_summary_tail(" ".join(texts)))
    return summary[:limit]


def question_contact_sheet(questions: list[QuestionSlice], out_path: Path) -> None:
    font = load_font(18)
    thumbs = []
    for q in questions:
        img = Image.open(q.crop_path).convert("RGB")
        img.thumbnail((360, 260))
        canvas = Image.new("RGB", (400, 335), "white")
        draw = ImageDraw.Draw(canvas)
        title = f"{q.question_id} {q.checkpoint or q.component_label} / {q.component_label}"
        draw.text((8, 8), title[:36], fill=(0, 0, 0), font=font)
        draw.text((8, 34), f"Q{q.local_number} {q.review_status}", fill=(80, 80, 80), font=font)
        canvas.paste(img, ((400 - img.width) // 2, 66))
        thumbs.append(canvas)
    if not thumbs:
        return
    cols = 3
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * 400, rows * 335), (245, 245, 245))
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 400, (idx // cols) * 335))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def write_outputs(pdf_path: str, anchors: list[Anchor], segments: list[Segment], questions: list[QuestionSlice], out_dir: Path) -> None:
    data = {
        "source_pdf": pdf_path,
        "principle": "visual-first: blue component anchors and rendered page layout define components; question numbers only assist starts inside those visual components",
        "anchor_count": len(anchors),
        "segment_count": len(segments),
        "question_count": len(questions),
        "anchors": [a.__dict__ for a in anchors],
        "segments": [s.__dict__ for s in segments],
        "questions": [q.__dict__ for q in questions],
    }
    (out_dir / "teacher_visual_question_split_v0.2.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    wb = Workbook()
    ws = wb.active
    ws.title = "题目切片"
    headers = ["题目ID", "考点", "父组件", "组件类型", "题号", "页码", "状态", "题干预览", "切片路径"]
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for q in questions:
        ws.append([q.question_id, q.checkpoint, q.component_label, q.component_kind, q.local_number, ",".join(map(str, q.visual_pages)), q.review_status, q.text_preview, q.crop_path])
    for idx, width in enumerate([12, 30, 14, 14, 8, 10, 22, 78, 90], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    wb.save(out_dir / "teacher_visual_question_split_v0.2.xlsx")

    counts: dict[str, int] = {}
    for q in questions:
        key = f"{q.checkpoint or '未挂考点'} / {q.component_label}"
        counts[key] = counts.get(key, 0) + 1

    md = ["# 教师版 PDF 视觉切题 v0.2\n\n"]
    md.append(f"源文件：`{pdf_path}`\n\n")
    md.append("## 结果概览\n\n")
    md.append(f"- 视觉锚点：{len(anchors)}\n")
    md.append(f"- 组件片段：{len(segments)}\n")
    md.append(f"- 题目切片：{len(questions)}\n\n")
    md.append("## 挂件统计\n\n")
    md.append("| 考点 / 组件 | 题目数 |\n|---|---:|\n")
    for key, value in counts.items():
        md.append(f"| {key} | {value} |\n")
    md.append("\n## 自检口径\n\n")
    md.append("- 蓝色大挂件负责一级组件边界，考点标题负责把后续例题/训练挂到哪个知识点。\n")
    md.append("- 单题起点看左侧题号；终点看下一题题号或父组件结束，所以红色答案解析、几何图、跨页续题不会被主动丢弃。\n")
    md.append("- 若没有清晰题号，会保留整块并标为 NEEDS_MANUAL_REVIEW，不做静默删除。\n")
    (out_dir / "teacher_visual_question_split_v0.2.md").write_text("".join(md), encoding="utf-8")


def zip_outputs(out_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in out_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(out_dir.parent))


def main() -> None:
    pdf_path = os.environ["PDF_TEACHER"]
    out_name = os.environ.get("SPLIT_OUT_NAME", "teacher_visual_question_split_v02")
    out_dir = Path.cwd() / "outputs" / "ingress_splitter_v0.1" / out_name
    pages_dir = out_dir / "pages"
    segment_dir = out_dir / "component_crops"
    question_dir = out_dir / "question_crops"
    annotated_dir = out_dir / "annotated_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    page_paths = render_pdf(pdf_path, pages_dir)
    lines_by_page = extract_lines(pdf_path)
    anchors = detect_anchors(page_paths, lines_by_page)
    segments = make_segments(page_paths, anchors)
    crop_segments(page_paths, segments, segment_dir)
    annotated_paths = annotate_pages(page_paths, segments, annotated_dir)
    contact_sheet(annotated_paths, out_dir / "component_annotated_contact_sheet.jpg")

    groups = build_groups(segments)
    questions: list[QuestionSlice] = []
    counter = 1
    for group in groups:
        group_questions, counter = split_group(group, lines_by_page, counter)
        questions.extend(group_questions)

    page_images = {i + 1: Image.open(path).convert("RGB") for i, path in enumerate(page_paths)}
    for q in questions:
        q.text_preview_pdf = q.text_preview
        out = question_dir / f"{q.question_id}_{safe_name(q.checkpoint)}_{safe_name(q.component_label)}_Q{q.local_number}.png"
        stitch_question(q, page_images, out)
        if looks_noisy_preview(q.text_preview):
            ocr_preview = ocr_preview_text(q, page_images)
            q.text_preview_ocr = ocr_preview
            if ocr_preview:
                q.text_preview = ocr_preview
                q.text_preview_source = "ocr_fallback"
            else:
                q.text_preview_source = "pdf_text_layer_noisy"
    question_contact_sheet(questions, out_dir / "question_crops_contact_sheet.jpg")
    write_outputs(pdf_path, anchors, segments, questions, out_dir)
    zip_path = out_dir.parent / f"{out_name}_package.zip"
    zip_outputs(out_dir, zip_path)
    print(json.dumps({
        "out_dir": str(out_dir),
        "zip": str(zip_path),
        "anchors": len(anchors),
        "segments": len(segments),
        "questions": len(questions),
        "component_contact_sheet": str(out_dir / "component_annotated_contact_sheet.jpg"),
        "question_contact_sheet": str(out_dir / "question_crops_contact_sheet.jpg"),
        "xlsx": str(out_dir / "teacher_visual_question_split_v0.2.xlsx"),
        "report": str(out_dir / "teacher_visual_question_split_v0.2.md"),
        "json": str(out_dir / "teacher_visual_question_split_v0.2.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
