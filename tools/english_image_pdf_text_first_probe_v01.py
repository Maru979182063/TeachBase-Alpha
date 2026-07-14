from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
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


@dataclass
class TextUnit:
    unit_id: str
    unit_type: str
    page_start: int
    page_end: int
    text: str
    ocr_line_refs: list[str]
    bbox_px_by_page: dict[str, list[int]]
    confidence: float
    flags: list[str] = field(default_factory=list)
    visual_object_refs: list[str] = field(default_factory=list)


@dataclass
class SemanticNodeProbe:
    node_id: str
    node_type: str
    title: str
    page_start: int
    page_end: int
    text: str
    child_unit_ids: list[str]
    shared_context_id: str = ""
    answer_text: str = ""
    analysis_text: str = ""
    visual_object_refs: list[str] = field(default_factory=list)
    review_status: str = "NEEDS_REVIEW"
    review_reasons: list[str] = field(default_factory=list)


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
    if any(key in stripped for key in ["【答案】", "[答案]", "答案：", "答案"]):
        return "answer"
    if any(key in stripped for key in ["【解析】", "【找】", "【圈】", "解析", "翻译"]):
        return "analysis"
    if re.match(r"^\s*\d{1,2}[.)．]\s*", stripped) or "?" in stripped and len(stripped) < 140:
        return "question"
    if re.match(r"^\s*[A-D][.)．]\s*", stripped):
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
            if any(_overlap_ratio(box, other) > 0.65 for other in kept):
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


def _line_text(line: OcrLine) -> str:
    return str(line.text or "").strip()


def _find_line_index(lines: list[OcrLine], start: int, predicate) -> int:
    for idx in range(max(0, start), len(lines)):
        if predicate(_line_text(lines[idx])):
            return idx
    return -1


def _node_from_line_range(
    *,
    node_id: str,
    node_type: str,
    title: str,
    lines: list[OcrLine],
    start: int,
    end: int,
    shared_context_id: str = "",
    review_status: str = "NEEDS_REVIEW",
    review_reasons: list[str] | None = None,
) -> dict[str, Any] | None:
    if start < 0 or end <= start or start >= len(lines):
        return None
    selected = lines[start : min(end, len(lines))]
    if not selected:
        return None
    return {
        "node_id": node_id,
        "node_type": node_type,
        "title": title,
        "page_start": min(line.page for line in selected),
        "page_end": max(line.page for line in selected),
        "text": "\n".join(_line_text(line) for line in selected),
        "ocr_line_refs": [line.line_id for line in selected],
        "bbox_px_by_page": _bbox_by_page(selected),
        "shared_context_id": shared_context_id,
        "review_status": review_status,
        "review_reasons": list(review_reasons or []),
    }


def _bbox_by_page(lines: list[OcrLine]) -> dict[str, list[int]]:
    boxes: dict[str, list[list[int]]] = {}
    for line in lines:
        boxes.setdefault(str(line.page), []).append(line.bbox_px)
    return {page: union_box(page_boxes) for page, page_boxes in boxes.items()}


