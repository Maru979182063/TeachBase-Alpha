from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.layout_block_extractor_v03 import BlockCandidateV03


@dataclass
class BlockAssignmentV03:
    block_id: str
    node_action: str
    node_id: str
    new_node_type: str
    role: str
    confidence: float
    reason_code: str


def role_from_flags(flags: list[str]) -> str:
    if "answer_like" in flags:
        return "answer_block"
    if "analysis_like" in flags:
        return "analysis_block"
    if "translation_like" in flags:
        return "translation_block"
    if "possible_section_heading" in flags:
        return "section_heading"
    if "possible_question_start" in flags:
        return "question_body"
    return "body_continuation"


def _continues_previous_page(block: BlockCandidateV03, active_node: str, active_page: int) -> bool:
    if not active_node or not active_page:
        return False
    if block.page != active_page + 1:
        return False
    flags = set(block.candidate_flags)
    if "continues_previous_page" in flags or "page_top_continuation" in flags:
        return True
    features = block.visual_features or {}
    return bool(features.get("continues_previous_page", False))


def _bbox_height(block: BlockCandidateV03) -> int:
    if len(block.bbox_px) < 4:
        return 0
    return max(0, int(block.bbox_px[3]) - int(block.bbox_px[1]))


def _is_large_section(block: BlockCandidateV03) -> bool:
    """Large teaching panels must become knowledge nodes, not question prefixes."""
    flags = set(block.candidate_flags)
    if "knowledge_like" in flags or "table_like" in flags or "diagram_like" in flags:
        return True
    norm_height = 0.0
    if len(block.bbox_norm) >= 4:
        norm_height = max(0.0, float(block.bbox_norm[3]) - float(block.bbox_norm[1]))
    text = str(block.text_stub or "")
    return _bbox_height(block) >= 900 or norm_height >= 0.18 or len(text) >= 180


def _is_attachable_section_label(block: BlockCandidateV03) -> bool:
    """Small component labels may travel with the first question for context."""
    if "possible_section_heading" not in set(block.candidate_flags):
        return False
    if _is_large_section(block):
        return False
    return _bbox_height(block) <= 360 and len(str(block.text_stub or "")) <= 120


def _knowledge_assignment(block: BlockCandidateV03, counter: int, reason: str) -> BlockAssignmentV03:
    return BlockAssignmentV03(
        block.block_id,
        "new_node",
        f"{block.doc_key}_knowledge_{block.page:03d}_{counter:03d}",
        "knowledge_block",
        "knowledge_body" if _is_large_section(block) else "section_heading",
        0.78,
        reason,
    )


def _flush_pending_sections(assignments: list[BlockAssignmentV03], pending_sections: list[BlockCandidateV03], question_counter: int, reason: str) -> int:
    for section in pending_sections:
        assignments.append(_knowledge_assignment(section, question_counter, reason))
        question_counter += 1
    pending_sections.clear()
    return question_counter


def mock_semantic_assignments_v03(blocks: list[BlockCandidateV03]) -> list[BlockAssignmentV03]:
    assignments: list[BlockAssignmentV03] = []
    active_node = ""
    active_page = 0
    pending_sections: list[BlockCandidateV03] = []
    question_counter = 1
    for block in sorted(blocks, key=lambda b: (b.doc_key, b.page, b.bbox_px[1], b.bbox_px[0])):
        if pending_sections and block.page != pending_sections[-1].page:
            question_counter = _flush_pending_sections(assignments, pending_sections, question_counter, "section_not_carried_across_page")
        if active_node and active_page and block.page > active_page + 1:
            active_node = ""
            active_page = 0
        flags = block.candidate_flags
        if "page_number_noise" in flags:
            assignments.append(BlockAssignmentV03(block.block_id, "quarantine", "", "", "page_number_noise", 0.99, "page_number_noise"))
            continue
        if "knowledge_like" in flags and "possible_question_start" not in flags:
            node_id = f"{block.doc_key}_knowledge_{block.page:03d}_{question_counter:03d}"
            question_counter += 1
            assignments.append(
                BlockAssignmentV03(
                    block.block_id,
                    "new_node",
                    node_id,
                    "knowledge_block",
                    "knowledge_body",
                    0.76,
                    "visual_knowledge_panel",
                )
            )
            continue
        if "possible_section_heading" in flags and "possible_question_start" not in flags:
            if _is_attachable_section_label(block):
                pending_sections.append(block)
            else:
                assignments.append(_knowledge_assignment(block, question_counter, "large_section_kept_as_knowledge"))
                question_counter += 1
            continue
        if _continues_previous_page(block, active_node, active_page):
            active_page = block.page
            assignments.append(
                BlockAssignmentV03(
                    block.block_id,
                    "attach_to_existing",
                    active_node,
                    "",
                    "body_continuation",
                    0.8,
                    "model_marked_cross_page_continuation",
                )
            )
            continue
        if "possible_question_start" in flags:
            active_node = f"{block.doc_key}_q_{question_counter:03d}"
            active_page = block.page
            question_counter += 1
            assignments.append(BlockAssignmentV03(block.block_id, "new_node", active_node, "question", "question_body", 0.82, "possible_question_start"))
            for section in pending_sections:
                if _is_attachable_section_label(section) and section.page == block.page:
                    assignments.append(
                        BlockAssignmentV03(
                            section.block_id,
                            "attach_to_existing",
                            active_node,
                            "",
                            "section_heading",
                            0.72,
                            "attach_section_heading_to_next_question",
                        )
                    )
                else:
                    assignments.append(_knowledge_assignment(section, question_counter, "pending_section_split_from_question"))
                    question_counter += 1
            pending_sections = []
            continue
        if active_node and ("answer_like" in flags or "analysis_like" in flags or "translation_like" in flags):
            active_page = block.page
            assignments.append(BlockAssignmentV03(block.block_id, "attach_to_existing", active_node, "", role_from_flags(flags), 0.78, "attach_answer_analysis_to_open_question"))
            continue
        if active_node:
            active_page = block.page
            assignments.append(BlockAssignmentV03(block.block_id, "attach_to_existing", active_node, "", "body_continuation", 0.58, "reading_order_attach"))
            continue
        assignments.append(BlockAssignmentV03(block.block_id, "quarantine", "", "", "unassigned", 0.4, "no_open_node"))
    for section in pending_sections:
        assignments.append(_knowledge_assignment(section, question_counter, "unattached_section_heading"))
        question_counter += 1
    return assignments


def write_assignments(path: Path, assignments: list[BlockAssignmentV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "semantic_assignments_v0.3", "assignments": [asdict(a) for a in assignments]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
