from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_grouper_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return -1


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def slug_for(path: Path) -> str:
    value = path.parent.name or path.stem
    chars: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in "._-":
            chars.append(ch)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return ("".join(chars).strip("_") or "docx_question_grouper")[:96]


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


def load_prompt(config: dict[str, Any], key: str) -> str:
    path = Path(str(config.get(key) or ""))
    if not path.is_absolute():
        path = ROOT / path
    return read_text(path)


def load_tags(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    tags = payload.get("tags", payload) if isinstance(payload, dict) else payload
    return {str(item.get("block_id")): item for item in tags if isinstance(item, dict)}


def load_blocks(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    paragraphs = payload.get("paragraphs") or payload.get("blocks") or []
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(paragraphs):
        block_id = str(block.get("block_id") or f"b_{index:06d}")
        markdown = str(block.get("display_markdown") or block.get("markdown") or "")
        text = str(block.get("plain_text_lossy") or block.get("text") or "")
        image_refs = [item for item in (block.get("image_refs") or block.get("asset_refs") or []) if isinstance(item, dict)]
        blocks.append(
            {
                "block_id": block_id,
                "source_order": index,
                "source_block_type": str(block.get("source_block_type") or "docx_block"),
                "text": text,
                "display_markdown": markdown,
                "formula_count": int(block.get("formula_count") or 0),
                "image_ref_count": len(image_refs),
                "content_tags": [],
            }
        )
    return blocks


@dataclass(frozen=True)
class Window:
    window_id: str
    core_start: int
    core_end_exclusive: int
    input_start: int
    input_end_exclusive: int


def plan_windows(blocks: list[dict[str, Any]], core: int, stride: int, left: int, right: int) -> list[Window]:
    windows: list[Window] = []
    start = 0
    index = 0
    while start < len(blocks):
        end = min(len(blocks), start + core)
        windows.append(
            Window(
                window_id=f"g_{index:04d}",
                core_start=start,
                core_end_exclusive=end,
                input_start=max(0, start - left),
                input_end_exclusive=min(len(blocks), end + right),
            )
        )
        if end >= len(blocks):
            break
        start += max(1, stride)
        index += 1
    return windows


def block_for_model(block: dict[str, Any], tag: dict[str, Any], scope: str, preview_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "scope": scope,
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "block_role": tag.get("primary_role", "unknown"),
        "needs_resolution": bool(tag.get("needs_resolution", False)),
        "display_markdown_preview": compact_text(block.get("display_markdown", ""), preview_chars),
        "text_preview": compact_text(block.get("text", ""), preview_chars),
        "formula_count": block.get("formula_count", 0),
        "image_ref_count": block.get("image_ref_count", 0),
        "content_tags": tag.get("content_tags", []),
    }


def build_window_payload(
    *,
    doc_id: str,
    window: Window,
    blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    preview_chars = int((config.get("window_policy") or {}).get("max_block_preview_chars") or 520)
    groups = {"previous_tail_blocks": [], "current_blocks": [], "next_head_blocks": [], "excluded_evidence_blocks": []}
    for index in range(window.input_start, window.input_end_exclusive):
        block = blocks[index]
        tag = tags.get(block["block_id"], {})
        scope = "previous_tail" if index < window.core_start else ("next_head" if index >= window.core_end_exclusive else "current")
        role = str(tag.get("primary_role") or "unknown")
        item = block_for_model(block, tag, scope, preview_chars)
        if role == "question_content":
            if scope == "previous_tail":
                groups["previous_tail_blocks"].append(item)
            elif scope == "next_head":
                groups["next_head_blocks"].append(item)
            else:
                groups["current_blocks"].append(item)
        else:
            groups["excluded_evidence_blocks"].append(item)
    return {
        "doc_id": doc_id,
        "window_id": window.window_id,
        "prompt_version": config.get("prompt_version"),
        "window_policy": config.get("window_policy", {}),
        "core_block_ids": [blocks[index]["block_id"] for index in range(window.core_start, window.core_end_exclusive)],
        **groups,
    }


def call_model(config: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str, timeout: int) -> dict[str, Any]:
    body = {
        "model": config.get("default_model_endpoint_id"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
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
        "request_body": body,
        "raw_response": raw_response,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_packet(
    packet: dict[str, Any],
    valid_ids: set[str],
    current_ids: set[str],
    ordered_input_ids: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    evidence_ids = [str(item) for item in packet.get("source_block_ids", []) or []]
    start_block_id = str(packet.get("start_block_id") or "")
    end_block_id = str(packet.get("end_block_id") or "")
    if not evidence_ids and not (start_block_id and end_block_id):
        return None, [{"type": "empty_packet"}]
    unknown = [block_id for block_id in evidence_ids + [start_block_id, end_block_id] if block_id and block_id not in valid_ids]
    if unknown:
        return None, [{"type": "unknown_block_id", "block_ids": unknown}]
    evidence_ordered = sorted(dict.fromkeys(evidence_ids), key=source_order)
    if not start_block_id:
        start_block_id = evidence_ordered[0]
    if not end_block_id:
        end_block_id = evidence_ordered[-1]
    start_order = source_order(start_block_id)
    end_order = source_order(end_block_id)
    if start_order > end_order:
        return None, [{"type": "inverted_packet_range", "start_block_id": start_block_id, "end_block_id": end_block_id}]
    expanded = [block_id for block_id in ordered_input_ids if start_order <= source_order(block_id) <= end_order]
    if not expanded:
        return None, [{"type": "empty_expanded_range", "start_block_id": start_block_id, "end_block_id": end_block_id}]
    evidence_outside_range = [block_id for block_id in evidence_ordered if block_id not in expanded]
    if evidence_outside_range:
        issues.append({"type": "evidence_outside_range", "severity": "warning", "block_ids": evidence_outside_range})
    if not (set(expanded) & current_ids):
        issues.append({"type": "context_only_packet", "severity": "info", "block_ids": expanded})
    range_filled = [block_id for block_id in expanded if block_id not in set(evidence_ordered)]
    normalized = {
        "draft_id": str(packet.get("draft_id") or ""),
        "source_block_ids": expanded,
        "evidence_block_ids": evidence_ordered,
        "range_filled_block_ids": range_filled,
        "start_block_id": expanded[0],
        "end_block_id": expanded[-1],
        "completion_status": str(packet.get("completion_status") or "unknown"),
        "confidence": str(packet.get("confidence") or "unknown"),
        "reason": str(packet.get("reason") or ""),
    }
    return normalized, issues


def validate_output(payload: dict[str, Any] | None, window_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return [], [{"type": "invalid_json"}]
    issues: list[dict[str, Any]] = []
    if payload.get("schema") != "docx_question_grouper_v0.1":
        issues.append({"type": "schema_mismatch", "value": payload.get("schema")})
    if payload.get("window_id") != window_payload["window_id"]:
        issues.append({"type": "window_id_mismatch", "value": payload.get("window_id")})
    valid_ids = {
        block["block_id"]
        for key in ("previous_tail_blocks", "current_blocks", "next_head_blocks", "excluded_evidence_blocks")
        for block in window_payload.get(key, [])
    }
    current_ids = {
        block["block_id"]
        for key in ("current_blocks", "excluded_evidence_blocks")
        for block in window_payload.get(key, [])
        if block.get("scope") == "current"
    }
    ordered_input_ids = sorted(valid_ids, key=source_order)
    packets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for packet in payload.get("draft_packets", []) or []:
        if not isinstance(packet, dict):
            issues.append({"type": "invalid_packet_shape"})
            continue
        normalized, packet_issues = validate_packet(packet, valid_ids, current_ids, ordered_input_ids)
        issues.extend(packet_issues)
        if normalized:
            key = ",".join(normalized["source_block_ids"])
            if key in seen:
                issues.append({"type": "duplicate_packet_in_window", "block_ids": normalized["source_block_ids"]})
            else:
                seen.add(key)
                packets.append(normalized)
    return packets, issues


def run_one_window(
    *,
    window: Window,
    blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    config: dict[str, Any],
    doc_id: str,
    system_prompt: str,
    user_template: str,
    raw_dir: Path,
    api_key: str,
    timeout: int,
    resume: bool,
) -> dict[str, Any]:
    window_payload = build_window_payload(doc_id=doc_id, window=window, blocks=blocks, tags=tags, config=config)
    prompt = render_template(
        user_template,
        {
            "doc_id": doc_id,
            "window_id": window.window_id,
            "prompt_version": config.get("prompt_version"),
            "window_policy_json": json.dumps(config.get("window_policy", {}), ensure_ascii=False, indent=2),
            "window_blocks_json": json.dumps(
                {
                    "previous_tail_blocks": window_payload["previous_tail_blocks"],
                    "current_blocks": window_payload["current_blocks"],
                    "next_head_blocks": window_payload["next_head_blocks"],
                    "excluded_evidence_blocks": window_payload["excluded_evidence_blocks"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    )
    prompt_path = raw_dir / f"{window.window_id}.prompt.json"
    response_path = raw_dir / f"{window.window_id}.response.json"
    content_path = raw_dir / f"{window.window_id}.content.json"
    parsed_path = raw_dir / f"{window.window_id}.parsed.json"
    write_json(prompt_path, {"window_payload": window_payload, "system_prompt": system_prompt, "user_prompt": prompt})
    started = time.time()
    try:
        if resume and parsed_path.exists():
            parsed = read_json(parsed_path)
            raw_response = read_json(response_path) if response_path.exists() else {}
            result = {"parsed": parsed, "raw_response": raw_response, "raw_content": "", "parse_error": "", "latency_seconds": 0.0, "source": "replay"}
        else:
            result = call_model(config, system_prompt, prompt, api_key, timeout)
            write_json(response_path, result["raw_response"])
            content_path.write_text(result["raw_content"], encoding="utf-8")
            if result["parsed"] is not None:
                write_json(parsed_path, result["parsed"])
            result["source"] = "model"
        packets, issues = validate_output(result["parsed"], window_payload)
    except Exception as exc:  # noqa: BLE001 - preserve failure as artifact for experimental node
        result = {"source": "failed", "latency_seconds": round(time.time() - started, 3), "raw_response": {}, "raw_content": "", "parse_error": str(exc)}
        packets, issues = [], [{"type": "window_failed", "reason": str(exc), "window_id": window.window_id}]
    return {
        "window_id": window.window_id,
        "source": result["source"],
        "packets": packets,
        "issues": issues,
        "latency_seconds": result.get("latency_seconds", round(time.time() - started, 3)),
        "parse_error": result.get("parse_error", ""),
        "usage": (result.get("raw_response") or {}).get("usage", {}),
    }


def packet_score(packet: dict[str, Any], core_ids_by_window: dict[str, set[str]]) -> tuple[int, int, int]:
    ids = set(packet["source_block_ids"])
    core_overlap = len(ids & core_ids_by_window.get(packet.get("window_id", ""), set()))
    confidence_rank = {"high": 3, "medium": 2, "low": 1}.get(packet.get("confidence"), 0)
    return (core_overlap, len(ids), confidence_rank)


def block_ids_between(blocks: list[dict[str, Any]], start_block_id: str, end_block_id: str) -> list[str]:
    start = source_order(start_block_id)
    end = source_order(end_block_id)
    return [block["block_id"] for block in blocks if start <= source_order(block["block_id"]) <= end]


def refresh_packet_range(packet: dict[str, Any], blocks: list[dict[str, Any]], start_block_id: str, end_block_id: str) -> dict[str, Any] | None:
    source_ids = block_ids_between(blocks, start_block_id, end_block_id)
    if not source_ids:
        return None
    evidence = [block_id for block_id in packet.get("evidence_block_ids", packet.get("source_block_ids", [])) if block_id in set(source_ids)]
    out = {**packet}
    out["start_block_id"] = source_ids[0]
    out["end_block_id"] = source_ids[-1]
    out["source_block_ids"] = source_ids
    out["evidence_block_ids"] = evidence
    out["range_filled_block_ids"] = [block_id for block_id in source_ids if block_id not in set(evidence)]
    return out


def overlap_len(left: dict[str, Any], right: dict[str, Any]) -> int:
    start = max(source_order(left["start_block_id"]), source_order(right["start_block_id"]))
    end = min(source_order(left["end_block_id"]), source_order(right["end_block_id"]))
    return max(0, end - start + 1)


def merge_status(left: dict[str, Any], right: dict[str, Any]) -> str:
    right_status = str(right.get("completion_status", ""))
    left_status = str(left.get("completion_status", ""))
    parts: list[str] = []
    if "continues_from_previous" in left_status:
        parts.append("continues_from_previous")
    if "continues_to_next" in right_status:
        parts.append("continues_to_next")
    return ", ".join(parts) if parts else "complete"


def merge_packets(left: dict[str, Any], right: dict[str, Any], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    start = left["start_block_id"] if source_order(left["start_block_id"]) <= source_order(right["start_block_id"]) else right["start_block_id"]
    end = left["end_block_id"] if source_order(left["end_block_id"]) >= source_order(right["end_block_id"]) else right["end_block_id"]
    evidence = sorted(
        dict.fromkeys((left.get("evidence_block_ids") or left.get("source_block_ids") or []) + (right.get("evidence_block_ids") or right.get("source_block_ids") or [])),
        key=source_order,
    )
    merged = {
        **left,
        "draft_id": left.get("draft_id") or right.get("draft_id"),
        "evidence_block_ids": evidence,
        "completion_status": merge_status(left, right),
        "confidence": "high" if "high" in {left.get("confidence"), right.get("confidence")} else str(left.get("confidence") or right.get("confidence") or "unknown"),
        "reason": "Merged overlapping sliding-window draft packets.",
        "merged_from_windows": sorted(set((left.get("merged_from_windows") or [left.get("window_id")]) + (right.get("merged_from_windows") or [right.get("window_id")]))),
    }
    refreshed = refresh_packet_range(merged, blocks, start, end)
    return refreshed or merged


def resolve_overlapping_packets(
    packets: list[dict[str, Any]],
    windows: list[Window],
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_ids_by_window = {
        window.window_id: {blocks[index]["block_id"] for index in range(window.core_start, window.core_end_exclusive)}
        for window in windows
    }
    audit: list[dict[str, Any]] = []
    ordered = sorted(packets, key=lambda item: (source_order(item["start_block_id"]), source_order(item["end_block_id"])))

    filtered: list[dict[str, Any]] = []
    for index, packet in enumerate(ordered):
        previous_packet = ordered[index - 1] if index > 0 else None
        next_packet = ordered[index + 1] if index + 1 < len(ordered) else None
        packet_len = max(1, len(packet.get("source_block_ids", [])))
        core_overlap = len(set(packet.get("source_block_ids", [])) & core_ids_by_window.get(packet.get("window_id", ""), set()))
        bridges_neighbors = bool(previous_packet and next_packet and overlap_len(previous_packet, packet) and overlap_len(packet, next_packet))
        if bridges_neighbors and (core_overlap <= 1 or core_overlap / packet_len <= 0.25):
            audit.append(
                {
                    "type": "drop_low_core_bridge_packet",
                    "window_id": packet.get("window_id"),
                    "block_ids": packet.get("source_block_ids", []),
                    "core_overlap": core_overlap,
                    "block_count": packet_len,
                }
            )
            continue
        filtered.append(packet)

    trimmed: list[dict[str, Any]] = []
    for packet in filtered:
        small_overlap = overlap_len(trimmed[-1], packet) if trimmed else 0
        if trimmed and 0 < small_overlap <= 2:
            new_start_order = source_order(trimmed[-1]["end_block_id"]) + 1
            new_start = next((block["block_id"] for block in blocks if source_order(block["block_id"]) == new_start_order), "")
            if new_start and source_order(new_start) <= source_order(packet["end_block_id"]):
                refreshed = refresh_packet_range(packet, blocks, new_start, packet["end_block_id"])
                if refreshed:
                    audit.append(
                        {
                            "type": "trim_small_boundary_overlap",
                            "previous_end_block_id": trimmed[-1]["end_block_id"],
                            "old_start_block_id": packet["start_block_id"],
                            "new_start_block_id": refreshed["start_block_id"],
                            "overlap_block_count": small_overlap,
                            "window_id": packet.get("window_id"),
                        }
                    )
                    packet = refreshed
        trimmed.append(packet)

    resolved: list[dict[str, Any]] = []
    for packet in trimmed:
        if not resolved:
            resolved.append(packet)
            continue
        previous_packet = resolved[-1]
        current_overlap = overlap_len(previous_packet, packet)
        should_merge = current_overlap >= 3 or (
            current_overlap > 0
            and ("continues_to_next" in str(previous_packet.get("completion_status", "")) or "continues_from_previous" in str(packet.get("completion_status", "")))
        )
        if should_merge:
            merged = merge_packets(previous_packet, packet, blocks)
            audit.append(
                {
                    "type": "merge_overlapping_packets",
                    "left_window": previous_packet.get("window_id"),
                    "right_window": packet.get("window_id"),
                    "left_range": [previous_packet["start_block_id"], previous_packet["end_block_id"]],
                    "right_range": [packet["start_block_id"], packet["end_block_id"]],
                    "merged_range": [merged["start_block_id"], merged["end_block_id"]],
                    "overlap_block_count": current_overlap,
                }
            )
            resolved[-1] = merged
        else:
            resolved.append(packet)
    return resolved, audit


def normalize_final_completion_statuses(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(packets, key=lambda item: source_order(item["start_block_id"]))
    normalized: list[dict[str, Any]] = []
    for index, packet in enumerate(ordered):
        previous_packet = ordered[index - 1] if index > 0 else None
        next_packet = ordered[index + 1] if index + 1 < len(ordered) else None
        status = str(packet.get("completion_status") or "unknown")
        parts: list[str] = []
        if "continues_from_previous" in status and previous_packet and source_order(packet["start_block_id"]) <= source_order(previous_packet["end_block_id"]):
            parts.append("continues_from_previous")
        if "continues_to_next" in status and next_packet and source_order(next_packet["start_block_id"]) <= source_order(packet["end_block_id"]):
            parts.append("continues_to_next")
        out = {**packet, "model_completion_status": status, "completion_status": ", ".join(parts) if parts else "complete"}
        normalized.append(out)
    return normalized


def dedupe_packets(packets: list[dict[str, Any]], windows: list[Window], blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_ids_by_window = {
        window.window_id: {blocks[index]["block_id"] for index in range(window.core_start, window.core_end_exclusive)}
        for window in windows
    }
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for packet in packets:
        key = tuple(packet["source_block_ids"])
        existing = by_key.get(key)
        if not existing or packet_score(packet, core_ids_by_window) > packet_score(existing, core_ids_by_window):
            if existing:
                audit.append({"type": "replace_identical_packet", "kept_window": packet.get("window_id"), "dropped_window": existing.get("window_id"), "block_ids": list(key)})
            by_key[key] = packet
        else:
            audit.append({"type": "drop_identical_packet", "kept_window": existing.get("window_id"), "dropped_window": packet.get("window_id"), "block_ids": list(key)})
    candidates = sorted(by_key.values(), key=lambda item: (source_order(item["start_block_id"]), -len(item["source_block_ids"])))
    kept: list[dict[str, Any]] = []
    for packet in candidates:
        ids = set(packet["source_block_ids"])
        suppressor = next((other for other in kept if ids < set(other["source_block_ids"])), None)
        if suppressor:
            audit.append({"type": "drop_subset_packet", "dropped": packet["source_block_ids"], "kept": suppressor["source_block_ids"]})
            continue
        kept.append(packet)
    kept, overlap_audit = resolve_overlapping_packets(kept, windows, blocks)
    audit.extend(overlap_audit)
    kept = normalize_final_completion_statuses(kept)
    for index, packet in enumerate(sorted(kept, key=lambda item: source_order(item["start_block_id"])), start=1):
        packet["packet_id"] = f"dq_{index:04d}"
    return kept, audit


def render_trace(out_dir: Path, blocks: list[dict[str, Any]], tags: dict[str, dict[str, Any]], packets: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    packet_by_block: dict[str, list[str]] = {}
    for packet in packets:
        for block_id in packet.get("source_block_ids", []):
            packet_by_block.setdefault(block_id, []).append(packet["packet_id"])
    rows = []
    for block in blocks:
        tag = tags.get(block["block_id"], {})
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(block["block_id"]),
                html.escape(str(tag.get("primary_role", ""))),
                html.escape(",".join(packet_by_block.get(block["block_id"], []))),
                html.escape(str(block.get("image_ref_count", 0))),
                html.escape(compact_text(block.get("display_markdown") or block.get("text") or "", 260)),
            )
        )
    page = (
        "<!doctype html><meta charset='utf-8'><title>DOCX Question Grouper Trace</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;background:#f5f7fb;color:#102033}"
        "table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #d8e0eb;padding:6px;vertical-align:top}"
        "th{background:#eef3f9}.issues{white-space:pre-wrap;background:#fff;border:1px solid #d8e0eb;padding:12px}</style>"
        "<h1>DOCX Question Grouper Trace</h1>"
        f"<p>blocks={len(blocks)} packets={len(packets)} issues={len(issues)}</p>"
        f"<pre class='issues'>{html.escape(json.dumps(issues[:120], ensure_ascii=False, indent=2))}</pre>"
        "<table><thead><tr><th>block</th><th>role</th><th>packet</th><th>images</th><th>markdown</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )
    (out_dir / "question_grouper_trace.html").write_text(page, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks = load_blocks(args.paragraph_stream)
    tags = load_tags(args.block_tags)
    doc_id = args.doc_id or slug_for(args.paragraph_stream)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_grouper_v0_1")
    out_dir = out_root / args.run_id / doc_id
    raw_dir = out_dir / "raw_model_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    policy = config.get("window_policy", {}) or {}
    windows = plan_windows(
        blocks,
        int(args.core_blocks or policy.get("core_blocks") or 28),
        int(args.stride_blocks or policy.get("stride_blocks") or 18),
        int(policy.get("previous_tail_blocks") or 8),
        int(policy.get("next_head_blocks") or 8),
    )
    if args.max_windows:
        windows = windows[: args.max_windows]
    write_json(out_dir / "window_plan.json", {"schema_version": "docx_question_grouper_window_plan.v0.1", "windows": [window.__dict__ for window in windows]})
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    all_results: list[dict[str, Any]] = []
    if args.no_model:
        all_results = [{"window_id": window.window_id, "source": "no_model", "packets": [], "issues": [{"type": "model_skipped"}], "latency_seconds": 0.0, "usage": {}} for window in windows]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
            futures = [
                executor.submit(
                    run_one_window,
                    window=window,
                    blocks=blocks,
                    tags=tags,
                    config=config,
                    doc_id=doc_id,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    raw_dir=raw_dir,
                    api_key=api_key,
                    timeout=args.timeout,
                    resume=not args.no_resume,
                )
                for window in windows
            ]
            for future in concurrent.futures.as_completed(futures):
                all_results.append(future.result())
    all_results.sort(key=lambda item: item["window_id"])
    write_json(out_dir / "window_results.json", {"schema_version": "docx_question_grouper_window_results.v0.1", "windows": all_results})
    raw_packets: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    usage = Counter()
    for result in all_results:
        for packet in result.get("packets", []):
            raw_packets.append({**packet, "window_id": result["window_id"]})
        for issue in result.get("issues", []):
            issues.append({**issue, "window_id": result["window_id"]})
        usage.update({key: int(value or 0) for key, value in (result.get("usage") or {}).items() if isinstance(value, int)})
    write_json(out_dir / "raw_draft_packets.json", {"schema_version": "docx_question_grouper_raw_packets.v0.1", "packets": raw_packets})
    packets, dedupe_audit = dedupe_packets(raw_packets, windows, blocks)
    write_json(out_dir / "question_packet_candidates.json", {"schema_version": "docx_question_packet_candidates.v0.1", "packets": packets})
    write_json(out_dir / "dedupe_audit.json", {"schema_version": "docx_question_grouper_dedupe_audit.v0.1", "items": dedupe_audit})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_grouper_issues.v0.1", "issues": issues})
    render_trace(out_dir, blocks, tags, packets, issues)
    blocking_issues = [issue for issue in issues if issue.get("severity") not in {"info"}]
    summary = {
        "schema_version": "docx_question_grouper_summary.v0.1",
        "status": "needs_resolution" if blocking_issues else "ok",
        "doc_id": doc_id,
        "block_count": len(blocks),
        "window_count": len(windows),
        "raw_packet_count": len(raw_packets),
        "packet_count": len(packets),
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking_issues),
        "failed_window_count": sum(1 for result in all_results if result.get("source") == "failed"),
        "dedupe_action_count": len(dedupe_audit),
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "window_plan": safe_rel(out_dir / "window_plan.json"),
            "window_results": safe_rel(out_dir / "window_results.json"),
            "raw_draft_packets": safe_rel(out_dir / "raw_draft_packets.json"),
            "question_packet_candidates": safe_rel(out_dir / "question_packet_candidates.json"),
            "dedupe_audit": safe_rel(out_dir / "dedupe_audit.json"),
            "issues": safe_rel(out_dir / "issues.json"),
            "trace_html": safe_rel(out_dir / "question_grouper_trace.html"),
            "raw_model_responses": safe_rel(raw_dir),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX question_content sliding-window grouper v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--core-blocks", type=int, default=0)
    parser.add_argument("--stride-blocks", type=int, default=0)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
