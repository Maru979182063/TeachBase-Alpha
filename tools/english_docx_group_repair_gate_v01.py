from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_repair_gate_v01.json"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return 10**9


def compact_text(value: str, limit: int) -> str:
    text = str(value or "").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def load_prompt(config: dict[str, Any], key: str) -> str:
    path = Path(str(config.get(key) or ""))
    if not path.is_absolute():
        path = ROOT / path
    return read_text(path)


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


def call_model(config: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": config.get("default_model_endpoint_id"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    timeout = int((config.get("runner") or {}).get("timeout_seconds") or 240)
    started = time.time()
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    raw_response = json.loads(raw)
    raw_content = str(raw_response["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(raw_content)
    return {
        "raw_response": raw_response,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
        "usage": raw_response.get("usage") or {},
    }


def load_blocks(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = read_json(path)
    raw_blocks = payload.get("blocks") if isinstance(payload, dict) else payload
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(raw_blocks or []):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or block.get("id") or f"b_{index:06d}")
        text = str(
            block.get("display_markdown")
            or block.get("markdown")
            or block.get("md")
            or block.get("plain_text_lossy")
            or block.get("text")
            or ""
        )
        normalized = {
            "block_id": block_id,
            "source_order": index,
            "display_markdown": text,
            "asset_ref_count": len(block.get("asset_refs") or []),
            "blank_count": len(block.get("blank_refs") or []),
            "response_area_count": len(block.get("response_area_refs") or []),
        }
        blocks.append(normalized)
    return blocks, {block["block_id"]: block for block in blocks}


def block_preview(block_id: str, blocks_by_id: dict[str, dict[str, Any]], preview_chars: int) -> dict[str, Any]:
    block = blocks_by_id.get(block_id) or {}
    return {
        "block_id": block_id,
        "source_order": block.get("source_order", source_order(block_id)),
        "text": compact_text(block.get("display_markdown") or "", preview_chars),
        "asset_ref_count": block.get("asset_ref_count", 0),
        "blank_count": block.get("blank_count", 0),
        "response_area_count": block.get("response_area_count", 0),
    }


def edge_block_ids(ids: list[str], max_edge: int) -> list[str]:
    if len(ids) <= max_edge * 2:
        return ids
    return ids[:max_edge] + ids[-max_edge:]


def neighboring_block_ids(block_id: str, blocks: list[dict[str, Any]], radius: int) -> list[str]:
    order = source_order(block_id)
    all_ids = [str(block["block_id"]) for block in blocks]
    positions = {source_order(bid): index for index, bid in enumerate(all_ids)}
    index = positions.get(order)
    if index is None:
        return [block_id]
    start = max(0, index - radius)
    end = min(len(all_ids), index + radius + 1)
    return all_ids[start:end]


def build_repair_input(
    *,
    doc_id: str,
    config: dict[str, Any],
    assembled: dict[str, Any],
    blocks: list[dict[str, Any]],
    blocks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    preview_chars = int(config.get("max_block_preview_chars") or 700)
    max_edge = int(config.get("max_group_edge_blocks") or 4)
    radius = int(config.get("max_uncovered_context_each_side") or 3)
    groups = assembled.get("groups") or []
    covered = {str(bid) for group in groups for bid in group.get("source_block_ids") or []}
    repair_groups = []
    group_ids = [str(group.get("group_id") or "") for group in groups]
    for group_index, group in enumerate(groups):
        ids = [str(bid) for bid in group.get("source_block_ids") or []]
        edge_blocks = [block_preview(bid, blocks_by_id, preview_chars) for bid in edge_block_ids(ids, max_edge)]
        repair_groups.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "group_kind": str(group.get("group_kind") or "mixed_or_unknown"),
                "previous_group_id": group_ids[group_index - 1] if group_index > 0 else "",
                "next_group_id": group_ids[group_index + 1] if group_index + 1 < len(group_ids) else "",
                "start_block_id": str(group.get("start_block_id") or ""),
                "end_block_id": str(group.get("end_block_id") or ""),
                "block_count": len(ids),
                "total_response_area_count": sum(int(blocks_by_id.get(bid, {}).get("response_area_count") or 0) for bid in ids),
                "total_blank_count": sum(int(blocks_by_id.get(bid, {}).get("blank_count") or 0) for bid in ids),
                "total_asset_ref_count": sum(int(blocks_by_id.get(bid, {}).get("asset_ref_count") or 0) for bid in ids),
                "start_evidence": str(group.get("start_evidence") or ""),
                "end_evidence": str(group.get("end_evidence") or ""),
                "edge_blocks": edge_blocks,
            }
        )
    uncovered = []
    for bid in assembled.get("uncovered_nonempty_block_ids") or []:
        bid = str(bid)
        context_ids = neighboring_block_ids(bid, blocks, radius)
        uncovered.append(
            {
                "block_id": bid,
                "context_blocks": [
                    {**block_preview(item, blocks_by_id, preview_chars), "covered_by_group": item in covered}
                    for item in context_ids
                ],
            }
        )
    return {
        "doc_id": doc_id,
        "groups": repair_groups,
        "uncovered_nonempty_blocks": uncovered,
    }


def validate_payload(payload: dict[str, Any] | None, *, doc_id: str, assembled: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    allowed_actions = set(config.get("allowed_actions") or [])
    allowed_conf = set(config.get("apply_confidence_levels") or ["high", "medium"])
    groups = {str(group.get("group_id") or "") for group in assembled.get("groups") or []}
    group_block_ids = {str(bid) for group in assembled.get("groups") or [] for bid in group.get("source_block_ids") or []}
    uncovered = {str(bid) for bid in assembled.get("uncovered_nonempty_block_ids") or []}
    if not isinstance(payload, dict):
        return {
            "schema": "english_docx_group_repair_gate_v0.1",
            "doc_id": doc_id,
            "verdict": "needs_retry",
            "actions": [],
            "warnings": ["invalid_model_json"],
        }, [{"type": "invalid_model_json"}]
    if payload.get("schema") != "english_docx_group_repair_gate_v0.1":
        issues.append({"type": "schema_mismatch", "value": payload.get("schema")})
    if str(payload.get("doc_id") or "") != doc_id:
        issues.append({"type": "doc_id_mismatch", "value": payload.get("doc_id")})
    clean_actions: list[dict[str, Any]] = []
    clean_group_verdicts: list[dict[str, Any]] = []
    clean_uncovered_verdicts: list[dict[str, Any]] = []
    supplied_verdict_groups: set[str] = set()
    allowed_roles = {
        "complete_question",
        "support_only_attach_previous",
        "support_only_attach_specific",
        "heading_or_context",
        "waste",
        "ambiguous",
    }
    for index, item in enumerate(payload.get("group_verdicts") or []):
        if not isinstance(item, dict):
            issues.append({"type": "invalid_group_verdict_shape", "index": index})
            continue
        gid = str(item.get("group_id") or "")
        role = str(item.get("structural_role") or "ambiguous")
        target = str(item.get("target_group_id") or "")
        if gid not in groups:
            issues.append({"type": "unknown_group_verdict_group", "index": index, "group_id": gid})
            continue
        if role not in allowed_roles:
            issues.append({"type": "invalid_structural_role", "index": index, "group_id": gid, "role": role})
            role = "ambiguous"
        if target and target not in groups:
            issues.append({"type": "unknown_group_verdict_target", "index": index, "group_id": gid, "target_group_id": target})
            target = ""
        supplied_verdict_groups.add(gid)
        clean_group_verdicts.append(
            {
                "group_id": gid,
                "structural_role": role,
                "target_group_id": target,
                "confidence": str(item.get("confidence") or "low"),
                "reason": str(item.get("reason") or ""),
            }
        )
    for gid in sorted(groups - supplied_verdict_groups):
        issues.append({"type": "missing_group_verdict", "group_id": gid, "severity": "warning"})
    allowed_uncovered_roles = {
        "support_tail_attach_previous",
        "support_tail_attach_specific",
        "heading_or_context",
        "waste",
        "ambiguous",
    }
    supplied_uncovered: set[str] = set()
    for index, item in enumerate(payload.get("uncovered_verdicts") or []):
        if not isinstance(item, dict):
            issues.append({"type": "invalid_uncovered_verdict_shape", "index": index})
            continue
        bid = str(item.get("block_id") or "")
        role = str(item.get("structural_role") or "ambiguous")
        target = str(item.get("target_group_id") or "")
        if bid not in uncovered:
            issues.append({"type": "unknown_uncovered_verdict_block", "index": index, "block_id": bid})
            continue
        if role not in allowed_uncovered_roles:
            issues.append({"type": "invalid_uncovered_structural_role", "index": index, "block_id": bid, "role": role})
            role = "ambiguous"
        if target and target not in groups:
            issues.append({"type": "unknown_uncovered_verdict_target", "index": index, "block_id": bid, "target_group_id": target})
            target = ""
        supplied_uncovered.add(bid)
        clean_uncovered_verdicts.append(
            {
                "block_id": bid,
                "structural_role": role,
                "target_group_id": target,
                "confidence": str(item.get("confidence") or "low"),
                "reason": str(item.get("reason") or ""),
            }
        )
    for bid in sorted(uncovered - supplied_uncovered, key=source_order):
        issues.append({"type": "missing_uncovered_verdict", "block_id": bid, "severity": "warning"})
    for index, action in enumerate(payload.get("actions") or []):
        if not isinstance(action, dict):
            issues.append({"type": "invalid_action_shape", "index": index})
            continue
        name = str(action.get("action") or "")
        confidence = str(action.get("confidence") or "low")
        if name not in allowed_actions:
            issues.append({"type": "unknown_action", "index": index, "action": name})
            continue
        if name != "no_op" and confidence not in allowed_conf:
            issues.append({"type": "low_confidence_action_skipped", "index": index, "action": name, "confidence": confidence})
            continue
        clean = dict(action)
        if name == "attach_uncovered_blocks":
            target = str(action.get("target_group_id") or "")
            ids = [str(bid) for bid in action.get("block_ids") or []]
            bad_ids = [bid for bid in ids if bid not in uncovered]
            if target not in groups:
                issues.append({"type": "unknown_target_group", "index": index, "target_group_id": target})
                continue
            if bad_ids:
                issues.append({"type": "attach_non_uncovered_block_skipped", "index": index, "block_ids": bad_ids})
                continue
            clean["block_ids"] = sorted(dict.fromkeys(ids), key=source_order)
        elif name == "merge_group":
            source = str(action.get("source_group_id") or "")
            target = str(action.get("target_group_id") or "")
            if source not in groups or target not in groups or source == target:
                issues.append({"type": "invalid_merge_groups", "index": index, "source_group_id": source, "target_group_id": target})
                continue
        elif name == "mark_group_waste":
            source = str(action.get("source_group_id") or "")
            if source not in groups:
                issues.append({"type": "unknown_waste_group", "index": index, "source_group_id": source})
                continue
        elif name == "needs_boundary_retry":
            ids = [str(gid) for gid in action.get("group_ids") or []]
            bad_groups = [gid for gid in ids if gid not in groups]
            if bad_groups:
                issues.append({"type": "unknown_retry_group", "index": index, "group_ids": bad_groups})
                continue
        elif name == "no_op":
            pass
        clean_actions.append(clean)
    return {
        "schema": "english_docx_group_repair_gate_v0.1",
        "doc_id": doc_id,
        "verdict": str(payload.get("verdict") or "ok"),
        "group_verdicts": clean_group_verdicts,
        "uncovered_verdicts": clean_uncovered_verdicts,
        "actions": clean_actions,
        "warnings": [str(item) for item in payload.get("warnings") or []],
    }, issues


def sort_ids(ids: list[str]) -> list[str]:
    return sorted(dict.fromkeys(str(item) for item in ids), key=source_order)


def previous_block_id(block_id: str) -> str:
    text = str(block_id or "")
    try:
        prefix, number = text.rsplit("_", 1)
        value = int(number)
    except ValueError:
        return ""
    if value <= 0:
        return ""
    return f"{prefix}_{value - 1:0{len(number)}d}"


def refresh_group_span(group: dict[str, Any]) -> None:
    ids = sort_ids([str(bid) for bid in group.get("source_block_ids") or []])
    group["source_block_ids"] = ids
    group["block_count"] = len(ids)
    if ids:
        group["start_block_id"] = ids[0]
        group["end_block_id"] = ids[-1]
    projection = group.get("protocol_projection")
    if isinstance(projection, dict):
        payload_ids = projection.get("payload_block_ids")
        if isinstance(payload_ids, list):
            projection["payload_block_ids"] = ids


def apply_actions(assembled: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repaired = copy.deepcopy(assembled)
    groups = repaired.get("groups") or []
    by_gid = {str(group.get("group_id") or ""): group for group in groups}
    removed: set[str] = set()
    applied: list[dict[str, Any]] = []
    uncovered = set(str(bid) for bid in repaired.get("uncovered_nonempty_block_ids") or [])
    actions = list(payload.get("actions") or [])
    existing_merge = {(str(action.get("source_group_id") or ""), str(action.get("target_group_id") or "")) for action in actions if action.get("action") == "merge_group"}
    for verdict in payload.get("group_verdicts") or []:
        role = str(verdict.get("structural_role") or "")
        source_id = str(verdict.get("group_id") or "")
        target_id = str(verdict.get("target_group_id") or "")
        confidence = str(verdict.get("confidence") or "low")
        if role in {"support_only_attach_previous", "support_only_attach_specific"} and target_id and confidence in {"high", "medium"}:
            key = (source_id, target_id)
            if key not in existing_merge:
                actions.append(
                    {
                        "action": "merge_group",
                        "source_group_id": source_id,
                        "target_group_id": target_id,
                        "role_hint": role,
                        "confidence": confidence,
                        "reason": verdict.get("reason") or "synthesized from group_verdict",
                        "synthesized_from": "group_verdict",
                    }
                )
                existing_merge.add(key)
    attach_by_target: dict[str, dict[str, Any]] = {}
    for verdict in payload.get("uncovered_verdicts") or []:
        role = str(verdict.get("structural_role") or "")
        target_id = str(verdict.get("target_group_id") or "")
        confidence = str(verdict.get("confidence") or "low")
        bid = str(verdict.get("block_id") or "")
        if role in {"support_tail_attach_previous", "support_tail_attach_specific"} and target_id and confidence in {"high", "medium"}:
            bucket = attach_by_target.setdefault(
                target_id,
                {
                    "action": "attach_uncovered_blocks",
                    "target_group_id": target_id,
                    "block_ids": [],
                    "role_hint": role,
                    "confidence": confidence,
                    "reason": "synthesized from uncovered_verdicts",
                    "synthesized_from": "uncovered_verdicts",
                },
            )
            bucket["block_ids"].append(bid)
    for verdict in payload.get("group_verdicts") or []:
        role = str(verdict.get("structural_role") or "")
        source_id = str(verdict.get("group_id") or "")
        target_id = str(verdict.get("target_group_id") or "")
        confidence = str(verdict.get("confidence") or "low")
        if role not in {"support_only_attach_previous", "support_only_attach_specific"} or not target_id or confidence not in {"high", "medium"}:
            continue
        source = by_gid.get(source_id) or {}
        source_ids = sort_ids([str(bid) for bid in source.get("source_block_ids") or []])
        if not source_ids:
            continue
        heading_id = previous_block_id(source_ids[0])
        if heading_id not in uncovered:
            continue
        bucket = attach_by_target.setdefault(
            target_id,
            {
                "action": "attach_uncovered_blocks",
                "target_group_id": target_id,
                "block_ids": [],
                "role_hint": "support_tail_heading_following_group_verdict",
                "confidence": confidence,
                "reason": "synthesized from support-only group verdict and adjacent uncovered heading",
                "synthesized_from": "group_verdict_adjacent_heading",
            },
        )
        bucket["block_ids"].append(heading_id)
    existing_attached = {str(bid) for action in actions if action.get("action") == "attach_uncovered_blocks" for bid in action.get("block_ids") or []}
    for action in attach_by_target.values():
        action["block_ids"] = [bid for bid in sort_ids(action["block_ids"]) if bid not in existing_attached]
        if action["block_ids"]:
            actions.append(action)

    for action in actions:
        name = str(action.get("action") or "")
        if name == "attach_uncovered_blocks":
            target = by_gid.get(str(action.get("target_group_id") or ""))
            if not target:
                continue
            ids = [str(bid) for bid in action.get("block_ids") or [] if str(bid) in uncovered]
            target["source_block_ids"] = sort_ids([*(target.get("source_block_ids") or []), *ids])
            refresh_group_span(target)
            uncovered -= set(ids)
            applied.append({"action": name, "target_group_id": target.get("group_id"), "block_ids": ids, "role_hint": action.get("role_hint"), "reason": action.get("reason")})
        elif name == "merge_group":
            source_id = str(action.get("source_group_id") or "")
            target_id = str(action.get("target_group_id") or "")
            source = by_gid.get(source_id)
            target = by_gid.get(target_id)
            if not source or not target:
                continue
            source_ids = [str(bid) for bid in source.get("source_block_ids") or []]
            target["source_block_ids"] = sort_ids([*(target.get("source_block_ids") or []), *source_ids])
            refresh_group_span(target)
            target.setdefault("repair_merged_source_group_ids", []).append(source_id)
            removed.add(source_id)
            applied.append({"action": name, "source_group_id": source_id, "target_group_id": target_id, "source_block_ids": source_ids, "role_hint": action.get("role_hint"), "reason": action.get("reason")})
        elif name == "mark_group_waste":
            source_id = str(action.get("source_group_id") or "")
            source = by_gid.get(source_id)
            if source:
                source["status"] = "waste_by_repair_gate"
                source.setdefault("repair_notes", []).append(str(action.get("reason") or "marked waste by repair gate"))
                applied.append({"action": name, "source_group_id": source_id, "reason": action.get("reason")})
        elif name == "needs_boundary_retry":
            applied.append({"action": name, "group_ids": action.get("group_ids") or [], "reason": action.get("reason")})
    repaired["groups"] = [group for group in groups if str(group.get("group_id") or "") not in removed]
    repaired["uncovered_nonempty_block_ids"] = sorted(uncovered, key=source_order)
    repaired["schema_version"] = "english_docx_group_repair_gate_repaired_groups.v0.1"
    repaired["repair_gate_applied_actions"] = applied
    return repaired, applied


def blocking_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [issue for issue in issues if str(issue.get("severity") or "blocking") != "warning"]


def validate_group_integrity(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    groups = payload.get("groups") or []
    seen: dict[str, str] = {}
    for group in groups:
        gid = str(group.get("group_id") or "")
        ids = [str(bid) for bid in group.get("source_block_ids") or []]
        if ids != sort_ids(ids):
            issues.append({"type": "group_source_block_ids_not_sorted", "group_id": gid, "severity": "blocking"})
        if len(ids) != len(set(ids)):
            issues.append({"type": "duplicate_block_inside_group", "group_id": gid, "severity": "blocking"})
        if ids and (str(group.get("start_block_id") or "") != ids[0] or str(group.get("end_block_id") or "") != ids[-1]):
            issues.append(
                {
                    "type": "group_span_mismatch",
                    "group_id": gid,
                    "start_block_id": group.get("start_block_id"),
                    "end_block_id": group.get("end_block_id"),
                    "expected_start_block_id": ids[0],
                    "expected_end_block_id": ids[-1],
                    "severity": "blocking",
                }
            )
        for bid in ids:
            if bid in seen:
                issues.append({"type": "block_assigned_to_multiple_groups", "block_id": bid, "first_group_id": seen[bid], "second_group_id": gid, "severity": "blocking"})
            seen[bid] = gid
    overlap = sorted(set(str(bid) for bid in payload.get("uncovered_nonempty_block_ids") or []) & set(seen), key=source_order)
    if overlap:
        issues.append({"type": "covered_blocks_still_uncovered", "block_ids": overlap, "severity": "blocking"})
    return issues


def select_safe_assembled(
    *,
    original: dict[str, Any],
    repaired: dict[str, Any],
    payload: dict[str, Any],
    validation_issues: list[dict[str, Any]],
    integrity_issues: list[dict[str, Any]],
    model_failed: bool,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = config.get("safety_policy") or {}
    reasons: list[str] = []
    if model_failed and policy.get("fallback_on_model_failure", True):
        reasons.append("model_failure")
    if str(payload.get("verdict") or "") == "needs_retry" and policy.get("fallback_on_needs_retry", True):
        reasons.append("model_verdict_needs_retry")
    if blocking_issues(validation_issues) and policy.get("fallback_on_blocking_validation_issue", True):
        reasons.append("blocking_validation_issue")
    if blocking_issues(integrity_issues) and policy.get("fallback_on_integrity_error", True):
        reasons.append("integrity_error")
    if reasons:
        selected = copy.deepcopy(original)
        selected["schema_version"] = "english_docx_group_repair_gate_selected_groups.v0.1"
        selected["repair_gate_selection"] = {"mode": "fallback_original_assembled", "fallback_reasons": reasons}
        return selected, selected["repair_gate_selection"]
    selected = copy.deepcopy(repaired)
    selected["schema_version"] = "english_docx_group_repair_gate_selected_groups.v0.1"
    selected["repair_gate_selection"] = {"mode": "repaired", "fallback_reasons": []}
    return selected, selected["repair_gate_selection"]


def render_audit(
    *,
    out_path: Path,
    doc_id: str,
    repair_input: dict[str, Any],
    payload: dict[str, Any],
    applied: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    integrity_issues: list[dict[str, Any]],
    selection: dict[str, Any],
) -> None:
    def e(value: Any) -> str:
        return html.escape(str(value or ""))

    action_rows = []
    for action in payload.get("actions") or []:
        action_rows.append(
            "<tr>"
            f"<td>{e(action.get('action'))}</td>"
            f"<td>{e(action.get('confidence'))}</td>"
            f"<td><pre>{e(json.dumps(action, ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
        )
    verdict_rows = []
    for item in payload.get("group_verdicts") or []:
        verdict_rows.append(
            "<tr>"
            f"<td>{e(item.get('group_id'))}</td>"
            f"<td>{e(item.get('structural_role'))}</td>"
            f"<td>{e(item.get('target_group_id'))}</td>"
            f"<td>{e(item.get('confidence'))}</td>"
            f"<td>{e(item.get('reason'))}</td>"
            "</tr>"
        )
    uncovered_verdict_rows = []
    for item in payload.get("uncovered_verdicts") or []:
        uncovered_verdict_rows.append(
            "<tr>"
            f"<td>{e(item.get('block_id'))}</td>"
            f"<td>{e(item.get('structural_role'))}</td>"
            f"<td>{e(item.get('target_group_id'))}</td>"
            f"<td>{e(item.get('confidence'))}</td>"
            f"<td>{e(item.get('reason'))}</td>"
            "</tr>"
        )
    groups = []
    for group in repair_input.get("groups") or []:
        edge = "".join(f"<li><b>{e(block['block_id'])}</b> {e(block.get('text'))}</li>" for block in group.get("edge_blocks") or [])
        groups.append(
            f"<section class='group'><h3>{e(group.get('group_id'))} <span>{e(group.get('group_kind'))} · {e(group.get('start_block_id'))}-{e(group.get('end_block_id'))}</span></h3><ul>{edge}</ul></section>"
        )
    uncovered = []
    for item in repair_input.get("uncovered_nonempty_blocks") or []:
        ctx = "".join(
            f"<li class='{ 'covered' if block.get('covered_by_group') else 'uncovered'}'><b>{e(block.get('block_id'))}</b> {e(block.get('text'))}</li>"
            for block in item.get("context_blocks") or []
        )
        uncovered.append(f"<section class='uncovered'><h3>{e(item.get('block_id'))}</h3><ul>{ctx}</ul></section>")
    out_path.write_text(
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{margin:0;background:#f3f6f8;color:#172033;font:15px/1.55 Arial,"Microsoft YaHei",sans-serif}
header{padding:18px 28px;background:#fff;border-bottom:1px solid #d8dee4;position:sticky;top:0}
main{max-width:1180px;margin:24px auto;padding:0 18px}.panel,.group,.uncovered{background:#fff;border:1px solid #d8dee4;border-radius:6px;margin:12px 0;padding:14px}
h1{margin:0;font-size:22px}h2{font-size:18px;margin:18px 0 8px}h3{font-size:15px;margin:0 0 8px}span{color:#667085;font-weight:400}
table{width:100%;border-collapse:collapse;background:#fff}td,th{border:1px solid #d8dee4;padding:8px;vertical-align:top}pre{white-space:pre-wrap;margin:0;font-size:12px}
li{margin:5px 0}.covered{color:#667085}.uncovered b{color:#b45309}
</style></head><body>"""
        f"<header><h1>Group Repair Gate Audit - {e(doc_id)}</h1><div>verdict={e(payload.get('verdict'))} | selected={e(selection.get('mode'))} | actions={len(payload.get('actions') or [])} | applied={len(applied)} | validation={len(issues)} | integrity={len(integrity_issues)}</div></header><main>"
        f"<section class='panel'><h2>Safety Selection</h2><pre>{e(json.dumps(selection, ensure_ascii=False, indent=2))}</pre></section>"
        f"<section class='panel'><h2>Group Verdicts</h2><table><tr><th>group</th><th>role</th><th>target</th><th>confidence</th><th>reason</th></tr>{''.join(verdict_rows)}</table></section>"
        f"<section class='panel'><h2>Uncovered Verdicts</h2><table><tr><th>block</th><th>role</th><th>target</th><th>confidence</th><th>reason</th></tr>{''.join(uncovered_verdict_rows)}</table></section>"
        f"<section class='panel'><h2>Actions</h2><table><tr><th>action</th><th>confidence</th><th>payload</th></tr>{''.join(action_rows)}</table></section>"
        f"<section class='panel'><h2>Applied</h2><pre>{e(json.dumps(applied, ensure_ascii=False, indent=2))}</pre></section>"
        f"<section class='panel'><h2>Validation Issues</h2><pre>{e(json.dumps(issues, ensure_ascii=False, indent=2))}</pre></section>"
        f"<section class='panel'><h2>Integrity Issues</h2><pre>{e(json.dumps(integrity_issues, ensure_ascii=False, indent=2))}</pre></section>"
        f"<h2>Groups</h2>{''.join(groups)}<h2>Uncovered Context</h2>{''.join(uncovered)}"
        "</main></body></html>",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    api_key = os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.no_model and not api_key:
        raise SystemExit(f"missing api key env: {config.get('api_key_env')}")
    assembled = read_json(args.assembled_groups)
    blocks, blocks_by_id = load_blocks(args.block_stream)
    doc_id = args.doc_id or args.assembled_groups.parent.name
    repair_input = build_repair_input(doc_id=doc_id, config=config, assembled=assembled, blocks=blocks, blocks_by_id=blocks_by_id)
    output_root = Path(str(config.get("owned_output_root") or "outputs/english_docx_group_repair_gate_v0_1"))
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    out_dir = output_root / args.run_id / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    user_prompt = render_template(
        user_template,
        {
            "doc_id": doc_id,
            "prompt_version": config.get("prompt_version"),
            "repair_input_json": json.dumps(repair_input, ensure_ascii=False, indent=2),
        },
    )
    raw_dir = out_dir / "raw_model_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": user_prompt})
    max_attempts = 1 if args.no_model else int((config.get("runner") or {}).get("max_attempts") or 3)
    last_result: dict[str, Any] = {}
    payload: dict[str, Any] | None = None
    model_failed = False
    for attempt in range(1, max_attempts + 1):
        if args.no_model:
            payload = {
                "schema": "english_docx_group_repair_gate_v0.1",
                "doc_id": doc_id,
                "verdict": "ok",
                "actions": [],
                "warnings": ["no_model"],
            }
            break
        try:
            result = call_model(config, system_prompt, user_prompt, api_key)
            last_result = result
            write_json(raw_dir / f"attempt{attempt}.raw.json", result["raw_response"])
            (raw_dir / f"attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result.get("parsed") is not None:
                write_json(raw_dir / f"attempt{attempt}.parsed.json", result["parsed"])
            payload, issues = validate_payload(result.get("parsed"), doc_id=doc_id, assembled=assembled, config=config)
            write_json(raw_dir / f"attempt{attempt}.validated.json", {"payload": payload, "issues": issues})
            if not issues or payload.get("actions"):
                break
        except Exception as exc:  # noqa: BLE001
            model_failed = True
            last_result = {"exception": repr(exc)}
            write_json(raw_dir / f"attempt{attempt}.exception.json", last_result)
    payload, issues = validate_payload(payload, doc_id=doc_id, assembled=assembled, config=config)
    repaired, applied = apply_actions(assembled, payload)
    integrity_issues = validate_group_integrity(repaired)
    selected, selection = select_safe_assembled(
        original=assembled,
        repaired=repaired,
        payload=payload,
        validation_issues=issues,
        integrity_issues=integrity_issues,
        model_failed=model_failed and payload.get("verdict") == "needs_retry" and not payload.get("group_verdicts"),
        config=config,
    )
    write_json(out_dir / "repair_input.json", repair_input)
    write_json(out_dir / "repair_actions.json", payload)
    write_json(out_dir / "repair_validation_issues.json", issues)
    write_json(out_dir / "repair_integrity_issues.json", integrity_issues)
    write_json(out_dir / "repaired_assembled_groups.json", repaired)
    write_json(out_dir / "selected_assembled_groups.json", selected)
    write_json(
        out_dir / "repair_trace.json",
        {
            "source_assembled_groups": safe_rel(args.assembled_groups),
            "source_block_stream": safe_rel(args.block_stream),
            "selected_mode": selection.get("mode"),
            "fallback_reasons": selection.get("fallback_reasons") or [],
            "applied_actions": applied,
            "validation_issues": issues,
            "integrity_issues": integrity_issues,
        },
    )
    render_audit(out_path=out_dir / "audit.html", doc_id=doc_id, repair_input=repair_input, payload=payload, applied=applied, issues=issues, integrity_issues=integrity_issues, selection=selection)
    summary = {
        "schema_version": "english_docx_group_repair_gate_summary.v0.1",
        "doc_id": doc_id,
        "run_id": args.run_id,
        "verdict": payload.get("verdict"),
        "selected_mode": selection.get("mode"),
        "fallback_reasons": selection.get("fallback_reasons") or [],
        "action_counts": dict(Counter(action.get("action") for action in payload.get("actions") or [])),
        "group_role_counts": dict(Counter(item.get("structural_role") for item in payload.get("group_verdicts") or [])),
        "uncovered_role_counts": dict(Counter(item.get("structural_role") for item in payload.get("uncovered_verdicts") or [])),
        "applied_action_count": len(applied),
        "validation_issue_count": len(issues),
        "blocking_validation_issue_count": len(blocking_issues(issues)),
        "integrity_issue_count": len(integrity_issues),
        "blocking_integrity_issue_count": len(blocking_issues(integrity_issues)),
        "group_count_before": len(assembled.get("groups") or []),
        "group_count_after": len(repaired.get("groups") or []),
        "selected_group_count": len(selected.get("groups") or []),
        "uncovered_before": len(assembled.get("uncovered_nonempty_block_ids") or []),
        "uncovered_after": len(repaired.get("uncovered_nonempty_block_ids") or []),
        "selected_uncovered": len(selected.get("uncovered_nonempty_block_ids") or []),
        "usage": last_result.get("usage") or {},
        "artifacts": {
            "audit": safe_rel(out_dir / "audit.html"),
            "repaired_assembled_groups": safe_rel(out_dir / "repaired_assembled_groups.json"),
            "selected_assembled_groups": safe_rel(out_dir / "selected_assembled_groups.json"),
            "repair_actions": safe_rel(out_dir / "repair_actions.json"),
            "repair_trace": safe_rel(out_dir / "repair_trace.json"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental repair gate between English DOCX boundary cutting and field normalization.")
    parser.add_argument("--block-stream", required=True, type=Path)
    parser.add_argument("--assembled-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
