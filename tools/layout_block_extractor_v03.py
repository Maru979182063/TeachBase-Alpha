from __future__ import annotations

import json
import base64
import http.client
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
VENDOR_DIR = THIS_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import fitz
from PIL import Image, ImageDraw, ImageFont

from tools.page_render_adapter_v03 import PageManifestV03


QUESTION_HEAD_RE = re.compile(r"^\s*(?:\d{1,2}[.．、)]|【\s*(?:例|练|变式)\s*\d+)")
ANSWER_RE = re.compile(r"(【答案】|答案|参考答案)")
ANALYSIS_RE = re.compile(r"(【解析】|解析|【详解】|详解|【分析】|分析)")
SECTION_RE = re.compile(r"(知识|梳理|方法|例题讲解|强化训练|课后|要点|回顾|思维导图|词法|句法|内环境|稳态|考点)")
ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


@dataclass
class BlockCandidateV03:
    block_id: str
    doc_key: str
    page: int
    bbox_px: list[int]
    bbox_norm: list[float]
    source: str
    text_stub: str
    visual_features: dict = field(default_factory=dict)
    candidate_flags: list[str] = field(default_factory=list)


def _norm_bbox(box: list[int], width: int, height: int) -> list[float]:
    return [
        round(box[0] / max(width, 1), 6),
        round(box[1] / max(height, 1), 6),
        round(box[2] / max(width, 1), 6),
        round(box[3] / max(height, 1), 6),
    ]


def _flags(text: str) -> list[str]:
    flags: list[str] = []
    if QUESTION_HEAD_RE.search(text):
        flags.append("possible_question_start")
    if ANSWER_RE.search(text):
        flags.append("answer_like")
    if ANALYSIS_RE.search(text):
        flags.append("analysis_like")
    if SECTION_RE.search(text):
        flags.append("possible_section_heading")
    if re.fullmatch(r"\s*\d{1,3}\s*", text or ""):
        flags.append("page_number_noise")
    return flags


def _extract_pdf_line_blocks(pdf_path: str, manifests: list[PageManifestV03], doc_key: str) -> list[BlockCandidateV03]:
    doc = fitz.open(pdf_path)
    blocks: list[BlockCandidateV03] = []
    counter = 1
    for manifest in manifests:
        page = doc[manifest.page - 1]
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                text = re.sub(r"\s+", " ", text)
                if not text:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                box = [
                    int(x0 * manifest.render_scale),
                    int(y0 * manifest.render_scale),
                    int(x1 * manifest.render_scale),
                    int(y1 * manifest.render_scale),
                ]
                source = "pdf_text_line"
                if doc_key == "english":
                    source = "image_ocr_mock_line"
                blocks.append(
                    BlockCandidateV03(
                        block_id=f"{doc_key}_b{counter:05d}",
                        doc_key=doc_key,
                        page=manifest.page,
                        bbox_px=box,
                        bbox_norm=_norm_bbox(box, manifest.width_px, manifest.height_px),
                        source=source,
                        text_stub=text[:240],
                        visual_features={"line_height": max(1, box[3] - box[1])},
                        candidate_flags=_flags(text),
                    )
                )
                counter += 1
    return blocks