def fit_reading_six_page_structure(lines: list[OcrLine]) -> dict[str, Any]:
    """A deliberately narrow probe for reading pages 1-6.

    This is not the production assembler. It checks whether OCR text can recover
    the coarse business structure from a real English reading handout.
    """
    ordered = sorted(lines, key=lambda line: (line.page, line.order))
    if not ordered:
        return {"schema": "english_reading_structure_fit_probe_v0.1", "nodes": [], "question_packets": [], "warnings": ["no_ocr_lines"]}

    example_idx = _find_line_index(
        ordered,
        0,
        lambda text: "In economic theories" in text or "economic theories" in text or "【例1" in text or "銆愪緥1" in text,
    )
    q2_idx = _find_line_index(ordered, max(example_idx, 0), lambda text: bool(re.match(r"^\s*2[.)．]\s*", text)) and "Paragraph 2" in text)
    q4_idx = _find_line_index(ordered, max(q2_idx, 0), lambda text: bool(re.match(r"^\s*4[.)．]\s*", text)) and "best title" in text)
    practice_idx = _find_line_index(
        ordered,
        max(q4_idx, 0),
        lambda text: "Maybe you've dreamed" in text or "Maybe you" in text or "强化训练" in text or "寮哄寲璁" in text,
    )

    warnings: list[str] = []
    for label, idx in {"example_start": example_idx, "q2": q2_idx, "q4": q4_idx, "practice_start": practice_idx}.items():
        if idx < 0:
            warnings.append(f"anchor_missing:{label}")

    nodes: list[dict[str, Any]] = []
    intro_end = example_idx if example_idx >= 0 else len(ordered)
    intro = _node_from_line_range(
        node_id="knowledge_intro_and_method_001",
        node_type="knowledge_block",
        title="reading main-idea method intro",
        lines=ordered,
        start=0,
        end=intro_end,
        review_reasons=["probe_coarse_node_not_auto_ingested"],
    )
    if intro:
        nodes.append(intro)

    passage_end = q2_idx if q2_idx >= 0 else (q4_idx if q4_idx >= 0 else len(ordered))
    passage = _node_from_line_range(
        node_id="passage_001",
        node_type="shared_context",
        title="example reading passage: economic stability model",
        lines=ordered,
        start=example_idx,
        end=passage_end,
        review_reasons=["shared_context_requires_question_group_validation"],
    )
    if passage:
        nodes.append(passage)

    q2_end = q4_idx if q4_idx >= 0 else (practice_idx if practice_idx >= 0 else len(ordered))
    q2 = _node_from_line_range(
        node_id="question_002_paragraph_main_idea",
        node_type="question",
        title="What is Paragraph 2 mainly about?",
        lines=ordered,
        start=q2_idx,
        end=q2_end,
        shared_context_id="passage_001",
        review_status="PROBE_READY" if q2_idx >= 0 and q4_idx >= 0 else "NEEDS_REVIEW",
        review_reasons=[] if q2_idx >= 0 and q4_idx >= 0 else ["question_boundary_uncertain"],
    )
    if q2:
        nodes.append(q2)

    q4_end = practice_idx if practice_idx >= 0 else len(ordered)
    q4 = _node_from_line_range(
        node_id="question_004_best_title",
        node_type="question",
        title="What can be the best title of the passage?",
        lines=ordered,
        start=q4_idx,
        end=q4_end,
        shared_context_id="passage_001",
        review_status="PROBE_READY" if q4_idx >= 0 and practice_idx >= 0 else "NEEDS_REVIEW",
        review_reasons=[] if q4_idx >= 0 and practice_idx >= 0 else ["question_boundary_uncertain"],
    )
    if q4:
        nodes.append(q4)

    practice = _node_from_line_range(
        node_id="practice_passage_002_start",
        node_type="shared_context",
        title="practice passage start: recurring dreams",
        lines=ordered,
        start=practice_idx,
        end=len(ordered),
        review_reasons=["truncated_at_page_range_end"],
    )
    if practice:
        nodes.append(practice)

    question_packets: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("node_type") != "question":
            continue
        text = str(node.get("text", ""))
        answer_match = re.search(r"(?:【答案】|銆愮瓟妗堛€慭?)([A-D])", text)
        answer = answer_match.group(1) if answer_match else ""
        option_lines = [line for line in text.splitlines() if re.match(r"^\s*[A-D][.)．]", line)]
        question_packets.append(
            {
                "question_uid": node["node_id"],
                "schema": "question_packet_probe_v0.1",
                "question_type": "single_choice",
                "stem": node["title"],
                "shared_context_id": node.get("shared_context_id", ""),
                "options_text": option_lines,
                "answer": answer,
                "source_pages": list(range(int(node["page_start"]), int(node["page_end"]) + 1)),
                "ocr_line_refs": node.get("ocr_line_refs", []),
                "review_status": node.get("review_status", "NEEDS_REVIEW"),
                "note": "probe output; not runtime importable yet",
            }
        )

    return {
        "schema": "english_reading_structure_fit_probe_v0.1",
        "strategy": "coarse_anchor_fit_from_ocr_lines_with_page_coordinates",
        "anchors": {
            "example_start": ordered[example_idx].line_id if example_idx >= 0 else "",
            "q2": ordered[q2_idx].line_id if q2_idx >= 0 else "",
            "q4": ordered[q4_idx].line_id if q4_idx >= 0 else "",
            "practice_start": ordered[practice_idx].line_id if practice_idx >= 0 else "",
        },
        "nodes": nodes,
        "question_packets": question_packets,
        "warnings": warnings,
    }


