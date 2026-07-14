from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.layout_block_extractor_v03 import BlockCandidateV03
from tools.vision_prompt_store import (
    get_split_v03_english_semantic_assembler_prompt_bundle,
    get_split_v03_semantic_assembler_prompt_bundle,
)


ARK_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


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


def _extract_json_block(text: str) -> dict:
    clean = str(text or "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json_not_found")
    return json.loads(clean[start : end + 1])


def _compact_block(block: BlockCandidateV03) -> dict:
    return {
        "block_id": block.block_id,
        "page": block.page,
        "bbox_px": block.bbox_px,
        "bbox_norm": block.bbox_norm,
        "text_stub": block.text_stub,
        "candidate_flags": block.candidate_flags,
        "visual_features": {
            "role_hint": block.visual_features.get("role_hint", ""),
            "block_type": block.visual_features.get("block_type", ""),
            "visible_question_numbers": block.visual_features.get("visible_question_numbers", []),
            "continues_previous_page": block.visual_features.get("continues_previous_page", False),
            "starts_with_visible_question_number": block.visual_features.get("starts_with_visible_question_number", False),
        },
    }


def _is_english_doc(doc_key: str) -> bool:
    lowered = str(doc_key or "").lower()
    return lowered.startswith("english") or "_english" in lowered or "reading" in lowered or "writing" in lowered or "grammar" in lowered


def _english_profile_subtype(doc_key: str) -> str:
    lowered = str(doc_key or "").lower()
    if "writing" in lowered or "help_letter" in lowered or "letter" in lowered:
        return "english_writing_task_pack"
    if "grammar" in lowered or "relative_clause" in lowered or "clause" in lowered:
        return "english_grammar_practice"
    if "reading" in lowered or "mainidea" in lowered or "application" in lowered:
        return "english_reading_passage_group"
    return "english_general_handout"


def _call_visual_semantic_assembler(
    *,
    doc_key: str,
    blocks: list[BlockCandidateV03],
    api_key: str,
    model: str,
    timeout_seconds: int = 120,
) -> dict:
    is_english = _is_english_doc(doc_key)
    bundle = get_split_v03_english_semantic_assembler_prompt_bundle() if is_english else get_split_v03_semantic_assembler_prompt_bundle()
    profile_subtype = _english_profile_subtype(doc_key) if is_english else "general"
    page_range = (
        f"{min(block.page for block in blocks)}-{max(block.page for block in blocks)}"
        if blocks
        else ""
    )
    user_prompt = (
        bundle["user_template"]
        .replace("{{DOC_KEY}}", doc_key)
        .replace("{{PAGE_RANGE}}", page_range)
        .replace("{{PROFILE_SUBTYPE}}", profile_subtype)
        .replace("{{READING_BLOCKS_JSON}}", json.dumps([_compact_block(block) for block in blocks], ensure_ascii=False))
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": bundle["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        ARK_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    parsed = _extract_json_block(payload["choices"][0]["message"]["content"])
    parsed["_meta"] = {
        "provider": "visual",
        "model": model,
        "prompt_version": bundle["prompt_version"],
        "latency_seconds": round(time.time() - started, 3),
        "usage": payload.get("usage", {}),
    }
    return parsed


def _coerce_assignment(raw: dict, block_ids: set[str]) -> BlockAssignmentV03 | None:
    if not isinstance(raw, dict):
        return None
    block_id = str(raw.get("block_id", "") or "")
    if block_id not in block_ids:
        return None
    action = str(raw.get("node_action", "") or "")
    if action not in {"new_node", "attach_to_existing", "quarantine"}:
        return None
    node_id = str(raw.get("node_id", "") or "")
    new_node_type = str(raw.get("new_node_type", "") or "")
    if action == "new_node" and new_node_type not in {"question", "knowledge_block", "quarantined_orphan"}:
        return None
    if action == "attach_to_existing" and not node_id:
        return None
    role = str(raw.get("role", "") or "unassigned")
    allowed_roles = {
        "question_body",
        "body_continuation",
        "answer_block",
        "analysis_block",
        "translation_block",
        "section_heading",
        "knowledge_body",
        "table_body",
        "diagram_body",
        "unassigned",
    }
    if role not in allowed_roles:
        role = "unassigned"
    try:
        confidence = float(raw.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    return BlockAssignmentV03(
        block_id=block_id,
        node_action=action,
        node_id=node_id,
        new_node_type=new_node_type,
        role=role,
        confidence=max(0.0, min(1.0, confidence)),
        reason_code=str(raw.get("reason_code", "") or "visual_semantic_assembler"),
    )


def visual_semantic_assignments_v03(
    blocks: list[BlockCandidateV03],
    *,
    doc_key: str,
    api_key: str,
    model: str = "doubao-seed-2-0-lite-260428",
) -> list[BlockAssignmentV03]:
    if not blocks:
        return []
    if not api_key:
        return mock_semantic_assignments_v03(blocks)
    try:
        parsed = _call_visual_semantic_assembler(doc_key=doc_key, blocks=blocks, api_key=api_key, model=model)
        raw_assignments = parsed.get("assignments", [])
        if not isinstance(raw_assignments, list):
            raise ValueError("assignments_not_list")
        block_ids = {block.block_id for block in blocks}
        assignments = []
        assigned_ids: set[str] = set()
        for raw in raw_assignments:
            item = _coerce_assignment(raw, block_ids)
            if item is None:
                continue
            if item.block_id in assigned_ids:
                continue
            assignments.append(item)
            assigned_ids.add(item.block_id)
        for block in blocks:
            if block.block_id not in assigned_ids:
                assignments.append(
                    BlockAssignmentV03(
                        block.block_id,
                        "quarantine",
                        "",
                        "",
                        "unassigned",
                        0.2,
                        "visual_assembler_missing_block_assignment",
                    )
                )
        if not assignments:
            raise ValueError("no_valid_assignments")
        return assignments
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError, RuntimeError):
        return mock_semantic_assignments_v03(blocks)


def write_assignments(path: Path, assignments: list[BlockAssignmentV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "semantic_assignments_v0.3", "assignments": [asdict(a) for a in assignments]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
