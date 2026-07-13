from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.layout_block_extractor_v03 import BlockCandidateV03
from tools.semantic_block_assembler_v03 import BlockAssignmentV03


@dataclass
class NodeFragmentV03:
    page: int
    bbox_px: list[int]
    role: str
    block_ids: list[str]
    flags: list[str] = field(default_factory=list)


@dataclass
class SemanticNodeV03:
    node_id: str
    node_type: str
    source: str
    fragments: list[NodeFragmentV03] = field(default_factory=list)
    review_status: str = "NEEDS_REVIEW"
    text_stub: str = ""


def accumulate_nodes_v03(blocks: list[BlockCandidateV03], assignments: list[BlockAssignmentV03]) -> tuple[list[SemanticNodeV03], list[dict]]:
    block_map = {b.block_id: b for b in blocks}
    nodes: dict[str, SemanticNodeV03] = {}
    trace: list[dict] = []
    orphan_counter = 1
    for assignment in assignments:
        block = block_map.get(assignment.block_id)
        if block is None:
            continue
        if assignment.node_action == "new_node":
            node = nodes.setdefault(
                assignment.node_id,
                SemanticNodeV03(node_id=assignment.node_id, node_type=assignment.new_node_type, source="semantic_v03"),
            )
            node.fragments.append(NodeFragmentV03(block.page, block.bbox_px, assignment.role, [block.block_id], list(block.candidate_flags)))
            node.text_stub = (node.text_stub + "\n" + block.text_stub).strip()
            trace.append({"event": "new_node", "node_id": node.node_id, "block_id": block.block_id, "role": assignment.role})
        elif assignment.node_action == "attach_to_existing" and assignment.node_id in nodes:
            node = nodes[assignment.node_id]
            node.fragments.append(NodeFragmentV03(block.page, block.bbox_px, assignment.role, [block.block_id], list(block.candidate_flags)))
            node.text_stub = (node.text_stub + "\n" + block.text_stub).strip()
            trace.append({"event": "attach_to_existing", "node_id": node.node_id, "block_id": block.block_id, "role": assignment.role})
        else:
            node_id = f"quarantined_orphan_{orphan_counter:03d}"
            orphan_counter += 1
            node = SemanticNodeV03(node_id=node_id, node_type="quarantined_orphan", source="semantic_v03", review_status="QUARANTINED")
            node.fragments.append(NodeFragmentV03(block.page, block.bbox_px, assignment.role, [block.block_id], list(block.candidate_flags)))
            node.text_stub = block.text_stub
            nodes[node_id] = node
            trace.append({"event": "quarantine", "node_id": node_id, "block_id": block.block_id, "reason": assignment.reason_code})
    for node in nodes.values():
        node.fragments.sort(key=lambda fragment: (fragment.page, fragment.bbox_px[1], fragment.bbox_px[0]))
        trace.append({"event": "close_node", "node_id": node.node_id, "fragment_count": len(node.fragments)})
    return list(nodes.values()), trace


def write_nodes(path: Path, nodes: list[SemanticNodeV03]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "semantic_nodes_v0.3", "nodes": [asdict(n) for n in nodes]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_trace(path: Path, trace: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "open_node_trace_v0.3", "events": trace}, ensure_ascii=False, indent=2), encoding="utf-8")