def _detect_ink_line_boxes(manifest: PageManifestV03) -> list[tuple[list[int], dict]]:
    img = Image.open(manifest.page_image_master).convert("RGB")
    width, height = img.size
    pix = img.load()
    row_stats: list[tuple[int, int, int]] = []
    for y in range(0, height):
        xs: list[int] = []
        red_count = 0
        for x in range(0, width, 3):
            r, g, b = pix[x, y]
            is_red = r > 150 and g < 115 and b < 115
            is_dark = r < 120 and g < 120 and b < 120
            is_blue_header = b > 150 and r < 170 and g < 210
            if (is_dark or is_red) and not is_blue_header:
                xs.append(x)
                if is_red:
                    red_count += 1
        if len(xs) >= 8:
            row_stats.append((y, min(xs), max(xs), red_count))
    if not row_stats:
        return []

    bands: list[list[int]] = []
    current = [row_stats[0][0], row_stats[0][0], row_stats[0][1], row_stats[0][2], row_stats[0][3], len(range(row_stats[0][1], row_stats[0][2] + 1, 3))]
    for y, x0, x1, red_count in row_stats[1:]:
        if y <= current[1] + 5:
            current[1] = y
            current[2] = min(current[2], x0)
            current[3] = max(current[3], x1)
            current[4] += red_count
            current[5] += max(1, len(range(x0, x1 + 1, 3)))
        else:
            bands.append(current)
            current = [y, y, x0, x1, red_count, max(1, len(range(x0, x1 + 1, 3)))]
    bands.append(current)

    boxes: list[tuple[list[int], dict]] = []
    for y0, y1, x0, x1, red_count, ink_span in bands:
        if y1 - y0 < 6:
            continue
        if y0 < height * 0.075 and (x1 - x0) > width * 0.45:
            continue
        if y0 < height * 0.025 or y1 > height * 0.985:
            continue
        pad_x = 10
        pad_y = 6
        red_ratio = red_count / max(1, ink_span)
        box = [max(0, x0 - pad_x), max(0, y0 - pad_y), min(width, x1 + pad_x), min(height, y1 + pad_y)]
        boxes.append((box, {"red_ratio": round(red_ratio, 4), "line_height": box[3] - box[1]}))
    return boxes


def _append_image_ocr_mock_regions(blocks: list[BlockCandidateV03], manifests: list[PageManifestV03], doc_key: str) -> None:
    existing_pages = {block.page for block in blocks}
    counter = len(blocks) + 1
    for manifest in manifests:
        if manifest.page in existing_pages:
            continue
        line_boxes = _detect_ink_line_boxes(manifest)
        if not line_boxes:
            line_boxes = [
                ([int(manifest.width_px * 0.08), int(manifest.height_px * 0.08), int(manifest.width_px * 0.92), int(manifest.height_px * 0.34)], {"fallback_region": True}),
                ([int(manifest.width_px * 0.08), int(manifest.height_px * 0.35), int(manifest.width_px * 0.92), int(manifest.height_px * 0.66)], {"fallback_region": True}),
                ([int(manifest.width_px * 0.08), int(manifest.height_px * 0.67), int(manifest.width_px * 0.92), int(manifest.height_px * 0.92)], {"fallback_region": True}),
            ]
        for box, features in line_boxes:
            flags = ["image_ocr_mock_line"]
            if features.get("red_ratio", 0) > 0.12:
                flags.extend(["answer_like", "analysis_like"])
            blocks.append(
                BlockCandidateV03(
                    block_id=f"{doc_key}_b{counter:05d}",
                    doc_key=doc_key,
                    page=manifest.page,
                    bbox_px=box,
                    bbox_norm=_norm_bbox(box, manifest.width_px, manifest.height_px),
                    source="image_ocr_mock_line",
                    text_stub=f"{doc_key} p{manifest.page} visual line y={box[1]}-{box[3]}",
                    visual_features={"mock_ocr": True, **features, "coordinate_space": "master_px"},
                    candidate_flags=flags,
                )
            )
            counter += 1


