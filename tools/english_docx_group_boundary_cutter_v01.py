from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_boundary_cutter_v01.json"
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


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def compact_text(value: str, limit: int) -> str:
    text = str(value or "").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return -1


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


def load_blocks(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = read_json(path)
    blocks = payload.get("blocks") or []
    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or f"b_{index:06d}")
        normalized.append(
            {
                "block_id": block_id,
                "source_order": index,
                "source_block_type": str(block.get("source_block_type") or "docx_block"),
                "display_markdown": str(block.get("display_markdown") or block.get("markdown") or ""),
                "plain_text_lossy": str(block.get("plain_text_lossy") or block.get("text") or ""),
                "asset_ref_count": len(block.get("asset_refs") or []),
                "blank_count": len(block.get("blank_refs") or []),
                "response_area_count": len(block.get("response_area_refs") or []),
                "content_loss_flags": list(block.get("content_loss_flags") or []),
            }
        )
    return normalized, payload


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
                window_id=f"w_{index:04d}",
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


def block_for_model(block: dict[str, Any], scope: str, preview_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "scope": scope,
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "display_markdown": compact_text(block["display_markdown"], preview_chars),
        "asset_ref_count": block["asset_ref_count"],
        "blank_count": block["blank_count"],
        "response_area_count": block["response_area_count"],
        "content_loss_flags": block["content_loss_flags"],
    }


