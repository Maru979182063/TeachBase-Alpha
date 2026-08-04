from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from english_text_first_normalizer.text_health import detect_mojibake


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_UNIT_TYPES = {
    "content_unit",
    "question_like_unit",
    "solution_unit",
    "analysis_unit",
    "translation_unit",
    "visual_unit",
    "writing_surface",
    "unknown_unit",
}
ALLOWED_TEXT_MODES = {"exact_copy", "summary_for_locator", "visual_reference_only"}
ALLOWED_UNIT_COMPLETION = {"complete", "continues_from_previous", "continues_to_next", "fragment", "unknown"}
ALLOWED_DRAFT_COMPLETION = {"complete", "missing_solution", "missing_context", "continues_to_next", "fragment", "unknown"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_CONTINUATION_DIRECTIONS = {"from_previous", "to_next"}
ALLOWED_QA_SEVERITY = {"warning", "error"}
ALLOWED_GROUP_OPEN_STATUS = {"closed", "open_from_previous", "open_to_next", "open_both", "fragment", "unknown"}


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


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_template(text: str, values: dict[str, Any]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def build_retry_prompt(user_prompt: str, validation: dict[str, Any], parse_error: str) -> str:
    retry_payload = {
        "parse_error": parse_error,
        "validation_errors": validation.get("errors", [])[:12],
        "validation_warnings": validation.get("warnings", [])[:12],
    }
    return (
        user_prompt
        + "\n\n"
        + "RETRY INSTRUCTION:\n"
        + "Your previous response failed JSON parsing or local contract validation.\n"
        + "Return the same JSON contract again, but make it strictly valid and compact.\n"
        + "Do not copy long source text. Use source_block_refs and short locator text only.\n"
        + "All ref fields except stem_unit_ref must be arrays. stem_unit_ref must be exactly one unit id.\n"
        + "Every composed unit must have at least one real source_block_refs value.\n"
        + "Do not invent visual or writing surface units without source refs.\n"
        + "Local failure report:\n"
        + json.dumps(retry_payload, ensure_ascii=False, indent=2)
    )


def make_fallback_output(*, doc_id: str, page: int, window_id: str, prompt_version: str, window: dict[str, Any], reason: str) -> dict[str, Any]:
    member_refs = [
        block["block_ref"]
        for group_key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks")
        for block in window[group_key]
    ]
    current_refs = [block["block_ref"] for block in window["current_page_blocks"]]
    return {
        "schema": "sliding_window_groups_v0.1",
        "doc_id": doc_id,
        "current_page": page,
        "window_id": window_id,
        "prompt_version": prompt_version,
        "groups": [
            {
                "group_id": f"fallback_{doc_id}_p{page:03d}_001",
                "group_kind": "unresolved_candidate_window",
                "anchor_block_refs": current_refs[:1],
                "member_block_refs": member_refs,
                "context_block_refs": [],
                "solution_block_refs": [],
                "analysis_block_refs": [],
                "translation_block_refs": [],
                "visual_block_refs": [],
                "carryover_block_refs": [ref for ref in member_refs if ref not in current_refs],
                "open_status": "unknown",
                "confidence": "low",
                "fallback_reason": reason,
            }
        ],
        "open_continuations": [],
        "dedupe_hints": [],
        "qa_flags": [
            {
                "code": "composer_fallback_unresolved",
                "severity": "warning",
                "message": reason,
                "source_block_refs": member_refs,
            }
        ],
    }


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


def selected_pages(values: list[str]) -> list[tuple[str, int]]:
    pairs = []
    for value in values:
        if ":" not in value:
            raise SystemExit(f"page selector must be doc_id:page_number, got {value}")
        doc_id, page_raw = value.split(":", 1)
        pairs.append((doc_id, int(page_raw)))
    return pairs


def verify_summary_record(run_dir: Path, record: dict[str, Any], index: int) -> None:
    artifact_ref = (record.get("artifact_paths") or {}).get("parsed_output") or record.get("artifact_path")
    if artifact_ref:
        artifact_path = workspace_path(artifact_ref)
        if not artifact_path.exists():
            raise SystemExit(f"Node2 preflight failed: summary record {index} artifact missing: {artifact_ref}")
        artifact_payload = read_json(artifact_path)
        if canonical_json(record.get("parsed_output")) != canonical_json(artifact_payload):
            raise SystemExit(
                "Node2 preflight failed: summary parsed_output differs from page artifact "
                f"for {record.get('doc_id')}:{record.get('page_number')} ({rel_workspace(artifact_path)})"
            )
    health = detect_mojibake(record.get("parsed_output"))
    if health["mojibake_suspected"]:
        raise SystemExit(
            "Node2 preflight failed: summary parsed_output contains mojibake markers "
            f"for {record.get('doc_id')}:{record.get('page_number')} "
            f"{json.dumps(health['signals'][:3], ensure_ascii=False)}"
        )


def load_doc_records(run_dir: Path) -> dict[int, dict[str, Any]]:
    summary = read_json(run_dir / "run_summary.json")
    records = summary.get("records")
    if not isinstance(records, list):
        raise SystemExit(f"Node2 preflight failed: {run_dir / 'run_summary.json'} has no records array")
    page_records: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(records):
        verify_summary_record(run_dir, record, index)
        page_number = int(record["page_number"])
        if page_number in page_records:
            raise SystemExit(f"Node2 preflight failed: duplicate page record {record.get('doc_id')}:{page_number}")
        page_records[page_number] = record
    return page_records


def tagged_blocks_for_page(doc_id: str, page: int, node1a_record: dict[str, Any], node1b_record: dict[str, Any]) -> list[dict[str, Any]]:
    tags = {tag["block_id"]: tag for tag in node1b_record["parsed_output"].get("tags", [])}
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(node1a_record["parsed_output"].get("blocks", []), start=1):
        tag = tags.get(block.get("block_id"), {})
        if block.get("label") == "header_footer" and tag.get("content_role") == "navigation" and tag.get("confidence") == "high":
            continue
        block_ref = f"{doc_id}_p{page:03d}_{block.get('block_id')}"
        blocks.append(
            {
                "block_ref": block_ref,
                "doc_id": doc_id,
                "page": page,
                "page_local_index": index,
                "block_id": block.get("block_id"),
                "node1a_label": block.get("label"),
                "text": block.get("text", ""),
                "bbox_hint": block.get("bbox_hint", ""),
                "is_complete": block.get("is_complete"),
                "visual_form": tag.get("visual_form"),
                "content_role": tag.get("content_role"),
                "relation_hint": tag.get("relation_hint"),
                "composition_relevance": tag.get("composition_relevance", "unknown"),
                "relevance_confidence": tag.get("relevance_confidence", "unknown"),
                "requires_visual_preservation": tag.get("requires_visual_preservation"),
                "preservation_reason": tag.get("preservation_reason"),
                "tag_confidence": tag.get("confidence"),
            }
        )
    return blocks


def composition_candidate_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in blocks
        if block.get("composition_relevance") in {"main_candidate", "context_candidate", "unknown"}
    ]


def evidence_only_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in blocks
        if block.get("composition_relevance") == "evidence_only"
    ]


