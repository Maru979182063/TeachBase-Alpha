from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.cross_page_node_accumulator_v03 import SemanticNodeV03


@dataclass
class AuditRecordV03:
    node_id: str
    status: str
    reasons: list[str] = field(default_factory=list)


def _bbox_overlap_y(a: list[int], b: list[int]) -> int:
    if len(a) < 4 or len(b) < 4:
        return 0
    return max(0, min(int(a[3]), int(b[3])) - max(int(a[1]), int(b[1])))


def _bbox_height(box: list[int]) -> int:
    if len(box) < 4:
        return 0
    return max(0, int(box[3]) - int(box[1]))


def _overlaps_external_section(node: SemanticNodeV03, nodes: list[SemanticNodeV03]) -> bool:
    """Catch question bboxes that swallow the next section or knowledge block."""
    section_fragments = []
    for other in nodes:
        if other.node_id == node.node_id:
            continue
        for fragment in other.fragments:
            flags = set(getattr(fragment, "flags", []) or [])
            if (
                fragment.role == "section_heading"
                or other.node_type == "knowledge_block"
                or "possible_section_heading" in flags
                or "knowledge_like" in flags
            ):
                section_fragments.append(fragment)

    for question_fragment in node.fragments:
        if question_fragment.role not in {"question_body", "body_continuation"}:
            continue
        qbox = question_fragment.bbox_px
        if len(qbox) < 4:
            continue
        for section_fragment in section_fragments:
            if section_fragment.page != question_fragment.page:
                continue
            sbox = section_fragment.bbox_px
            if len(sbox) < 4:
                continue
            # Section headings above a question are allowed. We only reject a
            # following section whose top edge has been swallowed by a question.
            section_starts_inside = int(qbox[1]) <= int(sbox[1]) < int(qbox[3])
            if not section_starts_inside:
                continue
            overlap_y = _bbox_overlap_y(qbox, sbox)
            if overlap_y >= 24 or overlap_y >= _bbox_height(sbox) * 0.15:
                return True
    return False


def _too_short_without_solution_evidence(node: SemanticNodeV03) -> bool:
    roles = [fragment.role for fragment in node.fragments]
    if roles != ["question_body"]:
        return False
    flags = {flag for fragment in node.fragments for flag in getattr(fragment, "flags", [])}
    if {"answer_like", "analysis_like", "continues_previous_page", "page_top_continuation", "near_page_bottom"} & flags:
        return False
    if not node.fragments:
        return False
    return _bbox_height(node.fragments[0].bbox_px) < 360


def _has_large_section_attached_to_question(node: SemanticNodeV03) -> bool:
    roles = [fragment.role for fragment in node.fragments]
    if "section_heading" not in roles or "question_body" not in roles:
        return False
    question_heights = [_bbox_height(fragment.bbox_px) for fragment in node.fragments if fragment.role == "question_body"]
    max_question_height = max(question_heights) if question_heights else 0
    for fragment in node.fragments:
        if fragment.role != "section_heading":
            continue
        section_height = _bbox_height(fragment.bbox_px)
        if section_height < 360:
            continue
        # Small visual labels such as 能力进阶/强化训练 are allowed to travel
        # with the first question. Large teaching panels are not question stems.
        if section_height >= 900 or (max_question_height > 0 and section_height > max_question_height * 1.2):
            return True
    return False


def _has_continuation_evidence(node: SemanticNodeV03) -> bool:
    pages = {int(fragment.page) for fragment in node.fragments}
    if len(pages) < 2:
        return False
    for fragment in node.fragments:
        flags = set(getattr(fragment, "flags", []) or [])
        if "continues_previous_page" in flags or "page_top_continuation" in flags:
            return True
        if fragment.role in {"body_continuation", "answer_block", "analysis_block", "translation_block", "solution_block"}:
            return True
    return False


def _looks_like_mixed_numbered_stub(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2 or len(lines) > 6:
        return False
    first_numbers = []
    for line in lines:
        match = re.search(r"(?:^|[^\d])(\d{1,2})(?:[.)、]|[^\d])", line)
        if match:
            first_numbers.append(int(match.group(1)))
    return 1 in first_numbers and 2 in first_numbers


def audit_nodes_v03(nodes: list[SemanticNodeV03]) -> list[AuditRecordV03]:
    records: list[AuditRecordV03] = []
    for node in nodes:
        reasons: list[str] = []
        roles = [fragment.role for fragment in node.fragments]
        fragment_flags = {flag for fragment in node.fragments for flag in getattr(fragment, "flags", [])}
        if "visual_coverage_incomplete" in fragment_flags:
            reasons.append("visual_coverage_incomplete")
        if "mixed_boundary_requires_secondary_split" in fragment_flags:
            reasons.append("mixed_boundary_requires_secondary_split")
        if (
            "near_page_bottom" in fragment_flags
            and "continues_previous_page" not in fragment_flags
            and "cross_page_checked_no_continuation" not in fragment_flags
            and not _has_continuation_evidence(node)
        ):
            reasons.append("page_bottom_may_continue")
        if node.node_type == "quarantined_orphan":
            reasons.append("orphan_unresolved")
        if node.node_type == "question":
            if "question_body" not in roles:
                reasons.append("missing_stem")
            if roles and all(role in {"answer_block", "analysis_block", "solution_block", "translation_block"} for role in roles):
                reasons.append("only_solution_without_question")
            if "section_heading" in roles and "question_body" not in roles:
                reasons.append("section_heading_as_question")
            if _has_large_section_attached_to_question(node):
                reasons.append("large_section_attached_to_question")
            if len(node.text_stub) < 8:
                reasons.append("too_small")
            if len(node.text_stub) > 5000:
                reasons.append("too_tall")
            if (
                node.text_stub.count("銆愮粌") > 1
                or node.text_stub.count("銆愪緥") > 2
                or _looks_like_mixed_numbered_stub(node.text_stub)
            ):
                reasons.append("mixed_next_node")
            if _overlaps_external_section(node, nodes):
                reasons.append("swallows_next_section")
            if _too_short_without_solution_evidence(node):
                reasons.append("short_question_without_solution_evidence")
        status = "AUDITED_READY" if not reasons and node.node_type == "question" else ("QUARANTINED" if "orphan_unresolved" in reasons else "NEEDS_REVIEW")
        node.review_status = status
        records.append(AuditRecordV03(node.node_id, status, reasons))
    return records


def write_audit_report(path: Path, records: list[AuditRecordV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "audit_report_v0.3", "records": [asdict(r) for r in records]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