def _overlap_ratio(a: list[int], b: list[int]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    smaller = min(max(1, (a[2] - a[0]) * (a[3] - a[1])), max(1, (b[2] - b[0]) * (b[3] - b[1])))
    return inter / smaller


def build_text_units(lines: list[OcrLine], visual_objects: list[VisualObject]) -> list[TextUnit]:
    units: list[TextUnit] = []
    current: list[OcrLine] = []
    current_type = ""

    def flush() -> None:
        nonlocal current, current_type
        if not current:
            return
        unit_id = f"u{len(units) + 1:04d}"
        page_boxes: dict[str, list[list[int]]] = {}
        for line in current:
            page_boxes.setdefault(str(line.page), []).append(line.bbox_px)
        bbox_by_page = {page: union_box(boxes) for page, boxes in page_boxes.items()}
        text = "\n".join(line.text for line in current)
        refs = [line.line_id for line in current]
        avg_conf = sum(line.confidence for line in current) / max(len(current), 1)
        flags: list[str] = []
        if len({line.page for line in current}) > 1:
            flags.append("cross_page_text_unit")
        attached_visuals = []
        for obj in visual_objects:
            if str(obj.page) in bbox_by_page and _overlap_ratio(obj.bbox_px, bbox_by_page[str(obj.page)]) > 0.12:
                attached_visuals.append(obj.object_id)
        units.append(
            TextUnit(
                unit_id=unit_id,
                unit_type=current_type or "body",
                page_start=min(line.page for line in current),
                page_end=max(line.page for line in current),
                text=text,
                ocr_line_refs=refs,
                bbox_px_by_page=bbox_by_page,
                confidence=round(avg_conf, 4),
                flags=flags,
                visual_object_refs=attached_visuals,
            )
        )
        current = []
        current_type = ""

    for line in lines:
        line_type = classify_line(line.text)
        unit_type = line_type
        if line_type in {"option", "vocabulary"}:
            unit_type = line_type
        if line_type == "body":
            unit_type = "knowledge_body"
        if not current:
            current = [line]
            current_type = unit_type
            continue
        previous = current[-1]
        same_run = unit_type == current_type and line.page == previous.page and line.bbox_px[1] - previous.bbox_px[3] < 95
        if current_type == "passage" and unit_type == "passage" and line.page <= previous.page + 1:
            same_run = True
        if current_type == "analysis" and unit_type in {"analysis", "passage", "body", "knowledge_body"} and line.page == previous.page:
            same_run = True
        if same_run:
            current.append(line)
        else:
            flush()
            current = [line]
            current_type = unit_type
    flush()
    return units


def fit_semantic_nodes(units: list[TextUnit], visual_objects: list[VisualObject]) -> list[SemanticNodeProbe]:
    nodes: list[SemanticNodeProbe] = []
    passage_id = ""
    active_question_index = 0
    active_question: SemanticNodeProbe | None = None

    def close_question() -> None:
        nonlocal active_question
        if active_question:
            if active_question.answer_text and active_question.analysis_text:
                active_question.review_status = "PROBE_READY"
            else:
                active_question.review_reasons.append("answer_or_analysis_incomplete_in_probe")
            nodes.append(active_question)
            active_question = None

    for unit in units:
        if unit.unit_type in {"heading", "knowledge_body"}:
            close_question()
            nodes.append(
                SemanticNodeProbe(
                    node_id=f"knowledge_{len(nodes) + 1:03d}",
                    node_type="knowledge_block",
                    title=unit.text.splitlines()[0][:80],
                    page_start=unit.page_start,
                    page_end=unit.page_end,
                    text=unit.text,
                    child_unit_ids=[unit.unit_id],
                    visual_object_refs=unit.visual_object_refs,
                    review_status="NEEDS_REVIEW",
                    review_reasons=["probe_knowledge_not_auto_ingested"],
                )
            )
            continue
        if unit.unit_type == "passage":
            close_question()
            if not passage_id:
                passage_id = "passage_001"
            nodes.append(
                SemanticNodeProbe(
                    node_id=passage_id if not any(n.node_id == passage_id for n in nodes) else f"{passage_id}_cont_{len(nodes):03d}",
                    node_type="shared_context",
                    title="reading passage",
                    page_start=unit.page_start,
                    page_end=unit.page_end,
                    text=unit.text,
                    child_unit_ids=[unit.unit_id],
                    visual_object_refs=unit.visual_object_refs,
                    review_status="NEEDS_REVIEW",
                    review_reasons=["probe_shared_context_requires_group_validation"],
                )
            )
            continue
        if unit.unit_type == "question":
            close_question()
            active_question_index += 1
            active_question = SemanticNodeProbe(
                node_id=f"question_{active_question_index:03d}",
                node_type="question",
                title=unit.text.splitlines()[0][:100],
                page_start=unit.page_start,
                page_end=unit.page_end,
                text=unit.text,
                child_unit_ids=[unit.unit_id],
                shared_context_id=passage_id,
                visual_object_refs=unit.visual_object_refs,
                review_status="NEEDS_REVIEW",
                review_reasons=[],
            )
            continue
        if active_question and unit.unit_type in {"option", "answer", "analysis"}:
            active_question.page_end = max(active_question.page_end, unit.page_end)
            active_question.child_unit_ids.append(unit.unit_id)
            active_question.visual_object_refs.extend([ref for ref in unit.visual_object_refs if ref not in active_question.visual_object_refs])
            if unit.unit_type == "answer":
                active_question.answer_text = "\n".join(filter(None, [active_question.answer_text, unit.text]))
            elif unit.unit_type == "analysis":
                active_question.analysis_text = "\n".join(filter(None, [active_question.analysis_text, unit.text]))
            else:
                active_question.text = "\n".join(filter(None, [active_question.text, unit.text]))
            continue
        close_question()
        nodes.append(
            SemanticNodeProbe(
                node_id=f"review_{len(nodes) + 1:03d}",
                node_type="review_unit",
                title=unit.unit_type,
                page_start=unit.page_start,
                page_end=unit.page_end,
                text=unit.text,
                child_unit_ids=[unit.unit_id],
                visual_object_refs=unit.visual_object_refs,
                review_status="NEEDS_REVIEW",
                review_reasons=["unattached_probe_unit"],
            )
        )
    close_question()
    return nodes


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


def write_review_html(path: Path, units: list[TextUnit], nodes: list[SemanticNodeProbe], visual_objects: list[VisualObject]) -> None:
    unit_cards = []
    for unit in units:
        unit_cards.append(
            f"<article><h3>{html.escape(unit.unit_id)} · {html.escape(unit.unit_type)}</h3>"
            f"<div class='meta'>p{unit.page_start}-{unit.page_end} · conf {unit.confidence} · lines {len(unit.ocr_line_refs)}</div>"
            f"<pre>{html.escape(unit.text)}</pre></article>"
        )
    node_cards = []
    for node in nodes:
        node_cards.append(
            f"<article><h3>{html.escape(node.node_id)} · {html.escape(node.node_type)} · {html.escape(node.review_status)}</h3>"
            f"<div class='meta'>p{node.page_start}-{node.page_end} · context {html.escape(node.shared_context_id)}</div>"
            f"<pre>{html.escape(node.text[:1600])}</pre>"
            f"<div class='answer'>{html.escape(node.answer_text[:500])}</div>"
            f"<div class='analysis'>{html.escape(node.analysis_text[:900])}</div>"
            f"<div class='meta'>{html.escape(', '.join(node.review_reasons))}</div></article>"
        )
    visual_cards = []
    for obj in visual_objects:
        visual_cards.append(
            f"<article><h3>{html.escape(obj.object_id)} · {html.escape(obj.object_type)}</h3>"
            f"<div class='meta'>p{obj.page} · conf {obj.confidence} · bbox {html.escape(str(obj.bbox_px))}</div>"
            f"<img src='{html.escape(Path(obj.crop_path).name)}'></article>"
        )
    path.write_text(
        f"""<!doctype html>
<meta charset="utf-8">
<title>English OCR Text-First Probe</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f7f7f5;color:#202124}}
h1{{font-size:24px}} h2{{margin-top:32px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}}
article{{background:white;border:1px solid #ddd;border-radius:6px;padding:12px}}
h3{{font-size:15px;margin:0 0 8px}} .meta{{font-size:12px;color:#666;margin:4px 0 8px}}
pre{{white-space:pre-wrap;font-size:12px;line-height:1.45;max-height:360px;overflow:auto;background:#fafafa;padding:8px}}
.answer{{color:#9b1c31;white-space:pre-wrap;font-size:12px}} .analysis{{color:#6b2633;white-space:pre-wrap;font-size:12px}}
img{{max-width:100%;border:1px solid #ddd}}
</style>
<h1>English OCR Text-First Probe</h1>
<p>This is a probe artifact. It is not production ingest output.</p>
<h2>Semantic Nodes</h2><div class="grid">{''.join(node_cards)}</div>
<h2>Text Units</h2><div class="grid">{''.join(unit_cards)}</div>
<h2>Visual Objects</h2><div class="grid">{''.join(visual_cards)}</div>
""",
        encoding="utf-8",
    )


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


def main() -> None:
    parser = argparse.ArgumentParser(description="English image-PDF OCR text-first probe v0.1.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--doc-key", default="english")
    parser.add_argument("--pages", default="1-6")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(args.pages)
    if not pdf_path.exists():
        raise SystemExit(f"pdf_not_found: {pdf_path}")

    page_images = render_pages(pdf_path, pages, out_dir / "page_images", args.dpi)
    lines, ocr_meta = run_ocr(page_images)
    visual_objects = detect_visual_objects(page_images, out_dir / "visual_objects")
    units = build_text_units(lines, visual_objects)
    nodes = fit_semantic_nodes(units, visual_objects)
    coarse_fit = fit_reading_six_page_structure(lines)
    draw_ocr_overlays(page_images, lines, visual_objects, out_dir / "ocr_overlays")

    write_json(out_dir / "ocr_lines.json", {"schema": "english_ocr_lines_probe_v0.1", "lines": [asdict(line) for line in lines]})
    write_json(out_dir / "ocr_run_meta.json", ocr_meta)
    write_json(out_dir / "visual_objects.json", {"schema": "english_visual_objects_probe_v0.1", "objects": [asdict(obj) for obj in visual_objects]})
    write_json(out_dir / "english_text_units.json", {"schema": "english_text_units_probe_v0.1", "units": [asdict(unit) for unit in units]})
    write_json(out_dir / "semantic_nodes_probe.json", {"schema": "semantic_nodes_probe_v0.1", "nodes": [asdict(node) for node in nodes]})
    write_json(out_dir / "coarse_structure_fit.json", coarse_fit)
    write_json(
        out_dir / "question_packets_probe.json",
        {"schema": "question_packets_probe_v0.1", "questions": coarse_fit.get("question_packets", [])},
    )
    write_page_text(out_dir / "ocr_page_text.md", lines)
    write_review_html(out_dir / "review.html", units, nodes, visual_objects)

    summary = {
        "schema": "english_image_pdf_text_first_probe_run_v0.1",
        "entry": "tools/english_image_pdf_text_first_probe_v01.py",
        "pdf": str(pdf_path),
        "doc_key": str(args.doc_key),
        "pages": pages,
        "page_count": len(page_images),
        "ocr_line_count": len(lines),
        "visual_object_count": len(visual_objects),
        "text_unit_count": len(units),
        "semantic_node_count": len(nodes),
        "coarse_fit_node_count": len(coarse_fit.get("nodes", [])),
        "coarse_fit_question_packet_count": len(coarse_fit.get("question_packets", [])),
        "coarse_fit_warnings": coarse_fit.get("warnings", []),
        "node_type_counts": {kind: sum(1 for node in nodes if node.node_type == kind) for kind in sorted({node.node_type for node in nodes})},
        "review_status_counts": {status: sum(1 for node in nodes if node.review_status == status) for status in sorted({node.review_status for node in nodes})},
        "artifacts": {
            "ocr_lines": str(out_dir / "ocr_lines.json"),
            "ocr_text": str(out_dir / "ocr_page_text.md"),
            "visual_objects": str(out_dir / "visual_objects.json"),
            "text_units": str(out_dir / "english_text_units.json"),
            "semantic_nodes": str(out_dir / "semantic_nodes_probe.json"),
            "coarse_structure_fit": str(out_dir / "coarse_structure_fit.json"),
            "question_packets_probe": str(out_dir / "question_packets_probe.json"),
            "review_html": str(out_dir / "review.html"),
            "ocr_overlays": str(out_dir / "ocr_overlays"),
        },
    }
    write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