def _image_to_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def _visual_block_prompt(manifest: PageManifestV03, doc_key: str, tile: dict | None = None) -> str:
    image_width = 1000
    image_height = 1000
    tile_note = ""
    if tile:
        tile_note = f"""

重要：当前输入不是整页，而是原页面的纵向局部窗口。
- 当前窗口在整页 VLM 图中的 y 范围：{tile["y0"]}-{tile["y1"]}。
- 你只需要判断当前窗口内可见的完整/半完整语义块。
- bbox 坐标必须基于当前窗口图片本身的 0-1000 归一化坐标，不要返回整页坐标。
- 如果当前窗口顶部或底部截断了题目，只框可见部分，并在 candidate_flags 加 uncertain。
""".rstrip()
    return f"""
你是 TeachBase split_v03 的视觉切块节点，只负责从页面图片中提出视觉候选块，不做题目转录。

核心原则：
- 你要输出“教学语义单元的大块”，不是文字行、不是答案行、不是红字段落。
- 一个题目单元必须尽量包含：题干 + 选项/填空 + 答案 + 解析 + 翻译/详解 + 图表。
- 如果同一题跨多段显示，也优先框成一个大 bbox；不要把答案、解析、翻译单独拆成块。
- 只有当页面上明确是知识图、表格、树状图、方法讲解整块时，才输出 knowledge_panel/table_panel。
- 页眉、logo、页码、横线、空白、装饰条不要输出。
- 严禁输出行级 bbox：如果一个 bbox 高度小于整页高度的 6%，通常是错误，除非它是独立标题区。
- 对连续的 1) 2) 3) 这种练习题：每个题目输出一个 question_candidate 大块，块的下边界应到该题解析/翻译结束，或下一个题号/新标题之前。
- 必须检查整张输入图从上到下的所有内容；不要只输出上半部分或前几道题。
- 如果输入图下半部仍有题干、答案、解析、翻译、图表或知识块，必须输出对应 bbox。
{tile_note}

任务：
1. 找出页面中的主要视觉区域：题目单元、知识讲解单元、表格/树状图/流程图/图组。
2. 不要逐字抄题；text_stub 只写极短标签，如 question_1, question_2, knowledge_panel。
3. 坐标必须使用 0-1000 归一化坐标：左上角是 (0,0)，右下角是 (1000,1000)。
4. 输出 image_width=1000, image_height=1000；bbox 的 x,y,w,h 都必须在 0-1000 坐标系内。
5. 输出 JSON，不要 Markdown。

字段：
- block_type: question_candidate | knowledge_panel | diagram_panel | table_panel | section_heading | uncertain
- bbox: x,y,w,h
- text_stub: 极短说明
- candidate_flags: possible_question_start / possible_section_heading / diagram_like / table_like / uncertain
- confidence: 0-1

doc_key={doc_key}
page={manifest.page}
image_width={image_width}
image_height={image_height}

输出格式：
{{
  "image_width": {image_width},
  "image_height": {image_height},
  "blocks": [
    {{
      "block_type": "question_candidate",
      "bbox": {{"x": 0, "y": 0, "w": 100, "h": 100}},
      "text_stub": "question_candidate",
      "candidate_flags": ["possible_question_start"],
      "starts_with_visible_question_number": true,
      "visible_question_number": "1",
      "continues_previous_page": false,
      "continuation_reason": "",
      "confidence": 0.8
    }}
  ]
}}

检查清单：
- 不要框 logo。
- 不要框页码。
- 不要框单独答案行。
- 不要框单独解析行。
- 不要框横线。
- 输出块数量通常应少于 12 个；如果超过 12 个，请合并成更大的题目单元。
""".strip()