def build_window_payload(doc_id: str, window: Window, blocks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    preview_chars = int((config.get("window_policy") or {}).get("max_block_preview_chars") or 900)
    payload = {
        "doc_id": doc_id,
        "window_id": window.window_id,
        "prompt_version": config.get("prompt_version"),
        "core_block_ids": [blocks[index]["block_id"] for index in range(window.core_start, window.core_end_exclusive)],
        "previous_tail_blocks": [],
        "current_blocks": [],
        "next_head_blocks": [],
    }
    for index in range(window.input_start, window.input_end_exclusive):
        scope = "previous_tail" if index < window.core_start else ("next_head" if index >= window.core_end_exclusive else "current")
        payload[f"{scope}_blocks"].append(block_for_model(blocks[index], scope, preview_chars))
    return payload


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
        "ok": parsed is not None,
        "parsed": parsed,
        "raw_content": raw_content,
        "raw_response": raw_response,
        "parse_error": parse_error,
        "usage": raw_response.get("usage", {}),
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_window_result(parsed: dict[str, Any], current_ids: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    current = set(current_ids)
    accounted: dict[str, int] = Counter()
    for item in parsed.get("block_accounting") or []:
        bid = str(item.get("block_id") or "")
        if bid:
            accounted[bid] += 1
    for bid in sorted(current - set(accounted), key=source_order):
        issues.append({"type": "unaccounted_current_block", "severity": "warning", "block_id": bid})
    for bid, count in sorted(accounted.items(), key=lambda pair: source_order(pair[0])):
        if bid not in current:
            issues.append({"type": "non_current_block_accounted", "severity": "warning", "block_id": bid})
        if count > 1:
            issues.append({"type": "duplicate_block_accounting", "severity": "warning", "block_id": bid, "count": count})
    for field in ["group_start_events", "group_end_events"]:
        for item in parsed.get(field) or []:
            bid = str(item.get("block_id") or "")
            if bid and bid not in current:
                issues.append({"type": f"non_current_{field}", "severity": "warning", "block_id": bid})
    return issues


def run_one_window(
    *,
    window: Window,
    blocks: list[dict[str, Any]],
    config: dict[str, Any],
    doc_id: str,
    system_prompt: str,
    user_template: str,
    api_key: str,
    raw_dir: Path,
    timeout: int,
    max_attempts: int,
    no_resume: bool,
) -> dict[str, Any]:
    payload = build_window_payload(doc_id, window, blocks, config)
    user_prompt = render_template(
        user_template,
        {
            "doc_id": doc_id,
            "window_id": window.window_id,
            "window_payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
        },
    )
    prompt_path = raw_dir / f"{window.window_id}.prompt.json"
    response_path = raw_dir / f"{window.window_id}.response.json"
    parsed_path = raw_dir / f"{window.window_id}.parsed.json"
    if response_path.exists() and parsed_path.exists() and not no_resume:
        parsed = read_json(parsed_path)
        return {
            "window_id": window.window_id,
            "source": "resume",
            "payload": payload,
            "parsed": parsed,
            "issues": validate_window_result(parsed, payload["core_block_ids"]),
            "usage": {},
            "latency_seconds": 0.0,
        }
    write_json(prompt_path, {"window_payload": payload, "system_prompt": system_prompt, "user_prompt": user_prompt})
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            model = call_model(config, system_prompt, user_prompt, api_key, timeout)
            write_json(response_path, model)
            if model["ok"] and isinstance(model["parsed"], dict):
                parsed = model["parsed"]
                write_json(parsed_path, parsed)
                return {
                    "window_id": window.window_id,
                    "source": "model",
                    "attempt": attempt,
                    "payload": payload,
                    "parsed": parsed,
                    "issues": validate_window_result(parsed, payload["core_block_ids"]),
                    "usage": model.get("usage", {}),
                    "latency_seconds": model.get("latency_seconds", 0.0),
                }
            last_error = str(model.get("parse_error") or "parse_failed")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
    return {
        "window_id": window.window_id,
        "source": "failed",
        "payload": payload,
        "parsed": {},
        "issues": [{"type": "window_failed", "severity": "error", "error": last_error}],
        "usage": {},
        "latency_seconds": 0.0,
    }


def confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(value), 0)


def collect_events(results: list[dict[str, Any]]) -> dict[str, Any]:
    starts: list[dict[str, Any]] = []
    ends: list[dict[str, Any]] = []
    accounting: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for result in results:
        wid = result["window_id"]
        parsed = result.get("parsed") or {}
        for item in parsed.get("group_start_events") or []:
            starts.append({"window_id": wid, **item})
        for item in parsed.get("group_end_events") or []:
            ends.append({"window_id": wid, **item})
        for item in parsed.get("block_accounting") or []:
            accounting.append({"window_id": wid, **item})
        for item in parsed.get("uncertain_blocks") or []:
            uncertain.append({"window_id": wid, **item})
        for issue in result.get("issues") or []:
            issues.append({"window_id": wid, **issue})
    return {
        "schema_version": "english_docx_group_boundary_events.v0.1",
        "group_start_events": starts,
        "group_end_events": ends,
        "block_accounting": accounting,
        "uncertain_blocks": uncertain,
        "issues": issues,
    }


def choose_events(items: list[dict[str, Any]], min_votes: int) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        bid = str(item.get("block_id") or "")
        if bid:
            by_id[bid].append(item)
    chosen: list[dict[str, Any]] = []
    for bid, votes in by_id.items():
        if len(votes) < min_votes:
            continue
        best = sorted(votes, key=lambda x: confidence_rank(str(x.get("confidence"))), reverse=True)[0]
        chosen.append(
            {
                "block_id": bid,
                "vote_count": len(votes),
                "best_confidence": best.get("confidence", "unknown"),
                "group_kind": best.get("group_kind", ""),
                "evidence": best.get("evidence", ""),
                "evidence_block_ids": best.get("evidence_block_ids", []),
                "windows": sorted({str(v.get("window_id")) for v in votes}),
            }
        )
    return sorted(chosen, key=lambda x: source_order(x["block_id"]))


def dominant_counter_value(counter: Counter) -> str:
    if not counter:
        return ""
    return sorted(counter.items(), key=lambda pair: (-pair[1], str(pair[0])))[0][0]


def summarize_accounting(accounting: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_block: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in accounting:
        bid = str(item.get("block_id") or "")
        if bid:
            by_block[bid].append(item)

    summaries: dict[str, dict[str, Any]] = {}
    for bid, votes in by_block.items():
        role_counts = Counter(str(v.get("role") or "") for v in votes if v.get("role"))
        boundary_role_counts = Counter(str(v.get("boundary_role") or "") for v in votes if v.get("boundary_role"))
        belongs_counts = Counter(str(v.get("belongs_to") or "") for v in votes if v.get("belongs_to"))
        summaries[bid] = {
            "block_id": bid,
            "vote_count": len(votes),
            "roles": dict(role_counts),
            "boundary_roles": dict(boundary_role_counts),
            "belongs_to": dict(belongs_counts),
            "dominant_role": dominant_counter_value(role_counts),
            "dominant_boundary_role": dominant_counter_value(boundary_role_counts),
            "dominant_belongs_to": dominant_counter_value(belongs_counts),
            "windows": sorted({str(v.get("window_id")) for v in votes if v.get("window_id")}),
            "evidence_samples": [str(v.get("evidence") or "") for v in votes[:3] if v.get("evidence")],
        }
    return summaries


def count_selected(counter_payload: dict[str, Any], selected: set[str]) -> int:
    return sum(int(value) for key, value in counter_payload.items() if key in selected)


def adjudicate_chosen_events(
    starts: list[dict[str, Any]],
    ends: list[dict[str, Any]],
    accounting: list[dict[str, Any]],
    aggregation_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    summaries = summarize_accounting(accounting)
    if not bool(aggregation_policy.get("adjudication_enabled", False)):
        return starts, ends, {
            "enabled": False,
            "block_accounting_summary": summaries,
            "accepted_start_events": starts,
            "rejected_start_events": [],
            "accepted_end_events": ends,
            "rejected_end_events": [],
        }

    opening_boundary_roles = set(aggregation_policy.get("opening_boundary_roles") or ["opening_anchor"])
    veto_boundary_roles = set(aggregation_policy.get("veto_boundary_roles") or ["region_context", "document_context", "support_anchor", "spacer", "waste"])
    fallback_opening_roles = set(aggregation_policy.get("fallback_opening_roles") or ["group_heading", "passage", "question_items", "instruction"])
    fallback_veto_roles = set(aggregation_policy.get("fallback_veto_roles") or ["document_title", "section_heading", "answer_marker", "answer", "guide", "analysis", "response_area", "waste"])
    opening_belongs_to = set(aggregation_policy.get("opening_belongs_to") or ["new_group_in_current", "visible_group_start"])
    veto_belongs_to = set(aggregation_policy.get("veto_belongs_to") or ["context_only", "previous_group", "waste"])

    def adjudicate_start(item: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        bid = str(item.get("block_id") or "")
        summary = summaries.get(bid) or {}
        boundary_roles = summary.get("boundary_roles") or {}
        roles = summary.get("roles") or {}
        belongs_to = summary.get("belongs_to") or {}
        opening_boundary_votes = count_selected(boundary_roles, opening_boundary_roles)
        veto_boundary_votes = count_selected(boundary_roles, veto_boundary_roles)
        opening_fallback_votes = count_selected(roles, fallback_opening_roles) + count_selected(belongs_to, opening_belongs_to)
        veto_fallback_votes = count_selected(roles, fallback_veto_roles) + count_selected(belongs_to, veto_belongs_to)
        has_boundary_votes = bool(boundary_roles)

        if has_boundary_votes and veto_boundary_votes > opening_boundary_votes:
            return False, {
                "reason": "boundary_role_veto",
                "opening_boundary_votes": opening_boundary_votes,
                "veto_boundary_votes": veto_boundary_votes,
                "accounting_summary": summary,
            }
        if not has_boundary_votes and veto_fallback_votes > opening_fallback_votes:
            return False, {
                "reason": "fallback_role_belongs_to_veto",
                "opening_fallback_votes": opening_fallback_votes,
                "veto_fallback_votes": veto_fallback_votes,
                "accounting_summary": summary,
            }
        return True, {
            "reason": "accepted",
            "opening_boundary_votes": opening_boundary_votes,
            "veto_boundary_votes": veto_boundary_votes,
            "opening_fallback_votes": opening_fallback_votes,
            "veto_fallback_votes": veto_fallback_votes,
            "accounting_summary": summary,
        }

    def adjudicate_end(item: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        bid = str(item.get("block_id") or "")
        summary = summaries.get(bid) or {}
        boundary_roles = summary.get("boundary_roles") or {}
        roles = summary.get("roles") or {}
        belongs_to = summary.get("belongs_to") or {}
        closure_boundary_votes = count_selected(boundary_roles, {"unit_content", "support_anchor", "opening_anchor"})
        veto_boundary_votes = count_selected(boundary_roles, {"region_context", "document_context", "spacer", "waste"})
        closure_fallback_votes = count_selected(roles, {"passage", "question_items", "options", "answer", "guide", "analysis", "instruction", "response_area", "image", "continuation"})
        veto_fallback_votes = count_selected(roles, {"document_title", "section_heading", "answer_marker", "waste"}) + count_selected(belongs_to, {"context_only", "waste"})
        has_boundary_votes = bool(boundary_roles)

        if has_boundary_votes and veto_boundary_votes > closure_boundary_votes:
            return False, {
                "reason": "boundary_role_veto",
                "closure_boundary_votes": closure_boundary_votes,
                "veto_boundary_votes": veto_boundary_votes,
                "accounting_summary": summary,
            }
        if not has_boundary_votes and veto_fallback_votes > closure_fallback_votes:
            return False, {
                "reason": "fallback_role_belongs_to_veto",
                "closure_fallback_votes": closure_fallback_votes,
                "veto_fallback_votes": veto_fallback_votes,
                "accounting_summary": summary,
            }
        return True, {
            "reason": "accepted",
            "closure_boundary_votes": closure_boundary_votes,
            "veto_boundary_votes": veto_boundary_votes,
            "closure_fallback_votes": closure_fallback_votes,
            "veto_fallback_votes": veto_fallback_votes,
            "accounting_summary": summary,
        }

    accepted_starts: list[dict[str, Any]] = []
    rejected_starts: list[dict[str, Any]] = []
    for item in starts:
        accepted, decision = adjudicate_start(item)
        decorated = {**item, "adjudication": decision}
        if accepted:
            accepted_starts.append(decorated)
        else:
            rejected_starts.append(decorated)

    end_orders = {source_order(item["block_id"]) for item in ends}
    collapsed_starts: list[dict[str, Any]] = []
    for item in accepted_starts:
        if not collapsed_starts:
            collapsed_starts.append(item)
            continue
        previous = collapsed_starts[-1]
        previous_order = source_order(previous["block_id"])
        current_order = source_order(item["block_id"])
        has_end_between = any(previous_order <= end_order < current_order for end_order in end_orders)
        previous_summary = (previous.get("adjudication") or {}).get("accounting_summary") or {}
        current_summary = (item.get("adjudication") or {}).get("accounting_summary") or {}
        previous_boundary = previous_summary.get("boundary_roles") or {}
        current_boundary = current_summary.get("boundary_roles") or {}
        current_roles = current_summary.get("roles") or {}
        previous_is_opening = count_selected(previous_boundary, opening_boundary_roles) > 0
        current_can_be_body_start = (
            count_selected(current_boundary, {"unit_content", "opening_anchor"}) > 0
            and count_selected(current_roles, {"passage", "instruction", "question_items", "group_heading"}) > 0
        )
        if not has_end_between and 0 < current_order - previous_order <= 3 and previous_is_opening and current_can_be_body_start:
            rejected_starts.append(
                {
                    **item,
                    "adjudication": {
                        **(item.get("adjudication") or {}),
                        "reason": "adjacent_duplicate_opening_anchor",
                        "kept_start_block_id": previous["block_id"],
                        "accounting_summary": current_summary,
                    },
                }
            )
            continue
        collapsed_starts.append(item)
    accepted_starts = collapsed_starts

    accepted_ends: list[dict[str, Any]] = []
    rejected_ends: list[dict[str, Any]] = []
    for item in ends:
        accepted, decision = adjudicate_end(item)
        decorated = {**item, "adjudication": decision}
        if accepted:
            accepted_ends.append(decorated)
        else:
            rejected_ends.append(decorated)

    return accepted_starts, accepted_ends, {
        "enabled": True,
        "block_accounting_summary": summaries,
        "accepted_start_events": accepted_starts,
        "rejected_start_events": rejected_starts,
        "accepted_end_events": accepted_ends,
        "rejected_end_events": rejected_ends,
    }


def assemble_model_groups(
    blocks: list[dict[str, Any]],
    starts: list[dict[str, Any]],
    ends: list[dict[str, Any]],
    allow_missing_end: bool,
    missing_end_status: str,
    adjudication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    order_to_block = {block["source_order"]: block for block in blocks}
    start_orders = [source_order(item["block_id"]) for item in starts]
    end_orders = [source_order(item["block_id"]) for item in ends]
    ends_by_order = {source_order(item["block_id"]): item for item in ends}
    accounting_summary = (adjudication or {}).get("block_accounting_summary") or {}

    def is_substantive_block(block_id: str) -> bool:
        summary = accounting_summary.get(block_id) or {}
        boundary_roles = summary.get("boundary_roles") or {}
        roles = summary.get("roles") or {}
        if count_selected(boundary_roles, {"spacer", "waste", "region_context", "document_context"}) > 0:
            return False
        if count_selected(roles, {"waste", "document_title", "section_heading"}) > 0:
            return False
        return True

    def previous_substantive_order(start_order: int, exclusive_end_order: int) -> int:
        for candidate in range(exclusive_end_order - 1, start_order - 1, -1):
            block = order_to_block.get(candidate)
            if not block:
                continue
            if str(block.get("display_markdown") or "").strip() and is_substantive_block(block["block_id"]):
                return candidate
        return max(start_order, exclusive_end_order - 1)

    def can_extend_end(block_id: str) -> bool:
        summary = accounting_summary.get(block_id) or {}
        boundary_roles = summary.get("boundary_roles") or {}
        roles = summary.get("roles") or {}
        belongs_to = summary.get("belongs_to") or {}
        if count_selected(boundary_roles, {"region_context", "document_context", "spacer", "waste"}) > 0:
            return False
        if count_selected(roles, {"document_title", "section_heading", "waste"}) > 0:
            return False
        support_votes = count_selected(boundary_roles, {"support_anchor", "unit_content"})
        content_votes = count_selected(roles, {"answer", "guide", "analysis", "response_area", "image", "continuation", "options", "question_items", "passage", "instruction"})
        belongs_votes = count_selected(belongs_to, {"previous_group", "visible_group_start"})
        return (support_votes + content_votes) > 0 and belongs_votes > 0

    groups: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        start_order = source_order(start["block_id"])
        next_start_order = start_orders[index + 1] if index + 1 < len(start_orders) else len(blocks)
        candidate_end_orders = [value for value in end_orders if start_order <= value < next_start_order]
        if candidate_end_orders:
            end_order = max(candidate_end_orders)
            end = ends_by_order[end_order]
            status = "ok"
            end_source = "model_end_event"
        elif allow_missing_end:
            end_order = previous_substantive_order(start_order, next_start_order)
            end = {}
            if next_start_order < len(blocks):
                status = "ok"
                end_source = "inferred_before_next_start"
            else:
                status = missing_end_status
                end_source = "fallback_before_document_end"
                issues.append({"type": "missing_model_end", "severity": "warning", "start_block_id": start["block_id"], "fallback_end_block_id": order_to_block[end_order]["block_id"]})
        else:
            issues.append({"type": "missing_model_end", "severity": "error", "start_block_id": start["block_id"]})
            continue
        original_end_order = end_order
        scan_order = end_order + 1
        while scan_order < next_start_order:
            block = order_to_block.get(scan_order)
            if not block:
                scan_order += 1
                continue
            if not can_extend_end(block["block_id"]):
                break
            end_order = scan_order
            scan_order += 1
        if end_order != original_end_order:
            end_source = f"{end_source}+accounting_support_extension"
        source_block_ids = [order_to_block[i]["block_id"] for i in range(start_order, end_order + 1) if i in order_to_block]
        groups.append(
            {
                "group_id": f"eg_{len(groups) + 1:04d}",
                "status": status,
                "group_kind": start.get("group_kind") or "mixed_or_unknown",
                "start_block_id": start["block_id"],
                "end_block_id": order_to_block[end_order]["block_id"],
                "source_block_ids": source_block_ids,
                "block_count": len(source_block_ids),
                "start_vote_count": start.get("vote_count"),
                "start_confidence": start.get("best_confidence"),
                "start_windows": start.get("windows", []),
                "start_evidence": start.get("evidence", ""),
                "end_vote_count": end.get("vote_count", 0),
                "end_confidence": end.get("best_confidence", ""),
                "end_windows": end.get("windows", []),
                "end_evidence": end.get("evidence", ""),
                "end_source": end_source,
            }
        )
    covered = {bid for group in groups for bid in group.get("source_block_ids", [])}
    nonempty = {block["block_id"] for block in blocks if str(block.get("display_markdown") or "").strip()}
    return {
        "schema_version": "english_docx_group_boundary_assembled_groups.v0.1",
        "groups": groups,
        "issues": issues,
        "uncovered_nonempty_block_ids": sorted(nonempty - covered, key=source_order),
        "chosen_start_events": starts,
        "chosen_end_events": ends,
        "adjudication": adjudication or {},
    }


def make_trace_html(out_dir: Path, assembled: dict[str, Any], events: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    by_id = {block["block_id"]: block for block in blocks}

    def preview(bid: str) -> str:
        return html.escape(compact_text((by_id.get(bid) or {}).get("display_markdown", ""), 180))

    rows = []
    for group in assembled.get("groups") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(group['group_id'])}</td>"
            f"<td>{html.escape(group.get('group_kind',''))}</td>"
            f"<td>{html.escape(group['start_block_id'])} - {html.escape(group['end_block_id'])}</td>"
            f"<td>{html.escape(group.get('status',''))}</td>"
            f"<td>{group.get('block_count')}</td>"
            f"<td>{html.escape(str(group.get('start_confidence','')))} / {html.escape(str(group.get('end_confidence','')))}</td>"
            f"<td>{preview(group['start_block_id'])}</td>"
            f"<td>{preview(group['end_block_id'])}</td>"
            "</tr>"
        )
    issue_rows = [f"<li>{html.escape(json.dumps(issue, ensure_ascii=False))}</li>" for issue in (events.get("issues") or [])[:200]]
    html_text = f"""<!doctype html>
<meta charset="utf-8">
<title>English DOCX Group Boundary Trace</title>
<style>
body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; background: #f4f7fb; color: #0f172a; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }}
th {{ background: #e2e8f0; }}
</style>
<h1>English DOCX Group Boundary Trace</h1>
<p>groups={len(assembled.get('groups') or [])} starts={len(events.get('group_start_events') or [])} ends={len(events.get('group_end_events') or [])} issues={len(events.get('issues') or [])}</p>
<table>
<thead><tr><th>group</th><th>kind</th><th>range</th><th>status</th><th>blocks</th><th>confidence</th><th>start preview</th><th>end preview</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<h2>Window Issues</h2>
<ul>{''.join(issue_rows)}</ul>
"""
    (out_dir / "group_boundary_trace.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks, source_payload = load_blocks(args.block_stream)
    doc_id = args.doc_id or Path(args.block_stream).parent.name
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/english_docx_group_boundary_cutter_v0_1")
    out_dir = out_root / args.run_id / doc_id
    raw_dir = out_dir / "raw_model_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)
    policy = config.get("window_policy", {}) or {}
    windows = plan_windows(
        blocks,
        int(args.core_blocks or policy.get("core_blocks") or 26),
        int(args.stride_blocks or policy.get("stride_blocks") or 16),
        int(policy.get("previous_tail_blocks") or 8),
        int(policy.get("next_head_blocks") or 10),
    )
    if args.window_start:
        windows = windows[args.window_start :]
    if args.max_windows:
        windows = windows[: args.max_windows]
    write_json(out_dir / "window_plan.json", {"schema_version": "english_docx_group_boundary_window_plan.v0.1", "windows": [w.__dict__ for w in windows]})
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    max_attempts = int(args.max_window_attempts or (config.get("runner") or {}).get("max_window_attempts") or 1)
    if args.no_model:
        results = [
            {
                "window_id": w.window_id,
                "source": "no_model",
                "payload": build_window_payload(doc_id, w, blocks, config),
                "parsed": {},
                "issues": [{"type": "model_skipped", "severity": "error"}],
                "usage": {},
            }
            for w in windows
        ]
    else:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
            futures = [
                executor.submit(
                    run_one_window,
                    window=w,
                    blocks=blocks,
                    config=config,
                    doc_id=doc_id,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    api_key=api_key,
                    raw_dir=raw_dir,
                    timeout=args.timeout,
                    max_attempts=max_attempts,
                    no_resume=args.no_resume,
                )
                for w in windows
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda x: x["window_id"])
    write_json(out_dir / "window_results.json", {"schema_version": "english_docx_group_boundary_window_results.v0.1", "windows": results})
    events = collect_events(results)
    agg = config.get("aggregation_policy") or {}
    starts = choose_events(events.get("group_start_events") or [], int(agg.get("min_start_votes") or 1))
    ends = choose_events(events.get("group_end_events") or [], int(agg.get("min_end_votes") or 1))
    adjudicated_starts, adjudicated_ends, adjudication = adjudicate_chosen_events(
        starts,
        ends,
        events.get("block_accounting") or [],
        agg,
    )
    events["adjudication"] = adjudication
    assembled = assemble_model_groups(
        blocks,
        adjudicated_starts,
        adjudicated_ends,
        bool(agg.get("allow_missing_end", True)),
        str(agg.get("missing_end_status") or "needs_resolution_missing_model_end"),
        adjudication,
    )
    write_json(out_dir / "group_boundary_events.json", events)
    write_json(out_dir / "assembled_groups.json", assembled)
    make_trace_html(out_dir, assembled, events, blocks)
    usage = Counter()
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    issue_counts = Counter(issue.get("type", "unknown") for issue in (events.get("issues") or []) + (assembled.get("issues") or []))
    failed_window_count = sum(1 for r in results if r.get("source") == "failed")
    skipped_window_count = sum(1 for r in results if r.get("source") == "no_model")
    missing_end_count = sum(1 for group in assembled.get("groups") or [] if group.get("status") == str(agg.get("missing_end_status") or "needs_resolution_missing_model_end"))
    summary = {
        "schema_version": "english_docx_group_boundary_cutter_summary.v0.1",
        "pipeline_id": "english_docx_group_boundary_cutter_v01",
        "run_id": args.run_id,
        "doc_id": doc_id,
        "status": "ok" if failed_window_count == 0 and skipped_window_count == 0 and missing_end_count == 0 else "needs_resolution",
        "source_block_stream": safe_rel(args.block_stream),
        "source_docx": source_payload.get("source_docx", ""),
        "block_count": len(blocks),
        "window_count": len(windows),
        "group_start_event_count": len(events.get("group_start_events") or []),
        "group_end_event_count": len(events.get("group_end_events") or []),
        "chosen_start_event_count": len(starts),
        "chosen_end_event_count": len(ends),
        "accepted_start_event_count": len(adjudicated_starts),
        "accepted_end_event_count": len(adjudicated_ends),
        "rejected_start_event_count": len((adjudication.get("rejected_start_events") if isinstance(adjudication, dict) else []) or []),
        "rejected_end_event_count": len((adjudication.get("rejected_end_events") if isinstance(adjudication, dict) else []) or []),
        "assembled_group_count": len(assembled.get("groups") or []),
        "missing_model_end_group_count": missing_end_count,
        "uncovered_nonempty_block_count": len(assembled.get("uncovered_nonempty_block_ids") or []),
        "issue_count": len(events.get("issues") or []) + len(assembled.get("issues") or []),
        "issue_counts": dict(issue_counts),
        "failed_window_count": failed_window_count,
        "skipped_window_count": skipped_window_count,
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "window_plan": safe_rel(out_dir / "window_plan.json"),
            "window_results": safe_rel(out_dir / "window_results.json"),
            "group_boundary_events": safe_rel(out_dir / "group_boundary_events.json"),
            "assembled_groups": safe_rel(out_dir / "assembled_groups.json"),
            "group_boundary_trace": safe_rel(out_dir / "group_boundary_trace.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Model-owned English DOCX group boundary cutter.")
    parser.add_argument("--block-stream", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--max-window-attempts", type=int, default=0)
    parser.add_argument("--core-blocks", type=int, default=0)
    parser.add_argument("--stride-blocks", type=int, default=0)
    parser.add_argument("--window-start", type=int, default=0)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
