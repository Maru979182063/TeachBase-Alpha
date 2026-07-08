from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.cross_page_node_accumulator_v03 import SemanticNodeV03


@dataclass
class AuditRecordV03:
    node_id: str
    status: str
    reasons: list[str] = field(default_factory=list)


def audit_nodes_v03(nodes: list[SemanticNodeV03]) -> list[AuditRecordV03]:
    records: list[AuditRecordV03] = []
    for node in nodes:
        reasons: list[str] = []
        roles = [fragment.role for fragment in node.fragments]
        fragment_flags = {flag for fragment in node.fragments for flag in getattr(fragment, "flags", [])}
        if "visual_coverage_incomplete" in fragment_flags:
            reasons.append("visual_coverage_incomplete")
        if "near_page_bottom" in fragment_flags and "continues_previous_page" not in fragment_flags:
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
            if len(node.text_stub) < 8:
                reasons.append("too_small")
            if len(node.text_stub) > 5000:
                reasons.append("too_tall")
            if node.text_stub.count("【练") > 1 or node.text_stub.count("【例") > 2:
                reasons.append("mixed_next_node")
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