def _call_visual_block_model(
    manifest: PageManifestV03,
    doc_key: str,
    api_key: str,
    model: str,
    timeout_seconds: int = 180,
    image_path: Path | None = None,
    tile: dict | None = None,
) -> dict:
    content = [
        {"type": "text", "text": _visual_block_prompt(manifest, doc_key, tile=tile)},
        {"type": "image_url", "image_url": {"url": _image_to_data_url(image_path or Path(manifest.page_image_vlm))}},
    ]
    body = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0}
    request = urllib.request.Request(
        ARK_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.time()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500:
                raise RuntimeError(f"http_{exc.code}: {detail}") from exc
            last_error = RuntimeError(f"http_{exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, http.client.RemoteDisconnected) as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"visual_call_failed_after_retries: doc={doc_key} page={manifest.page} error={last_error}") from last_error
    payload = json.loads(raw)
    parsed = _extract_json_block(payload["choices"][0]["message"]["content"])
    parsed["_meta"] = {
        "latency_seconds": round(time.time() - started, 3),
        "usage": payload.get("usage", {}),
    }
    return parsed


def _visual_item_to_master_box(
    item: dict,
    manifest: PageManifestV03,
    source_w: float,
    source_h: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    full_source_w: float | None = None,
    full_source_h: float | None = None,
) -> list[int] | None:
    bbox = item.get("bbox", {}) if isinstance(item.get("bbox"), dict) else {}
    try:
        x = float(bbox.get("x", 0) or 0)
        y = float(bbox.get("y", 0) or 0)
        w = float(bbox.get("w", 0) or 0)
        h = float(bbox.get("h", 0) or 0)
    except Exception:
        return None
    if w <= 5 or h <= 5:
        return None
    map_w = float(full_source_w or source_w or 1)
    map_h = float(full_source_h or source_h or 1)
    box = [
        int(round((offset_x + x) * manifest.width_px / map_w)),
        int(round((offset_y + y) * manifest.height_px / map_h)),
        int(round((offset_x + x + w) * manifest.width_px / map_w)),
        int(round((offset_y + y + h) * manifest.height_px / map_h)),
    ]
    box[0] = max(0, min(manifest.width_px - 1, box[0]))
    box[1] = max(0, min(manifest.height_px - 1, box[1]))
    box[2] = max(box[0] + 1, min(manifest.width_px, box[2]))
    box[3] = max(box[1] + 1, min(manifest.height_px, box[3]))
    return box


def _union_box(a: list[int], b: list[int]) -> list[int]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _normalize_visual_items(
    parsed: dict,
    manifest: PageManifestV03,
    source_w: float,
    source_h: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    full_source_w: float | None = None,
    full_source_h: float | None = None,
    source_tag: str = "full_page",
) -> tuple[list[dict], dict]:
    raw_items: list[dict] = []
    for item in parsed.get("blocks", []):
        if not isinstance(item, dict):
            continue
        box = _visual_item_to_master_box(
            item,
            manifest,
            source_w,
            source_h,
            offset_x=offset_x,
            offset_y=offset_y,
            full_source_w=full_source_w,
            full_source_h=full_source_h,
        )
        if not box:
            continue
        flags = [str(flag) for flag in item.get("candidate_flags", []) if str(flag)]
        block_type = str(item.get("block_type") or "uncertain")
        text_stub = str(item.get("text_stub") or block_type)[:240]
        starts_with_number = bool(item.get("starts_with_visible_question_number", False))
        visible_question_number = item.get("visible_question_number", None)
        if visible_question_number is not None:
            visible_question_number = str(visible_question_number)[:40]
        continues_previous_page = bool(item.get("continues_previous_page", False))
        continuation_reason = str(item.get("continuation_reason") or "")[:160]
        if continues_previous_page and "continues_previous_page" not in flags:
            flags.append("continues_previous_page")
        if starts_with_number and "visible_question_number" not in flags:
            flags.append("visible_question_number")
        if block_type == "question_candidate" and not starts_with_number and not continues_previous_page:
            if "no_visible_question_number" not in flags:
                flags.append("no_visible_question_number")
        if block_type == "noise" or "page_number_noise" in flags:
            continue
        raw_items.append(
            {
                "box": box,
                "block_type": block_type,
                "flags": flags,
                "text_stub": text_stub,
                "confidence": float(item.get("confidence", 0) or 0),
                "children": [block_type],
                "source_tag": source_tag,
                "starts_with_visible_question_number": starts_with_number,
                "visible_question_number": visible_question_number,
                "continues_previous_page": continues_previous_page,
                "continuation_reason": continuation_reason,
            }
        )

    raw_items.sort(key=lambda rec: (rec["box"][1], rec["box"][0]))
    merged: list[dict] = []
    current_question: dict | None = None
    attach_gap = max(90, int(manifest.height_px * 0.055))

    def flush_question() -> None:
        nonlocal current_question
        if current_question is not None:
            merged.append(current_question)
            current_question = None

    for rec in raw_items:
        block_type = rec["block_type"]
        flags = rec["flags"]
        is_answerish = block_type == "answer_analysis" or "answer_like" in flags or "analysis_like" in flags
        if block_type == "question_candidate":
            flush_question()
            rec["flags"] = sorted(set(flags + ["possible_question_start"]))
            rec["block_type"] = "question_candidate"
            current_question = rec
            continue
        if is_answerish:
            if current_question is not None and rec["box"][1] <= current_question["box"][3] + attach_gap:
                current_question["box"] = _union_box(current_question["box"], rec["box"])
                current_question["children"].extend(rec["children"])
                current_question["flags"] = sorted(set(current_question["flags"] + ["visual_merged_answer_analysis"]))
                current_question["confidence"] = min(current_question["confidence"], rec["confidence"] or current_question["confidence"])
            else:
                rec["block_type"] = "uncertain"
                rec["flags"] = sorted(set(flags + ["orphan_answer_analysis"]))
                merged.append(rec)
            continue
        flush_question()
        if block_type == "section_heading" and "possible_section_heading" not in flags:
            rec["flags"] = sorted(set(flags + ["possible_section_heading"]))
        merged.append(rec)

    flush_question()

    final_items: list[dict] = []
    for rec in merged:
        box = rec["box"]
        height_ratio = (box[3] - box[1]) / max(manifest.height_px, 1)
        width_ratio = (box[2] - box[0]) / max(manifest.width_px, 1)
        block_type = rec["block_type"]
        if block_type != "section_heading" and height_ratio < 0.012 and width_ratio > 0.2:
            continue
        final_items.append(rec)

    stats = {
        "raw_blocks": len(parsed.get("blocks", [])),
        "after_noise_filter": len(raw_items),
        "after_merge": len(final_items),
        "source_tag": source_tag,
    }
    return final_items, stats


def _infer_visual_source_size(parsed: dict, fallback_w: int, fallback_h: int) -> tuple[float, float, str]:
    declared_w = float(parsed.get("image_width") or fallback_w or 1)
    declared_h = float(parsed.get("image_height") or fallback_h or 1)
    max_x2 = 0.0
    max_y2 = 0.0
    for item in parsed.get("blocks", []) or []:
        bbox = item.get("bbox", {}) if isinstance(item, dict) else {}
        if not isinstance(bbox, dict):
            continue
        try:
            x = float(bbox.get("x", 0) or 0)
            y = float(bbox.get("y", 0) or 0)
            w = float(bbox.get("w", 0) or 0)
            h = float(bbox.get("h", 0) or 0)
        except Exception:
            continue
        max_x2 = max(max_x2, x + w)
        max_y2 = max(max_y2, y + h)
    if 0 < max_x2 <= 1100 and 0 < max_y2 <= 1100:
        return 1000.0, 1000.0, "normalized_1000_inferred"
    return declared_w, declared_h, "declared"


def _bbox_iou(a: list[int], b: list[int]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom else 0.0


def _dedupe_visual_items(items: list[dict]) -> list[dict]:
    ordered = sorted(items, key=lambda rec: (-float(rec.get("confidence", 0) or 0), rec["box"][1], rec["box"][0]))
    kept: list[dict] = []
    for rec in ordered:
        box = rec["box"]
        if any(_bbox_iou(box, existing["box"]) >= 0.72 for existing in kept):
            continue
        kept.append(rec)
    kept.sort(key=lambda rec: (rec["box"][1], rec["box"][0]))
    return kept


def _ink_span(manifest: PageManifestV03) -> dict:
    line_boxes = _detect_ink_line_boxes(manifest)
    if not line_boxes:
        return {"has_ink": False, "min_y": 0, "max_y": 0, "line_count": 0}
    y0 = min(box[0][1] for box in line_boxes)
    y1 = max(box[0][3] for box in line_boxes)
    lower_count = sum(1 for box, _ in line_boxes if (box[1] + box[3]) / 2 > manifest.height_px * 0.5)
    return {"has_ink": True, "min_y": y0, "max_y": y1, "line_count": len(line_boxes), "lower_half_line_count": lower_count}


def _needs_vertical_rescan(items: list[dict], manifest: PageManifestV03) -> tuple[bool, dict]:
    ink = _ink_span(manifest)
    if not ink["has_ink"]:
        return False, {"reason": "no_ink_detected", "ink": ink}
    max_visual_y = max((item["box"][3] for item in items), default=0)
    max_visual_ratio = max_visual_y / max(manifest.height_px, 1)
    ink_max_ratio = ink["max_y"] / max(manifest.height_px, 1)
    lower_has_ink = ink.get("lower_half_line_count", 0) > 0 or ink_max_ratio > 0.58
    missing_lower = lower_has_ink and max_visual_y < ink["max_y"] - int(manifest.height_px * 0.16)
    too_top_heavy = bool(items) and max_visual_ratio < 0.42 and ink_max_ratio > 0.62
    return bool(missing_lower or too_top_heavy or not items), {
        "reason": "visual_coverage_incomplete" if (missing_lower or too_top_heavy or not items) else "coverage_ok",
        "ink": ink,
        "max_visual_y": max_visual_y,
        "max_visual_ratio": round(max_visual_ratio, 4),
        "ink_max_ratio": round(ink_max_ratio, 4),
        "missing_lower": missing_lower,
        "too_top_heavy": too_top_heavy,
    }


def _tile_specs(manifest: PageManifestV03, coverage: dict | None = None) -> list[dict]:
    h = manifest.vlm_height_px
    w = manifest.vlm_width_px
    if coverage:
        master_h = max(manifest.height_px, 1)
        max_visual_y = int(coverage.get("max_visual_y", 0) or 0)
        ink = coverage.get("ink", {}) if isinstance(coverage.get("ink"), dict) else {}
        ink_max_y = int(ink.get("max_y", manifest.height_px) or manifest.height_px)
        start_master = max(0, max_visual_y - int(master_h * 0.10))
        end_master = min(manifest.height_px, max(ink_max_y + int(master_h * 0.06), int(master_h * 0.65)))
        start_ratio = start_master / master_h
        end_ratio = max(start_ratio + 0.20, end_master / master_h)
        if end_ratio - start_ratio <= 0.52:
            ranges = [(start_ratio, min(1.0, end_ratio))]
        else:
            mid = start_ratio + (end_ratio - start_ratio) * 0.56
            ranges = [(start_ratio, min(1.0, mid)), (max(start_ratio, mid - 0.14), min(1.0, end_ratio))]
    else:
        ranges = [(0.00, 0.42), (0.30, 0.72), (0.60, 1.00)]
    specs: list[dict] = []
    for idx, (a, b) in enumerate(ranges, start=1):
        y0 = max(0, int(round(h * a)))
        y1 = min(h, int(round(h * b)))
        if y1 - y0 < 80:
            continue
        specs.append({"tile_index": idx, "x0": 0, "y0": y0, "x1": w, "y1": y1, "width": w, "height": y1 - y0})
    return specs


def _visual_tile_items(
    manifest: PageManifestV03,
    doc_key: str,
    api_key: str,
    model: str,
    raw_dir: Path,
    coverage: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    src = Image.open(manifest.page_image_vlm).convert("RGB")
    all_items: list[dict] = []
    metas: list[dict] = []
    for spec in _tile_specs(manifest, coverage=coverage):
        tile_img = src.crop((spec["x0"], spec["y0"], spec["x1"], spec["y1"]))
        tile_path = raw_dir / f"p{manifest.page:03d}_tile{spec['tile_index']:02d}.png"
        tile_img.save(tile_path)
        try:
            parsed = _call_visual_block_model(
                manifest,
                doc_key,
                api_key=api_key,
                model=model,
                image_path=tile_path,
                tile=spec,
            )
        except Exception as exc:
            error_meta = {
                "tile": spec,
                "error": str(exc),
                "normalize_stats": {"raw_blocks": 0, "after_noise_filter": 0, "after_merge": 0, "source_tag": f"tile_{spec['tile_index']:02d}"},
                "raw_response": {"blocks": []},
            }
            (raw_dir / f"p{manifest.page:03d}_tile{spec['tile_index']:02d}.error.json").write_text(
                json.dumps(error_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            metas.append(error_meta)
            continue
        source_w, source_h, coordinate_mode = _infer_visual_source_size(parsed, 1000, 1000)
        normalized, stats = _normalize_visual_items(
            parsed,
            manifest,
            source_w,
            source_h,
            offset_x=spec["x0"],
            offset_y=spec["y0"],
            full_source_w=manifest.vlm_width_px,
            full_source_h=manifest.vlm_height_px,
            source_tag=f"tile_{spec['tile_index']:02d}",
        )
        stats["coordinate_mode"] = coordinate_mode
        all_items.extend(normalized)
        meta = dict(parsed.get("_meta", {}))
        meta["tile"] = spec
        meta["normalize_stats"] = stats
        meta["raw_response"] = {k: v for k, v in parsed.items() if k != "_meta"}
        (raw_dir / f"p{manifest.page:03d}_tile{spec['tile_index']:02d}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metas.append(meta)
    return all_items, metas


def _visual_blocks_for_manifest(
    manifest: PageManifestV03,
    doc_key: str,
    api_key: str,
    model: str,
    start_counter: int,
    raw_dir: Path,
    allow_tile_rescan: bool = False,
) -> tuple[list[BlockCandidateV03], dict]:
    parsed = _call_visual_block_model(manifest, doc_key, api_key=api_key, model=model)
    source_w, source_h, coordinate_mode = _infer_visual_source_size(parsed, 1000, 1000)
    normalized_items, normalize_stats = _normalize_visual_items(parsed, manifest, source_w, source_h)
    normalize_stats["coordinate_mode"] = coordinate_mode
    needs_rescan, coverage = _needs_vertical_rescan(normalized_items, manifest)
    tile_metas: list[dict] = []
    if needs_rescan and allow_tile_rescan:
        tile_items, tile_metas = _visual_tile_items(manifest, doc_key, api_key, model, raw_dir, coverage=coverage)
        if tile_items:
            normalized_items = _dedupe_visual_items(normalized_items + tile_items)
            normalize_stats = {
                **normalize_stats,
                "after_tile_rescan_merge": len(normalized_items),
                "tile_item_count": len(tile_items),
            }
            _, coverage = _needs_vertical_rescan(normalized_items, manifest)
    blocks: list[BlockCandidateV03] = []
    counter = start_counter
    coverage_incomplete = coverage.get("reason") != "coverage_ok"
    for item in normalized_items:
        box = item["box"]
        flags = list(item["flags"])
        if coverage_incomplete:
            flags.append("visual_coverage_incomplete")
        block_type = str(item["block_type"] or "uncertain")
        blocks.append(
            BlockCandidateV03(
                block_id=f"{doc_key}_vb{counter:05d}",
                doc_key=doc_key,
                page=manifest.page,
                bbox_px=box,
                bbox_norm=_norm_bbox(box, manifest.width_px, manifest.height_px),
                source="visual_vlm_region",
                text_stub=str(item.get("text_stub") or block_type)[:240],
                visual_features={
                    "block_type": block_type,
                    "confidence": float(item.get("confidence", 0) or 0),
                    "merged_children": item.get("children", []),
                    "source_tag": item.get("source_tag", "full_page"),
                    "starts_with_visible_question_number": bool(item.get("starts_with_visible_question_number", False)),
                    "visible_question_number": item.get("visible_question_number", None),
                    "continues_previous_page": bool(item.get("continues_previous_page", False)),
                    "continuation_reason": item.get("continuation_reason", ""),
                },
                candidate_flags=flags,
            )
        )
        counter += 1
    meta = dict(parsed.get("_meta", {}))
    meta["normalize_stats"] = normalize_stats
    meta["coverage"] = coverage
    meta["tile_rescan_requested"] = bool(needs_rescan)
    meta["tile_rescan_used"] = bool(tile_metas)
    meta["tile_rescan_skipped_reason"] = "" if not needs_rescan else "disabled_policy_visual_single_pass_required"
    meta["tile_meta_count"] = len(tile_metas)
    meta["raw_response"] = {k: v for k, v in parsed.items() if k != "_meta"}
    return blocks, meta


def extract_block_candidates_v03(
    pdf_path: str,
    manifests: list[PageManifestV03],
    doc_key: str,
    overlay_dir: Path,
    provider: str = "mock",
    api_key: str = "",
    model: str = "doubao-seed-2-0-lite-260428",
    max_vlm_calls: int = 0,
) -> list[BlockCandidateV03]:
    blocks: list[BlockCandidateV03]
    if provider == "visual":
        if not api_key:
            raise RuntimeError("visual_provider_requires_api_key")
        if max_vlm_calls < len(manifests):
            raise RuntimeError(f"max_vlm_calls_too_low: need {len(manifests)}, got {max_vlm_calls}")
        blocks = []
        raw_dir = overlay_dir.parent / "visual_provider_raw" / doc_key
        raw_dir.mkdir(parents=True, exist_ok=True)
        counter = 1
        remaining_calls = max_vlm_calls
        for manifest in manifests:
            # Do not auto-split a page into vertical tiles for semantic splitting.
            # Missing lower-page coverage is an audit failure, not a reason to
            # feed chopped page fragments into the planner.
            allow_tile_rescan = False
            try:
                page_blocks, meta = _visual_blocks_for_manifest(
                    manifest,
                    doc_key,
                    api_key,
                    model,
                    counter,
                    raw_dir,
                    allow_tile_rescan=allow_tile_rescan,
                )
            except Exception as exc:
                page_blocks = []
                meta = {
                    "error": str(exc),
                    "coverage": {"reason": "visual_page_call_failed"},
                    "normalize_stats": {"raw_blocks": 0, "after_noise_filter": 0, "after_merge": 0},
                    "raw_response": {"blocks": []},
                    "tile_rescan_requested": False,
                    "tile_rescan_used": False,
                    "tile_meta_count": 0,
                }
            remaining_calls -= 1 + (int(meta.get("tile_meta_count", 0) or 0))
            counter += len(page_blocks)
            blocks.extend(page_blocks)
            (raw_dir / f"p{manifest.page:03d}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        blocks = _extract_pdf_line_blocks(pdf_path, manifests, doc_key)
        _append_image_ocr_mock_regions(blocks, manifests, doc_key)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        img = Image.open(manifest.page_image_master).convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
        except Exception:
            font = ImageFont.load_default()
        for block in [b for b in blocks if b.page == manifest.page]:
            color = (220, 80, 40)
            if "possible_question_start" in block.candidate_flags:
                color = (20, 130, 220)
            elif "answer_like" in block.candidate_flags or "analysis_like" in block.candidate_flags:
                color = (210, 50, 80)
            elif "possible_section_heading" in block.candidate_flags:
                color = (60, 150, 70)
            x0, y0, x1, y1 = block.bbox_px
            draw.rectangle((x0, y0, x1, y1), outline=color, width=3)
            draw.text((x0, max(0, y0 - 24)), block.block_id, fill=color, font=font)
        img.thumbnail((1200, 1700))
        img.save(overlay_dir / f"{manifest.doc_key}_p{manifest.page:03d}_blocks_overlay.png", quality=92)
    return blocks


def write_blocks(path: Path, blocks: list[BlockCandidateV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "block_candidates_v0.3", "block_count": len(blocks), "blocks": [asdict(b) for b in blocks]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
