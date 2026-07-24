from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

FIELD_REF_KEYS = [
    "stem_refs",
    "option_refs",
    "passage_refs",
    "answer_refs",
    "analysis_refs",
    "translation_refs",
    "context_refs",
    "instruction_refs",
    "example_refs",
    "visual_refs",
    "writing_surface_refs",
    "rubric_refs",
    "other_evidence_refs",
]

ORDINARY_STATUS = {"present", "missing", "not_applicable", "uncertain", "partial"}
VISUAL_STATUS = {"required", "not_required", "uncertain"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def render_template(text: str, values: dict[str, Any]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = str(text or "").strip()
    try:
        return json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), ""
            except json.JSONDecodeError as nested:
                return None, str(nested)
        return None, str(exc)


def unique_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for ref in refs:
        if isinstance(ref, str) and ref and ref not in seen:
            seen.add(ref)
            result.append(ref)
    return result


def group_ref_list(group: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in [
        "anchor_block_refs",
        "member_block_refs",
        "context_block_refs",
        "solution_block_refs",
        "analysis_block_refs",
        "translation_block_refs",
        "visual_block_refs",
        "carryover_block_refs",
    ]:
        refs.extend(group.get(key) or [])
    return unique_refs(refs)


def load_block_index(node2_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    block_index: dict[str, dict[str, Any]] = {}
    for window_path in sorted((node2_run / doc_id).glob("page_*/window_input.json")):
        window = read_json(window_path)
        for key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks"):
            for block in window.get(key, []):
                block_index[block["block_ref"]] = block
    return block_index


def blocks_for_group(group: dict[str, Any], block_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []
    for ref in group_ref_list(group):
        block = dict(block_index.get(ref, {"block_ref": ref, "missing_from_node2_window": True}))
        block["text"] = str(block.get("text", ""))
        blocks.append(block)
    return sorted(
        blocks,
        key=lambda item: (
            int(item.get("page", 9999)),
            int(item.get("page_local_index", 9999)),
            item.get("block_ref", ""),
        ),
    )


def compact_group_input(doc_id: str, group: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "document_group": {
            "document_group_id": group.get("document_group_id"),
            "group_kind": group.get("group_kind", ""),
            "open_status": group.get("open_status", "unknown"),
            "source_pages": group.get("source_pages", []),
            "anchor_block_refs": group.get("anchor_block_refs", []),
            "member_block_refs": group.get("member_block_refs", []),
            "context_block_refs": group.get("context_block_refs", []),
            "solution_block_refs": group.get("solution_block_refs", []),
            "analysis_block_refs": group.get("analysis_block_refs", []),
            "translation_block_refs": group.get("translation_block_refs", []),
            "visual_block_refs": group.get("visual_block_refs", []),
            "carryover_block_refs": group.get("carryover_block_refs", []),
            "dedupe_notes": group.get("dedupe_notes", []),
        },
        "blocks": [
            {
                "block_ref": block.get("block_ref"),
                "page": block.get("page"),
                "page_local_index": block.get("page_local_index"),
                "node1a_label": block.get("node1a_label"),
                "visual_form": block.get("visual_form"),
                "content_role": block.get("content_role"),
                "relation_hint": block.get("relation_hint"),
                "composition_relevance": block.get("composition_relevance"),
                "requires_visual_preservation": block.get("requires_visual_preservation"),
                "preservation_reason": block.get("preservation_reason"),
                "is_complete": block.get("is_complete"),
                "bbox_hint": block.get("bbox_hint"),
                "text": block.get("text", ""),
            }
            for block in blocks
        ],
    }