def choose_window_policy(node: dict[str, Any], current_record: dict[str, Any]) -> dict[str, Any]:
    policy = node.get("window_policy", {})
    page_start = current_record["parsed_output"].get("page_start", {})
    page_end = current_record["parsed_output"].get("page_end", {})
    previous = int(policy.get("default_previous_tail_blocks", 8))
    next_ = int(policy.get("default_next_head_blocks", 6))
    reason = ["default"]
    if not page_start.get("continues_previous") and not page_end.get("tail_cutoff"):
        previous = int(policy.get("quiet_page_previous_tail_blocks", 4))
        next_ = int(policy.get("quiet_page_next_head_blocks", 4))
        reason = ["quiet_page"]
    if page_start.get("continues_previous"):
        previous = int(policy.get("continuation_previous_tail_blocks", 10))
        reason.append("continues_previous")
    if page_end.get("tail_cutoff"):
        next_ = int(policy.get("continuation_next_head_blocks", 10))
        reason.append("tail_cutoff")
    if page_end.get("open_tail_type") not in {None, "", "none"}:
        previous = max(previous, int(policy.get("continuation_previous_tail_blocks", 10)))
        next_ = max(next_, int(policy.get("continuation_next_head_blocks", 10)))
        reason.append(f"open_tail_type={page_end.get('open_tail_type')}")
    return {
        "previous_tail_count": previous,
        "next_head_count": next_,
        "max_window_blocks": int(policy.get("max_window_blocks", 48)),
        "reason": reason,
    }


