from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tools.layout_block_extractor_v03 import BlockCandidateV03, _norm_bbox
from tools.page_render_adapter_v03 import PageManifestV03


def _union_box(boxes: list[list[int]]) -> list[int]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _is_noise(block: BlockCandidateV03) -> bool:
    flags = set(block.candidate_flags)
    block_type = str(block.visual_features.get("block_type", ""))
    return "page_number_noise" in flags or block_type == "noise"


def _is_visual_line(block: BlockCandidateV03) -> bool:
    return block.source in {"image_ocr_mock_line", "image_ocr_region_line"}


def _is_visual_region(block: BlockCandidateV03) -> bool:
    return block.source == "visual_vlm_region"


def _line_gap_threshold(blocks: list[BlockCandidateV03], page_height: int) -> int:
    heights = sorted(max(1, b.bbox_px[3] - b.bbox_px[1]) for b in blocks)
    if not heights:
        return max(48, int(page_height * 0.02))
    median = heights[len(heights) // 2]
    return max(int(median * 1.45), int(page_height * 0.012), 44)


def _is_red_line(block: BlockCandidateV03) -> bool:
    return "answer_like" in block.candidate_flags or "analysis_like" in block.candidate_flags or float(block.visual_features.get("red_ratio", 0) or 0) > 0.12


def _group_has_black_text(group: list[BlockCandidateV03]) -> bool:
    return any(not _is_red_line(block) for block in group)


def _flags_for_role(role: str) -> list[str]:
    if role == "question_body":
        return ["possible_question_start", "reading_block"]
    if role == "body_continuation":
        return ["page_top_continuation", "reading_block"]
    if role == "answer_block":
        return ["answer_like", "reading_block"]
    if role == "analysis_block":
        return ["analysis_like", "reading_block"]
    if role == "translation_block":
        return ["translation_like", "reading_block"]
    if role == "section_heading":
        return ["possible_section_heading", "reading_block"]
    return ["reading_block"]


def _merge_flags(base: list[str], group: list[BlockCandidateV03]) -> list[str]:
    merged = list(base)
    for block in group:
        for flag in block.candidate_flags:
            if flag in {"visual_coverage_incomplete", "continues_previous_page", "visible_question_number", "no_visible_question_number", "near_page_bottom"} and flag not in merged:
                merged.append(flag)
    return merged


def _role_for_group(group: list[BlockCandidateV03], page: int, page_height: int) -> tuple[str, list[str]]:
    flags = {flag for block in group for flag in block.candidate_flags}
    y0 = min(block.bbox_px[1] for block in group)
    if "possible_section_heading" in flags:
        return "section_heading", ["possible_section_heading", "reading_block"]
    if "possible_question_start" in flags:
        return "question_body", ["possible_question_start", "reading_block"]
    if "answer_like" in flags or "analysis_like" in flags:
        if _group_has_black_text(group) and not (page > 1 and y0 < page_height * 0.18):
            return "question_body", ["possible_question_start", "reading_block", "visual_cluster_question", "contains_answer_analysis"]
        return "answer_block", ["answer_like", "analysis_like", "reading_block"]
    if page > 1 and y0 < page_height * 0.18:
        return "body_continuation", ["page_top_continuation", "reading_block"]
    return "question_body", ["possible_question_start", "reading_block", "visual_cluster_question"]


def _role_for_visual_region(block: BlockCandidateV03, page_height: int) -> tuple[str, list[str]]:
    flags = set(block.candidate_flags)
    block_type = str(block.visual_features.get("block_type", ""))
    if "continues_previous_page" in flags or bool(block.visual_features.get("continues_previous_page", False)):
        return "body_continuation", ["continues_previous_page", "reading_block"]
    if block_type == "question_candidate" or "possible_question_start" in flags:
        return "question_body", ["possible_question_start", "reading_block"]
    if block_type == "section_heading" or "possible_section_heading" in flags:
        return "section_heading", ["possible_section_heading", "reading_block"]
    if block_type == "knowledge_panel":
        return "knowledge_body", ["knowledge_like", "reading_block"]
    if block_type == "table_panel" or "table_like" in flags:
        return "knowledge_body", ["knowledge_like", "table_like", "reading_block"]
    if block_type == "diagram_panel" or "diagram_like" in flags:
        return "knowledge_body", ["knowledge_like", "diagram_like", "reading_block"]
    y0 = block.bbox_px[1]
    if "page_top_continuation" in flags and y0 < page_height * 0.18:
        return "body_continuation", ["page_top_continuation", "reading_block"]
    return "body_continuation", ["reading_block", "uncertain"]


def _split_red_role_groups(red_lines: list[BlockCandidateV03]) -> list[tuple[str, list[BlockCandidateV03]]]:
    if not red_lines:
        return []
    if len(red_lines) == 1:
        return [("answer_block", red_lines)]
    if len(red_lines) == 2:
        return [("answer_block", red_lines[:1]), ("analysis_block", red_lines[1:])]
    if len(red_lines) == 3:
        return [("answer_block", red_lines[:1]), ("analysis_block", red_lines[1:2]), ("translation_block", red_lines[2:])]
    translation_count = 2 if len(red_lines) >= 5 else 1
    answer = red_lines[:1]
    translation = red_lines[-translation_count:]
    analysis = red_lines[1:-translation_count]
    groups: list[tuple[str, list[BlockCandidateV03]]] = [("answer_block", answer)]
    if analysis:
        groups.append(("analysis_block", analysis))
    if translation:
        groups.append(("translation_block", translation))
    return groups


def _build_visual_line_reading_blocks(
    page_blocks: list[BlockCandidateV03],
    manifest: PageManifestV03,
    doc_key: str,
    start_counter: int,
) -> tuple[list[BlockCandidateV03], int]:
    gap_threshold = _line_gap_threshold(page_blocks, manifest.height_px)
    units: list[list[BlockCandidateV03]] = []
    active: list[BlockCandidateV03] = []
    for block in page_blocks:
        starts_new = False
        if active:
            prev = active[-1]
            gap = block.bbox_px[1] - prev.bbox_px[3]
            active_has_red = any(_is_red_line(item) for item in active)
            current_is_black = not _is_red_line(block)
            left_aligned = block.bbox_px[0] < manifest.width_px * 0.16
            if gap > gap_threshold:
                starts_new = True
            if active_has_red and current_is_black and left_aligned and gap > max(28, int(manifest.height_px * 0.006)):
                starts_new = True
        if starts_new and active:
            units.append(active)
            active = []
        active.append(block)
    if active:
        units.append(active)

    reading_blocks: list[BlockCandidateV03] = []
    counter = start_counter
    for unit in units:
        leading_black: list[BlockCandidateV03] = []
        red_lines: list[BlockCandidateV03] = []
        seen_red = False
        for block in unit:
            if _is_red_line(block):
                seen_red = True
                red_lines.append(block)
            elif not seen_red:
                leading_black.append(block)
            else:
                # A rare black continuation after red belongs to analysis context.
                red_lines.append(block)
        if leading_black:
            y0 = min(block.bbox_px[1] for block in leading_black)
            role = "body_continuation" if manifest.page > 1 and y0 < manifest.height_px * 0.11 else "question_body"
            reading_blocks.append(_make_reading_block(doc_key, counter, leading_black, manifest, role, _merge_flags(_flags_for_role(role), leading_black)))
            counter += 1
        for role, role_group in _split_red_role_groups(red_lines):
            reading_blocks.append(_make_reading_block(doc_key, counter, role_group, manifest, role, _merge_flags(_flags_for_role(role), role_group)))
            counter += 1
    return reading_blocks, counter


def _make_reading_block(
    doc_key: str,
    counter: int,
    group: list[BlockCandidateV03],
    manifest: PageManifestV03,
    role: str,
    flags: list[str],
) -> BlockCandidateV03:
    box = _union_box([block.bbox_px for block in group])
    output_flags = list(flags)
    if role != "section_heading":
        min_height = max(92, int(manifest.height_px * 0.026))
        height = box[3] - box[1]
        if height < min_height:
            extra = min_height - height
            box[1] = max(0, box[1] - extra // 2)
            box[3] = min(manifest.height_px, box[3] + extra - extra // 2)
        if role == "question_body" and box[3] > int(manifest.height_px * 0.90) and "near_page_bottom" not in output_flags:
            output_flags.append("near_page_bottom")
    source_ids = [block.block_id for block in group]
    text_stub = "\n".join(block.text_stub for block in group if block.text_stub)[:360]
    if not text_stub:
        text_stub = f"{doc_key} p{manifest.page} reading_block_{counter:04d}"
    visible_numbers = [
        str(block.visual_features.get("visible_question_number"))
        for block in group
        if block.visual_features.get("visible_question_number") not in {None, ""}
    ]
    continuation_reasons = [
        str(block.visual_features.get("continuation_reason"))
        for block in group
        if block.visual_features.get("continuation_reason")
    ]
    return BlockCandidateV03(
        block_id=f"{doc_key}_rb{counter:05d}",
        doc_key=doc_key,
        page=manifest.page,
        bbox_px=box,
        bbox_norm=_norm_bbox(box, manifest.width_px, manifest.height_px),
        source="reading_block",
        text_stub=text_stub,
        visual_features={
            "coordinate_space": "master_px",
            "role_hint": role,
            "raw_block_ids": source_ids,
            "raw_block_count": len(source_ids),
            "raw_sources": sorted({block.source for block in group}),
            "starts_with_visible_question_number": any(
                bool(block.visual_features.get("starts_with_visible_question_number", False)) for block in group
            ),
            "visible_question_numbers": visible_numbers,
            "continues_previous_page": any(bool(block.visual_features.get("continues_previous_page", False)) for block in group),
            "continuation_reasons": continuation_reasons,
        },
        candidate_flags=output_flags,
    )


def build_reading_blocks_v03(raw_blocks: list[BlockCandidateV03], manifests: list[PageManifestV03], doc_key: str) -> list[BlockCandidateV03]:
    manifest_by_page = {manifest.page: manifest for manifest in manifests}
    reading_blocks: list[BlockCandidateV03] = []
    counter = 1
    for page in sorted({block.page for block in raw_blocks}):
        manifest = manifest_by_page.get(page)
        if manifest is None:
            continue
        page_blocks = [block for block in raw_blocks if block.page == page and not _is_noise(block)]
        page_blocks.sort(key=lambda block: (block.bbox_px[1], block.bbox_px[0]))
        if not page_blocks:
            continue

        visual_line_mode = sum(1 for block in page_blocks if _is_visual_line(block)) >= max(3, len(page_blocks) // 2)
        visual_region_mode = sum(1 for block in page_blocks if _is_visual_region(block)) >= max(1, len(page_blocks) // 2)
        if visual_region_mode:
            for block in page_blocks:
                role, flags = _role_for_visual_region(block, manifest.height_px)
                reading_blocks.append(_make_reading_block(doc_key, counter, [block], manifest, role, _merge_flags(flags, [block])))
                counter += 1
            continue
        if visual_line_mode:
            built, counter = _build_visual_line_reading_blocks(page_blocks, manifest, doc_key, counter)
            reading_blocks.extend(built)
            continue
        gap_threshold = _line_gap_threshold(page_blocks, manifest.height_px)
        groups: list[list[BlockCandidateV03]] = []
        active: list[BlockCandidateV03] = []

        for block in page_blocks:
            starts_new = False
            flags = set(block.candidate_flags)
            if active:
                prev = active[-1]
                gap = block.bbox_px[1] - prev.bbox_px[3]
                starts_new = gap > gap_threshold
                if visual_line_mode:
                    active_has_red = any(_is_red_line(item) for item in active)
                    current_is_black = not _is_red_line(block)
                    left_aligned_question_like = block.bbox_px[0] < manifest.width_px * 0.16
                    after_answer_gap = gap > max(28, int(manifest.height_px * 0.006))
                    if active_has_red and current_is_black and left_aligned_question_like and after_answer_gap:
                        starts_new = True
                if not visual_line_mode and "possible_question_start" in flags:
                    starts_new = True
                if "possible_section_heading" in flags:
                    starts_new = True
            if starts_new and active:
                groups.append(active)
                active = []
            active.append(block)
        if active:
            groups.append(active)

        for group in groups:
            role, flags = _role_for_group(group, page, manifest.height_px)
            if role == "section_heading":
                flags = ["possible_section_heading", "reading_block"]
            block = _make_reading_block(doc_key, counter, group, manifest, role, _merge_flags(flags, group))
            reading_blocks.append(block)
            counter += 1
    return reading_blocks


def write_reading_blocks(path: Path, blocks: list[BlockCandidateV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "reading_blocks_v0.3", "block_count": len(blocks), "blocks": [asdict(block) for block in blocks]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_block_overlay(path: Path, manifest: PageManifestV03, blocks: list[BlockCandidateV03], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(manifest.page_image_master).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 22)
    except Exception:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, min(img.width - 1, 920), 42), fill=(235, 243, 255))
    draw.text((12, 8), title, fill=(30, 80, 150), font=font)
    for block in [b for b in blocks if b.page == manifest.page]:
        color = (20, 130, 220)
        if "answer_like" in block.candidate_flags or "analysis_like" in block.candidate_flags:
            color = (210, 50, 80)
        elif "possible_section_heading" in block.candidate_flags:
            color = (60, 150, 70)
        elif "page_top_continuation" in block.candidate_flags:
            color = (230, 130, 20)
        x0, y0, x1, y1 = block.bbox_px
        draw.rectangle((x0, y0, x1, y1), outline=color, width=4)
        draw.text((x0, max(0, y0 - 24)), block.block_id, fill=color, font=font)
    img.thumbnail((1200, 1700))
    img.save(path, quality=92)