def trim_window(previous: list[dict[str, Any]], current: list[dict[str, Any]], next_: list[dict[str, Any]], max_blocks: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    while len(previous) + len(current) + len(next_) > max_blocks and len(previous) > 2:
        previous = previous[1:]
    while len(previous) + len(current) + len(next_) > max_blocks and len(next_) > 2:
        next_ = next_[:-1]
    return previous, current, next_


def build_window(doc_id: str, page: int, node: dict[str, Any], node1a_records: dict[int, dict[str, Any]], node1b_records: dict[int, dict[str, Any]]) -> dict[str, Any]:
    current_record = node1a_records[page]
    policy = choose_window_policy(node, current_record)
    previous_blocks: list[dict[str, Any]] = []
    next_blocks: list[dict[str, Any]] = []
    current_all = tagged_blocks_for_page(doc_id, page, current_record, node1b_records[page])
    current_blocks = composition_candidate_blocks(current_all)
    excluded_evidence = {
        "current_page": evidence_only_blocks(current_all),
        "previous_page": [],
        "next_page": [],
    }
    if page - 1 in node1a_records and page - 1 in node1b_records:
        previous_all = tagged_blocks_for_page(doc_id, page - 1, node1a_records[page - 1], node1b_records[page - 1])
        excluded_evidence["previous_page"] = evidence_only_blocks(previous_all)
        previous_blocks = composition_candidate_blocks(previous_all)[-policy["previous_tail_count"] :]
    if page + 1 in node1a_records and page + 1 in node1b_records:
        next_all = tagged_blocks_for_page(doc_id, page + 1, node1a_records[page + 1], node1b_records[page + 1])
        excluded_evidence["next_page"] = evidence_only_blocks(next_all)
        next_blocks = composition_candidate_blocks(next_all)[: policy["next_head_count"]]
    previous_blocks, current_blocks, next_blocks = trim_window(previous_blocks, current_blocks, next_blocks, policy["max_window_blocks"])
    return {
        "window_id": f"{doc_id}_p{page:03d}_sliding_v01",
        "doc_id": doc_id,
        "current_page": page,
        "window_policy": policy,
        "page_boundary": {
            "current_page_start": current_record["parsed_output"].get("page_start", {}),
            "current_page_end": current_record["parsed_output"].get("page_end", {}),
            "current_page_visual_flags": current_record["parsed_output"].get("page_visual_flags", {}),
        },
        "previous_tail_blocks": previous_blocks,
        "current_page_blocks": current_blocks,
        "next_head_blocks": next_blocks,
        "excluded_evidence_only_blocks": excluded_evidence,
    }


def call_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_output(payload: dict[str, Any], *, doc_id: str, page: int, prompt_version: str, valid_block_refs: set[str]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def require_array(obj: dict[str, Any], key: str, path: str) -> list[Any]:
        value = obj.get(key)
        if not isinstance(value, list):
            errors.append({"path": f"{path}.{key}", "message": "must be array"})
            return []
        return value

    def require_string(obj: dict[str, Any], key: str, path: str, *, non_empty: bool = False) -> str:
        value = obj.get(key)
        if not isinstance(value, str):
            errors.append({"path": f"{path}.{key}", "message": "must be string"})
            return ""
        if non_empty and not value.strip():
            errors.append({"path": f"{path}.{key}", "message": "must be non-empty string"})
        return value

    def require_enum(obj: dict[str, Any], key: str, allowed: set[str], path: str) -> str:
        value = require_string(obj, key, path)
        if value and value not in allowed:
            errors.append({"path": f"{path}.{key}", "message": f"invalid value {value!r}; allowed={sorted(allowed)}"})
        return value

    def validate_block_refs(refs: Any, path: str, *, required: bool = False) -> list[str]:
        if not isinstance(refs, list):
            errors.append({"path": path, "message": "must be array"})
            return []
        if required and not refs:
            errors.append({"path": path, "message": "must be non-empty array"})
        valid_refs: list[str] = []
        for ref_index, ref in enumerate(refs):
            if not isinstance(ref, str) or not ref:
                errors.append({"path": f"{path}[{ref_index}]", "message": "must be non-empty string"})
                continue
            valid_refs.append(ref)
            if ref not in valid_block_refs:
                errors.append({"path": f"{path}[{ref_index}]", "message": f"unknown block ref {ref}"})
        return valid_refs

    def validate_unit_refs(refs: Any, path: str, unit_ids: set[str], *, required: bool = False) -> list[str]:
        if not isinstance(refs, list):
            errors.append({"path": path, "message": "must be array"})
            return []
        if required and not refs:
            errors.append({"path": path, "message": "must be non-empty array"})
        valid_refs: list[str] = []
        for ref_index, ref in enumerate(refs):
            if not isinstance(ref, str) or not ref:
                errors.append({"path": f"{path}[{ref_index}]", "message": "must be non-empty string"})
                continue
            valid_refs.append(ref)
            if ref not in unit_ids:
                errors.append({"path": f"{path}[{ref_index}]", "message": f"unknown unit ref {ref}"})
        return valid_refs

    if payload.get("schema") != "sliding_window_composition_v0.1":
        errors.append({"path": "$.schema", "message": "schema must be sliding_window_composition_v0.1"})
    if payload.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if payload.get("current_page") != page:
        errors.append({"path": "$.current_page", "message": "current_page mismatch"})
    if payload.get("prompt_version") != prompt_version:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})
    for key in ("composed_units", "draft_packets", "open_continuations", "dedupe_hints", "qa_flags"):
        if not isinstance(payload.get(key), list):
            errors.append({"path": f"$.{key}", "message": "must be array"})

    composed_units = payload.get("composed_units", []) if isinstance(payload.get("composed_units"), list) else []
    unit_ids: set[str] = set()
    unit_types: dict[str, str] = {}
    unit_source_refs: dict[str, list[str]] = {}
    for unit_index, unit in enumerate(composed_units):
        path = f"$.composed_units[{unit_index}]"
        if not isinstance(unit, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        unit_id = require_string(unit, "unit_id", path, non_empty=True)
        if unit_id:
            if unit_id in unit_ids:
                errors.append({"path": f"{path}.unit_id", "message": f"duplicate unit_id {unit_id}"})
            unit_ids.add(unit_id)
        unit_type = require_enum(unit, "unit_type", ALLOWED_UNIT_TYPES, path)
        if unit_id:
            unit_types[unit_id] = unit_type
        require_string(unit, "open_kind", path)
        require_string(unit, "title", path)
        refs = validate_block_refs(unit.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        if unit_id:
            unit_source_refs[unit_id] = refs
        if not isinstance(unit.get("primary_page"), int) or int(unit.get("primary_page", 0)) < 1:
            errors.append({"path": f"{path}.primary_page", "message": "must be integer >= 1"})
        require_enum(unit, "text_mode", ALLOWED_TEXT_MODES, path)
        text = require_string(unit, "text", path)
        if len(text) > 240:
            warnings.append({"path": f"{path}.text", "message": "text is longer than compact-output target of 240 characters"})
        if not isinstance(unit.get("contains_visual_requirement"), bool):
            errors.append({"path": f"{path}.contains_visual_requirement", "message": "must be boolean"})
        require_enum(unit, "completion_status", ALLOWED_UNIT_COMPLETION, path)
        require_enum(unit, "confidence", ALLOWED_CONFIDENCE, path)

    draft_packets = payload.get("draft_packets", []) if isinstance(payload.get("draft_packets"), list) else []
    for draft_index, draft in enumerate(draft_packets):
        path = f"$.draft_packets[{draft_index}]"
        if not isinstance(draft, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(draft, "draft_id", path, non_empty=True)
        require_string(draft, "draft_type", path)
        source_unit_refs = validate_unit_refs(draft.get("source_unit_refs"), f"{path}.source_unit_refs", unit_ids, required=True)
        validate_block_refs(draft.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        for key in ("context_unit_refs", "option_unit_refs", "solution_unit_refs", "analysis_unit_refs", "translation_unit_refs", "visual_unit_refs"):
            validate_unit_refs(draft.get(key), f"{path}.{key}", unit_ids)
        stem_unit_ref = require_string(draft, "stem_unit_ref", path, non_empty=True)
        if stem_unit_ref:
            if stem_unit_ref not in unit_ids:
                errors.append({"path": f"{path}.stem_unit_ref", "message": f"unknown unit ref {stem_unit_ref}"})
            elif unit_types.get(stem_unit_ref) in {"solution_unit", "analysis_unit", "translation_unit"}:
                errors.append({"path": f"{path}.stem_unit_ref", "message": f"stem_unit_ref cannot point to {unit_types.get(stem_unit_ref)}"})
            if stem_unit_ref not in source_unit_refs:
                warnings.append({"path": f"{path}.stem_unit_ref", "message": "stem_unit_ref is not included in source_unit_refs"})
        for key in ("solution_unit_refs", "analysis_unit_refs", "translation_unit_refs", "visual_unit_refs"):
            refs = draft.get(key)
            if isinstance(refs, list) and stem_unit_ref in refs:
                errors.append({"path": f"{path}.{key}", "message": "must not contain stem_unit_ref"})
        require_enum(draft, "completion_status", ALLOWED_DRAFT_COMPLETION, path)
        require_enum(draft, "confidence", ALLOWED_CONFIDENCE, path)

    for cont_index, cont in enumerate(payload.get("open_continuations", []) if isinstance(payload.get("open_continuations"), list) else []):
        path = f"$.open_continuations[{cont_index}]"
        if not isinstance(cont, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(cont, "continuation_id", path, non_empty=True)
        require_enum(cont, "direction", ALLOWED_CONTINUATION_DIRECTIONS, path)
        require_string(cont, "reason", path)
        validate_block_refs(cont.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        require_string(cont, "expected_next", path)

    for hint_index, hint in enumerate(payload.get("dedupe_hints", []) if isinstance(payload.get("dedupe_hints"), list) else []):
        path = f"$.dedupe_hints[{hint_index}]"
        if not isinstance(hint, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(hint, "candidate_id", path)
        validate_block_refs(hint.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        if not isinstance(hint.get("prefer_if_duplicate"), bool):
            errors.append({"path": f"{path}.prefer_if_duplicate", "message": "must be boolean"})
        require_string(hint, "reason", path)

    for flag_index, flag in enumerate(payload.get("qa_flags", []) if isinstance(payload.get("qa_flags"), list) else []):
        path = f"$.qa_flags[{flag_index}]"
        if not isinstance(flag, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(flag, "code", path)
        require_enum(flag, "severity", ALLOWED_QA_SEVERITY, path)
        require_string(flag, "message", path)
        validate_block_refs(flag.get("source_block_refs"), f"{path}.source_block_refs")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def validate_group_output(payload: dict[str, Any], *, doc_id: str, page: int, prompt_version: str, valid_block_refs: set[str]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def require_string(obj: dict[str, Any], key: str, path: str, *, non_empty: bool = False) -> str:
        value = obj.get(key)
        if not isinstance(value, str):
            errors.append({"path": f"{path}.{key}", "message": "must be string"})
            return ""
        if non_empty and not value.strip():
            errors.append({"path": f"{path}.{key}", "message": "must be non-empty string"})
        return value

    def require_enum(obj: dict[str, Any], key: str, allowed: set[str], path: str) -> str:
        value = require_string(obj, key, path)
        if value and value not in allowed:
            errors.append({"path": f"{path}.{key}", "message": f"invalid value {value!r}; allowed={sorted(allowed)}"})
        return value

    def validate_block_refs(refs: Any, path: str, *, required: bool = False) -> list[str]:
        if not isinstance(refs, list):
            errors.append({"path": path, "message": "must be array"})
            return []
        if required and not refs:
            errors.append({"path": path, "message": "must be non-empty array"})
        out: list[str] = []
        for index, ref in enumerate(refs):
            if not isinstance(ref, str) or not ref:
                errors.append({"path": f"{path}[{index}]", "message": "must be non-empty string"})
                continue
            out.append(ref)
            if ref not in valid_block_refs:
                errors.append({"path": f"{path}[{index}]", "message": f"unknown block ref {ref}"})
        return out

    if payload.get("schema") != "sliding_window_groups_v0.1":
        errors.append({"path": "$.schema", "message": "schema must be sliding_window_groups_v0.1"})
    if payload.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if payload.get("current_page") != page:
        errors.append({"path": "$.current_page", "message": "current_page mismatch"})
    if payload.get("window_id") != f"{doc_id}_p{page:03d}_sliding_v01":
        errors.append({"path": "$.window_id", "message": "window_id mismatch"})
    if payload.get("prompt_version") != prompt_version:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})
    for key in ("groups", "open_continuations", "dedupe_hints", "qa_flags"):
        if not isinstance(payload.get(key), list):
            errors.append({"path": f"$.{key}", "message": "must be array"})

    group_ids: set[str] = set()
    for group_index, group in enumerate(payload.get("groups", []) if isinstance(payload.get("groups"), list) else []):
        path = f"$.groups[{group_index}]"
        if not isinstance(group, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        group_id = require_string(group, "group_id", path, non_empty=True)
        if group_id in group_ids:
            errors.append({"path": f"{path}.group_id", "message": f"duplicate group_id {group_id}"})
        group_ids.add(group_id)
        require_string(group, "group_kind", path, non_empty=True)
        member_refs = validate_block_refs(group.get("member_block_refs"), f"{path}.member_block_refs", required=True)
        ref_keys = (
            "anchor_block_refs",
            "context_block_refs",
            "solution_block_refs",
            "analysis_block_refs",
            "translation_block_refs",
            "visual_block_refs",
            "carryover_block_refs",
        )
        for key in ref_keys:
            refs = validate_block_refs(group.get(key), f"{path}.{key}")
            extra = [ref for ref in refs if ref not in member_refs]
            if key != "carryover_block_refs" and extra:
                warnings.append({"path": f"{path}.{key}", "message": f"refs not included in member_block_refs: {extra}"})
        require_enum(group, "open_status", ALLOWED_GROUP_OPEN_STATUS, path)
        require_enum(group, "confidence", ALLOWED_CONFIDENCE, path)

    for cont_index, cont in enumerate(payload.get("open_continuations", []) if isinstance(payload.get("open_continuations"), list) else []):
        path = f"$.open_continuations[{cont_index}]"
        if not isinstance(cont, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(cont, "continuation_id", path, non_empty=True)
        require_enum(cont, "direction", ALLOWED_CONTINUATION_DIRECTIONS, path)
        require_string(cont, "reason", path)
        validate_block_refs(cont.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        require_string(cont, "expected_next", path)

    for hint_index, hint in enumerate(payload.get("dedupe_hints", []) if isinstance(payload.get("dedupe_hints"), list) else []):
        path = f"$.dedupe_hints[{hint_index}]"
        if not isinstance(hint, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(hint, "candidate_id", path)
        validate_block_refs(hint.get("source_block_refs"), f"{path}.source_block_refs", required=True)
        if not isinstance(hint.get("prefer_if_duplicate"), bool):
            errors.append({"path": f"{path}.prefer_if_duplicate", "message": "must be boolean"})
        require_string(hint, "reason", path)

    for flag_index, flag in enumerate(payload.get("qa_flags", []) if isinstance(payload.get("qa_flags"), list) else []):
        path = f"$.qa_flags[{flag_index}]"
        if not isinstance(flag, dict):
            errors.append({"path": path, "message": "must be object"})
            continue
        require_string(flag, "code", path)
        require_enum(flag, "severity", ALLOWED_QA_SEVERITY, path)
        require_string(flag, "message", path)
        validate_block_refs(flag.get("source_block_refs"), f"{path}.source_block_refs")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def render_review(out_dir: Path, records: list[dict[str, Any]]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Group Composer Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;line-height:1.45}.page{border:1px solid #ddd;margin:18px 0;padding:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.mono{font-family:Consolas,monospace;white-space:pre-wrap}.ok{background:#eef9f0}.bad{background:#fff0f0}.tag{background:#eef;padding:2px 5px;border-radius:4px;font-family:Consolas,monospace}.block{border-bottom:1px solid #eee;padding:6px 0}</style>",
        "<h1>Node2 GroupComposer Review</h1>",
    ]
    for record in records:
        css = "ok" if record["validation"]["valid"] else "bad"
        parts.append(f"<div class='page {css}'>")
        parts.append(f"<h2>{html.escape(record['window']['window_id'])} valid={record['validation']['valid']} fallback={record.get('used_fallback', False)}</h2>")
        parts.append("<div class='grid'><div>")
        parts.append("<h3>Window Blocks</h3>")
        for group_key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks"):
            parts.append(f"<h4>{group_key}</h4>")
            for block in record["window"][group_key]:
                parts.append("<div class='block'>")
                parts.append(f"<div><span class='tag'>{html.escape(block['block_ref'])}</span> <span class='tag'>{html.escape(str(block.get('content_role')))}</span> <span class='tag'>{html.escape(str(block.get('node1a_label')))}</span></div>")
                parts.append(f"<pre class='mono'>{html.escape(str(block.get('text', ''))[:1200])}</pre>")
                parts.append("</div>")
        parts.append("</div><div>")
        parts.append("<h3>Validation</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(record['validation'], ensure_ascii=False, indent=2))}</pre>")
        parts.append("<h3>Group Output</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(record.get('parsed_output'), ensure_ascii=False, indent=2))}</pre>")
        parts.append("</div></div></div>")
    write_text(out_dir / "review.html", "\n".join(parts))


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = workspace_path(args.config)
    config = read_json(config_path)
    node = config["nodes"]["node2_sliding_window_composer"]
    out_root = workspace_path(args.out or config["owned_output_root"])
    run_id = args.run_id or f"node2_sliding_composer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    node1a_runs = {item.split("=", 1)[0]: workspace_path(item.split("=", 1)[1]) for item in args.node1a_run}
    node1b_runs = {item.split("=", 1)[0]: workspace_path(item.split("=", 1)[1]) for item in args.node1b_run}
    if args.preflight_only:
        cache: dict[str, tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]] = {}
        window_count = 0
        for doc_id, page in selected_pages(args.pages):
            if doc_id not in cache:
                cache[doc_id] = (load_doc_records(node1a_runs[doc_id]), load_doc_records(node1b_runs[doc_id]))
            node1a_records, node1b_records = cache[doc_id]
            build_window(doc_id, page, node, node1a_records, node1b_records)
            window_count += 1
        summary = {
            "schema": "english_text_first_sliding_window_composer.preflight_summary",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "node": "node2_sliding_window_composer",
            "preflight_only": True,
            "window_count": window_count,
            "node1a_runs": {doc_id: rel_workspace(path) for doc_id, path in node1a_runs.items()},
            "node1b_runs": {doc_id: rel_workspace(path) for doc_id, path in node1b_runs.items()},
        }
        write_json(out_dir / "preflight_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return summary

    api_key = str(os.environ.get(config["api_key_env"], "") or "").strip()
    if not api_key:
        raise SystemExit(f"missing api key env {config['api_key_env']}")

    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    write_text(out_dir / "used_system_prompt.md", system_prompt)
    write_text(out_dir / "used_user_prompt_template.md", user_template)
    write_json(out_dir / "used_config.json", config)

    records: list[dict[str, Any]] = []
    cache: dict[str, tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]] = {}
    for doc_id, page in selected_pages(args.pages):
        if doc_id not in cache:
            cache[doc_id] = (load_doc_records(node1a_runs[doc_id]), load_doc_records(node1b_runs[doc_id]))
        node1a_records, node1b_records = cache[doc_id]
        window = build_window(doc_id, page, node, node1a_records, node1b_records)
        page_dir = out_dir / doc_id / f"page_{page:03d}"
        valid_refs = {
            block["block_ref"]
            for group_key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks")
            for block in window[group_key]
        }
        user_prompt = render_template(
            user_template,
            {
                "doc_id": doc_id,
                "page_number": page,
                "window_id": window["window_id"],
                "prompt_version": node["prompt_version"],
                "window_policy_json": json.dumps(window["window_policy"], ensure_ascii=False, indent=2),
                "page_boundary_json": json.dumps(window["page_boundary"], ensure_ascii=False, indent=2),
                "window_blocks_json": json.dumps(
                    {
                        "previous_tail_blocks": window["previous_tail_blocks"],
                        "current_page_blocks": window["current_page_blocks"],
                        "next_head_blocks": window["next_head_blocks"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        )
        write_json(page_dir / "window_input.json", window)
        write_text(page_dir / "system_prompt.md", system_prompt)
        write_text(page_dir / "user_prompt.md", user_prompt)
        model_result = call_model(config, node, system_prompt, user_prompt, api_key)
        write_json(page_dir / "request_messages.full.local.json", model_result["request_body"])
        write_json(page_dir / "raw_response.json", model_result["raw_response"])
        write_text(page_dir / "raw_content.txt", model_result["raw_content"])
        parsed = model_result["parsed"] or {}
        validation = (
            validate_group_output(parsed, doc_id=doc_id, page=page, prompt_version=node["prompt_version"], valid_block_refs=valid_refs)
            if parsed
            else {"valid": False, "errors": [{"message": model_result["parse_error"]}], "warnings": []}
        )
        attempts = [
            {
                "attempt": 1,
                "parsed": bool(model_result["parsed"]),
                "parse_error": model_result["parse_error"],
                "validation": validation,
                "latency_seconds": model_result["latency_seconds"],
                "usage": model_result["raw_response"].get("usage", {}),
                "finish_reason": (model_result["raw_response"].get("choices") or [{}])[0].get("finish_reason"),
            }
        ]
        retry_enabled = bool(node.get("retry_on_invalid", True))
        if retry_enabled and not validation["valid"]:
            retry_prompt = build_retry_prompt(user_prompt, validation, model_result["parse_error"])
            write_text(page_dir / "retry_user_prompt.md", retry_prompt)
            retry_result = call_model(config, node, system_prompt, retry_prompt, api_key)
            write_json(page_dir / "retry_request_messages.full.local.json", retry_result["request_body"])
            write_json(page_dir / "retry_raw_response.json", retry_result["raw_response"])
            write_text(page_dir / "retry_raw_content.txt", retry_result["raw_content"])
            retry_parsed = retry_result["parsed"] or {}
            retry_validation = (
                validate_group_output(retry_parsed, doc_id=doc_id, page=page, prompt_version=node["prompt_version"], valid_block_refs=valid_refs)
                if retry_parsed
                else {"valid": False, "errors": [{"message": retry_result["parse_error"]}], "warnings": []}
            )
            attempts.append(
                {
                    "attempt": 2,
                    "parsed": bool(retry_result["parsed"]),
                    "parse_error": retry_result["parse_error"],
                    "validation": retry_validation,
                    "latency_seconds": retry_result["latency_seconds"],
                    "usage": retry_result["raw_response"].get("usage", {}),
                    "finish_reason": (retry_result["raw_response"].get("choices") or [{}])[0].get("finish_reason"),
                }
            )
            if retry_validation["valid"] or not model_result["parsed"]:
                model_result = retry_result
                parsed = retry_parsed
                validation = retry_validation
        composer_parsed = parsed
        composer_validation = validation
        used_fallback = False
        write_json(page_dir / "composer_model_output.json", composer_parsed)
        write_json(page_dir / "composer_validation_report.json", composer_validation)
        if not validation["valid"]:
            fallback_reason = "composer_parse_or_contract_failed"
            if validation.get("errors"):
                fallback_reason = str(validation["errors"][0].get("message") or validation["errors"][0])
            parsed = make_fallback_output(
                doc_id=doc_id,
                page=page,
                window_id=window["window_id"],
                prompt_version=node["prompt_version"],
                window=window,
                reason=fallback_reason,
            )
            validation = validate_group_output(parsed, doc_id=doc_id, page=page, prompt_version=node["prompt_version"], valid_block_refs=valid_refs)
            used_fallback = True
        write_json(page_dir / "sliding_window_composition.json", parsed)
        write_json(page_dir / "validation_report.json", validation)
        write_json(page_dir / "attempts.json", attempts)
        record = {
            "doc_id": doc_id,
            "page_number": page,
            "window_id": window["window_id"],
            "model": node["model"],
            "prompt_version": node["prompt_version"],
            "latency_seconds": model_result["latency_seconds"],
            "parsed": bool(model_result["parsed"]),
            "parse_error": model_result["parse_error"],
            "validation": validation,
            "composer_validation": composer_validation,
            "used_fallback": used_fallback,
            "window": window,
            "parsed_output": parsed,
            "usage": model_result["raw_response"].get("usage", {}),
            "attempts": attempts,
            "artifact_paths": {
                "window_input": rel_workspace(page_dir / "window_input.json"),
                "system_prompt": rel_workspace(page_dir / "system_prompt.md"),
                "user_prompt": rel_workspace(page_dir / "user_prompt.md"),
                "raw_response": rel_workspace(page_dir / "raw_response.json"),
                "raw_content": rel_workspace(page_dir / "raw_content.txt"),
                "parsed_output": rel_workspace(page_dir / "sliding_window_composition.json"),
                "validation_report": rel_workspace(page_dir / "validation_report.json"),
                "attempts": rel_workspace(page_dir / "attempts.json"),
                "composer_model_output": rel_workspace(page_dir / "composer_model_output.json"),
                "composer_validation_report": rel_workspace(page_dir / "composer_validation_report.json"),
            },
        }
        write_json(page_dir / "record_manifest.json", record)
        records.append(record)

    summary = {
        "schema": "english_text_first_sliding_window_composer.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": rel_workspace(config_path),
        "node": "node2_sliding_window_composer",
        "out_dir": rel_workspace(out_dir),
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "windows_attempted": len(records),
        "windows_parsed": sum(1 for record in records if record["parsed"]),
        "windows_valid": sum(1 for record in records if record["validation"]["valid"]),
        "windows_fallback": sum(1 for record in records if record.get("used_fallback")),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        "review_html": rel_workspace(out_dir / "review.html"),
    }
    write_json(out_dir / "run_summary.json", summary)
    render_review(out_dir, records)
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled Node2 sliding-window composer for tagged English handout blocks.")
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--node1a-run", nargs="+", required=True, help="doc_id=run_dir mappings")
    parser.add_argument("--node1b-run", nargs="+", required=True, help="doc_id=run_dir mappings")
    parser.add_argument("--pages", nargs="+", required=True, help="doc_id:page_number selectors")
    parser.add_argument("--out", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
