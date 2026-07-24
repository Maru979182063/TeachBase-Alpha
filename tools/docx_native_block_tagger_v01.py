from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_native_block_tagger_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

PRIMARY_ROLES = {
    "section",
    "instruction",
    "question_content",
    "knowledge_like",
    "decorative",
    "document_meta",
    "blank",
    "unknown",
}

CONTENT_TAGS = {"text", "formula", "visual", "table"}
NOISE_TAGS = {
    "logo",
    "watermark",
    "header_footer",
    "ad_banner",
    "decorative_image",
    "page_number",
}

ROLE_PRIORITY = {
    "unknown": 0,
    "blank": 1,
    "decorative": 2,
    "document_meta": 3,
    "instruction": 4,
    "section": 5,
    "knowledge_like": 6,
    "question_content": 10,
}


DEFAULT_SYSTEM_PROMPT = "你是 TeachBase DOCX native 的块级内容打标器。只返回 tag_rows JSON。"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def load_system_prompt(config: dict[str, Any]) -> str:
    prompt_path = str(config.get("system_prompt_path") or "").strip()
    if not prompt_path:
        return DEFAULT_SYSTEM_PROMPT
    path = Path(prompt_path)
    if not path.is_absolute():
        path = ROOT / path
    return path.read_text(encoding="utf-8")


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
    return ("".join(chars).strip("_") or "docx_block_tagger")[:96]


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def source_order(block_id: str) -> int:
    try:
        return int(block_id.rsplit("_", 1)[-1])
    except ValueError:
        return -1


def structural_hints_for(block: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    text = str(block.get("display_markdown") or block.get("markdown") or block.get("text") or "").strip()
    if not text:
        hints.append("blank")
    if block.get("source_block_type") == "docx_table":
        hints.append("table_block")
    if int(block.get("formula_count") or 0) > 0:
        hints.append("has_formula")
    if block.get("image_refs") or block.get("asset_refs"):
        hints.append("has_image")
    if block.get("content_loss_flags"):
        hints.append("has_content_loss_flags")
    return hints


def content_tags_for(block: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    text = str(block.get("display_markdown") or block.get("markdown") or block.get("text") or "").strip()
    if text:
        tags.append("text")
    if int(block.get("formula_count") or 0) > 0:
        tags.append("formula")
    if block.get("source_block_type") == "docx_table":
        tags.append("table")
    if block.get("image_refs") or block.get("asset_refs"):
        tags.append("visual")
    return tags


def build_blocks(paragraph_stream: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for order, block in enumerate(paragraph_stream.get("paragraphs", []) or []):
        markdown = str(block.get("display_markdown") or block.get("markdown") or "")
        text = str(block.get("plain_text_lossy") or block.get("text") or "")
        image_refs = [item for item in (block.get("image_refs") or block.get("asset_refs") or []) if isinstance(item, dict)]
        inline_glyph_refs = [item for item in (block.get("inline_glyph_refs") or []) if isinstance(item, dict)]
        formula_refs = [item for item in (block.get("formula_findings") or block.get("formula_refs") or []) if isinstance(item, dict)]
        source_type = str(block.get("source_block_type") or "docx_block")
        blocks.append(
            {
                "block_id": f"b_{order:06d}",
                "source_order": order,
                "source_block_type": source_type,
                "paragraph_index": block.get("paragraph_index", order),
                "text": text,
                "display_markdown": markdown,
                "formula_count": int(block.get("formula_count") or len(formula_refs) or 0),
                "formula_refs": formula_refs,
                "image_refs": image_refs,
                "inline_glyph_refs": inline_glyph_refs,
                "content_tags": content_tags_for(block),
                "structural_hints": structural_hints_for(block),
                "qa_status": block.get("qa_status", "unknown"),
                "content_loss_flags": block.get("content_loss_flags", []),
                "content_hash": sha256_text(json.dumps({"text": text, "display_markdown": markdown}, ensure_ascii=False, sort_keys=True)),
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


def plan_windows(blocks: list[dict[str, Any]], core: int, left: int, right: int, stride: int | None = None) -> list[Window]:
    windows: list[Window] = []
    start = 0
    index = 0
    step = max(1, int(stride or core))
    while start < len(blocks):
        end = min(start + core, len(blocks))
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
        start += step
        index += 1
    return windows


def block_for_model(block: dict[str, Any], preview_chars: int, scope: str) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "scope": scope,
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "text_preview": compact_text(block.get("text", ""), preview_chars),
        "display_markdown_preview": compact_text(block.get("display_markdown", ""), preview_chars),
        "formula_count": block.get("formula_count", 0),
        "image_ref_count": len(block.get("image_refs", []) or []),
        "content_tags": block.get("content_tags", []),
        "structural_hints": block.get("structural_hints", []),
        "qa_status": block.get("qa_status", "unknown"),
        "content_loss_flags": block.get("content_loss_flags", []),
    }


def build_payload(window: Window, blocks: list[dict[str, Any]], preview_chars: int, config_hash: str) -> dict[str, Any]:
    core_blocks = blocks[window.core_start : window.core_end_exclusive]
    left_blocks = blocks[window.input_start : window.core_start]
    right_blocks = blocks[window.core_end_exclusive : window.input_end_exclusive]
    return {
        "task": "tag DOCX native blocks only; do not group or rewrite",
        "schema_version": "docx_native_block_tagger_v01",
        "config_hash": config_hash,
        "window_id": window.window_id,
        "core_block_ids": [block["block_id"] for block in core_blocks],
        "left_context_block_ids": [block["block_id"] for block in left_blocks],
        "right_context_block_ids": [block["block_id"] for block in right_blocks],
        "allowed_primary_roles": sorted(PRIMARY_ROLES),
        "allowed_content_tags": sorted(CONTENT_TAGS),
        "allowed_noise_tags": sorted(NOISE_TAGS),
        "blocks": (
            [block_for_model(block, preview_chars, "left_context") for block in left_blocks]
            + [block_for_model(block, preview_chars, "core") for block in core_blocks]
            + [block_for_model(block, preview_chars, "right_context") for block in right_blocks]
        ),
        "required_output": {
            "window_id": window.window_id,
            "tag_rows": [["one core block id", "one allowed_primary_role", ["text"], [], 0.0, False]],
            "qa_flags": [],
        },
    }


def call_model(api_key: str, model: str, payload: dict[str, Any], timeout: int, system_prompt: str) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ],
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    raw_response = json.loads(raw)
    raw_content = str(raw_response["choices"][0]["message"]["content"])
    parsed = json.loads(raw_content)
    return {
        "parsed": parsed,
        "raw_response": raw_response,
        "raw_content": raw_content,
        "usage": raw_response.get("usage", {}),
        "finish_reason": (raw_response.get("choices") or [{}])[0].get("finish_reason", ""),
        "latency_seconds": round(time.time() - started, 3),
    }


def normalize_tag(item: dict[str, Any], block_id: str) -> dict[str, Any]:
    role = str(item.get("primary_role") or "unknown")
    if role in {"question_like", "subquestion_like", "answer_like", "analysis_like", "solution_like", "explanation_like", "shared_material"}:
        role = "question_content"
    if role not in PRIMARY_ROLES:
        role = "unknown"
    content_tags = [str(tag) for tag in item.get("content_tags", []) or [] if str(tag) in CONTENT_TAGS]
    noise_tags = [str(tag) for tag in item.get("noise_tags", []) or [] if str(tag) in NOISE_TAGS]
    secondary_roles = [str(tag) for tag in item.get("secondary_roles", []) or [] if str(tag) in PRIMARY_ROLES and str(tag) != role]
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "block_id": block_id,
        "primary_role": role,
        "secondary_roles": secondary_roles,
        "content_tags": content_tags,
        "noise_tags": noise_tags,
        "confidence": confidence,
        "needs_resolution": bool(item.get("needs_resolution", item.get("needs_review", False))) or role == "unknown" or confidence < 0.55,
    }


def row_to_tag_item(row: Any) -> dict[str, Any]:
    if not isinstance(row, list) or len(row) < 6:
        return {}
    return {
        "block_id": row[0],
        "primary_role": row[1],
        "content_tags": row[2],
        "noise_tags": row[3],
        "confidence": row[4],
        "needs_resolution": row[5],
        "secondary_roles": [],
    }


def fallback_tag(block_id: str, issue_type: str) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "primary_role": "unknown",
        "secondary_roles": [],
        "content_tags": [],
        "noise_tags": [],
        "confidence": 0.0,
        "needs_resolution": True,
        "fallback_issue": issue_type,
    }


def apply_objective_content_tags(tag: dict[str, Any], block: dict[str, Any] | None) -> dict[str, Any]:
    if not block:
        return tag
    source_tags = [str(item) for item in block.get("content_tags", []) or [] if str(item) in CONTENT_TAGS]
    merged = list(dict.fromkeys([*tag.get("content_tags", []), *source_tags]))
    if merged != tag.get("content_tags", []):
        tag = {**tag, "content_tags": merged, "source_content_tags_added": [item for item in source_tags if item not in tag.get("content_tags", [])]}
    return tag


def validate_window_result(window: Window, result: dict[str, Any], block_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
    core_set = set(core_ids)
    by_id: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    raw_items = result.get("block_tags")
    if raw_items is None:
        raw_items = [row_to_tag_item(row) for row in result.get("tag_rows", []) or []]
    for item in raw_items or []:
        if not isinstance(item, dict):
            issues.append({"type": "invalid_tag_shape", "window_id": window.window_id})
            continue
        block_id = str(item.get("block_id") or "")
        if block_id not in core_set:
            issues.append({"type": "tag_for_non_core_block", "window_id": window.window_id, "block_id": block_id})
            continue
        if block_id in by_id:
            issues.append({"type": "duplicate_block_tag", "window_id": window.window_id, "block_id": block_id})
            continue
        by_id[block_id] = apply_objective_content_tags(normalize_tag(item, block_id), block_by_id.get(block_id))
    for block_id in core_ids:
        if block_id not in by_id:
            issues.append({"type": "missing_block_tag", "window_id": window.window_id, "block_id": block_id})
            by_id[block_id] = apply_objective_content_tags(fallback_tag(block_id, "missing_block_tag"), block_by_id.get(block_id))
    return [by_id[block_id] for block_id in core_ids], issues


def run_one_window(
    *,
    window: Window,
    blocks: list[dict[str, Any]],
    raw_dir: Path,
    api_key: str,
    model: str,
    preview_chars: int,
    config_hash: str,
    timeout: int,
    resume: bool,
    system_prompt: str,
) -> dict[str, Any]:
    payload_path = raw_dir / f"{window.window_id}.prompt.json"
    response_path = raw_dir / f"{window.window_id}.response.json"
    content_path = raw_dir / f"{window.window_id}.content.json"
    result_path = raw_dir / f"{window.window_id}.validated.json"
    payload = build_payload(window, blocks, preview_chars, config_hash)
    write_json(payload_path, payload)
    started = time.time()
    try:
        if resume and content_path.exists():
            parsed = read_json(content_path)
            result = {"parsed": parsed, "usage": {}, "finish_reason": "replay", "latency_seconds": 0.0}
            source = "replay"
        else:
            result = call_model(api_key, model, payload, timeout, system_prompt)
            write_json(response_path, result["raw_response"])
            content_path.write_text(result["raw_content"], encoding="utf-8")
            source = "model"
        block_by_id = {block["block_id"]: block for block in blocks}
        tags, issues = validate_window_result(window, result["parsed"], block_by_id)
    except (json.JSONDecodeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, OSError) as exc:
        core_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
        tags = [fallback_tag(block_id, "window_failed") for block_id in core_ids]
        issues = [{"type": "window_failed", "window_id": window.window_id, "reason": str(exc), "block_ids": core_ids}]
        result = {"usage": {}, "finish_reason": "failed", "latency_seconds": round(time.time() - started, 3)}
        source = "failed"
    validated = {
        "window_id": window.window_id,
        "source": source,
        "tags": tags,
        "issues": issues,
        "usage": result.get("usage", {}),
        "finish_reason": result.get("finish_reason", ""),
        "latency_seconds": result.get("latency_seconds", round(time.time() - started, 3)),
    }
    write_json(result_path, validated)
    return validated


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
    return round(values[index], 3)


def reconcile_duplicate_tags(tags: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        by_id.setdefault(str(tag.get("block_id")), []).append(tag)
    reconciled: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for block_id, votes in by_id.items():
        if len(votes) == 1:
            tag = {**votes[0], "tag_vote_count": 1, "dedupe_conflict": False}
            reconciled.append(tag)
            continue
        role_scores: dict[str, dict[str, Any]] = {}
        for vote in votes:
            role = str(vote.get("primary_role") or "unknown")
            bucket = role_scores.setdefault(role, {"count": 0, "confidence_sum": 0.0})
            bucket["count"] += 1
            bucket["confidence_sum"] += float(vote.get("confidence") or 0.0)
        sorted_roles = sorted(
            role_scores.items(),
            key=lambda item: (
                item[1]["count"],
                item[1]["confidence_sum"] / max(1, item[1]["count"]),
                ROLE_PRIORITY.get(item[0], 0),
            ),
            reverse=True,
        )
        winner = sorted_roles[0][0]
        winner_votes = [vote for vote in votes if vote.get("primary_role") == winner]
        content_tags = list(dict.fromkeys(tag for vote in votes for tag in vote.get("content_tags", []) or []))
        noise_tags = list(dict.fromkeys(tag for vote in votes for tag in vote.get("noise_tags", []) or []))
        avg_confidence = sum(float(vote.get("confidence") or 0.0) for vote in winner_votes) / max(1, len(winner_votes))
        role_conflict = len(role_scores) > 1
        tied_top_roles = [
            role
            for role, data in role_scores.items()
            if data["count"] == role_scores[winner]["count"]
        ]
        conflict_type = ""
        role_set = set(role_scores)
        if role_conflict:
            if "question_content" in role_set:
                conflict_type = "question_content_boundary"
            else:
                conflict_type = "role_boundary_conflict"
        needs_resolution = role_conflict or any(bool(vote.get("needs_resolution", vote.get("needs_review"))) for vote in votes) or avg_confidence < 0.7 or winner == "unknown"
        merged = {
            **winner_votes[0],
            "primary_role": winner,
            "content_tags": content_tags,
            "noise_tags": noise_tags,
            "confidence": round(avg_confidence, 3),
            "needs_resolution": bool(needs_resolution),
            "tag_vote_count": len(votes),
            "dedupe_conflict": bool(role_conflict),
            "conflict_type": conflict_type,
            "role_votes": {role: data["count"] for role, data in sorted(role_scores.items())},
            "tied_top_roles": sorted(tied_top_roles),
        }
        reconciled.append(merged)
        audits.append(
            {
                "block_id": block_id,
                "vote_count": len(votes),
                "winner": winner,
                "role_votes": merged["role_votes"],
                "dedupe_conflict": bool(role_conflict),
                "conflict_type": conflict_type,
                "needs_resolution": bool(needs_resolution),
                "selected_primary_role": winner,
                "tied_top_roles": sorted(tied_top_roles),
                "votes": [
                    {
                        "primary_role": vote.get("primary_role"),
                        "confidence": vote.get("confidence"),
                        "needs_resolution": vote.get("needs_resolution", vote.get("needs_review")),
                        "content_tags": vote.get("content_tags"),
                        "noise_tags": vote.get("noise_tags"),
                    }
                    for vote in votes
                ],
            }
        )
    reconciled.sort(key=lambda tag: source_order(str(tag.get("block_id"))))
    audits.sort(key=lambda item: source_order(str(item.get("block_id"))))
    return reconciled, audits


def build_summary(
    *,
    out_dir: Path,
    paragraph_stream_path: Path,
    blocks: list[dict[str, Any]],
    windows: list[Window],
    tags: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    usage_totals: dict[str, int],
    window_results: list[dict[str, Any]],
    tag_vote_count: int,
    dedupe_audit: list[dict[str, Any]],
    started_at: float,
    model: str,
    config: dict[str, Any],
    system_prompt: str,
) -> dict[str, Any]:
    role_counts = Counter(tag["primary_role"] for tag in tags)
    noise_counts = Counter(noise for tag in tags for noise in tag.get("noise_tags", []))
    content_counts = Counter(content for tag in tags for content in tag.get("content_tags", []))
    latencies = [float(item.get("latency_seconds") or 0.0) for item in window_results if item.get("source") == "model"]
    failed_windows = [item["window_id"] for item in window_results if item.get("source") == "failed"]
    resolution_blocks = [tag["block_id"] for tag in tags if tag.get("needs_resolution")]
    status = "needs_resolution" if issues or failed_windows or resolution_blocks else "ok"
    return {
        "schema_version": "docx_native_block_tagger_summary.v0.1",
        "status": status,
        "source_paragraph_stream": str(paragraph_stream_path),
        "block_count": len(blocks),
        "window_count": len(windows),
        "tag_count": len(tags),
        "tag_vote_count": tag_vote_count,
        "duplicate_vote_block_count": len(dedupe_audit),
        "dedupe_conflict_count": sum(1 for item in dedupe_audit if item.get("dedupe_conflict")),
        "issue_count": len(issues),
        "failed_window_count": len(failed_windows),
        "failed_windows": failed_windows,
        "resolution_block_count": len(resolution_blocks),
        "role_counts": dict(sorted(role_counts.items())),
        "noise_counts": dict(sorted(noise_counts.items())),
        "content_tag_counts": dict(sorted(content_counts.items())),
        "model_provider": config.get("model_provider"),
        "model": model,
        "prompt_version": config.get("prompt_version"),
        "system_prompt_path": config.get("system_prompt_path", ""),
        "prompt_hash": sha256_text(system_prompt),
        "runtime_seconds": round(time.time() - started_at, 3),
        "model_latency_seconds": {
            "count": len(latencies),
            "min": round(min(latencies), 3) if latencies else 0.0,
            "median": round(statistics.median(latencies), 3) if latencies else 0.0,
            "p90": percentile(latencies, 0.9),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "usage": usage_totals,
        "artifacts": {
            "block_tags": safe_rel(out_dir / "block_tags.json"),
            "tag_dedupe_audit": safe_rel(out_dir / "tag_dedupe_audit.json"),
            "window_plan": safe_rel(out_dir / "window_plan.json"),
            "tagger_trace_html": safe_rel(out_dir / "block_tagger_trace.html"),
            "raw_model_responses": safe_rel(out_dir / "raw_model_responses"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }


def render_trace_html(out_dir: Path, blocks: list[dict[str, Any]], tags: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    tag_by_id = {tag["block_id"]: tag for tag in tags}
    rows: list[str] = []
    for block in blocks:
        tag = tag_by_id.get(block["block_id"], fallback_tag(block["block_id"], "not_tagged"))
        classes = []
        if tag.get("needs_resolution"):
            classes.append("resolution")
        if tag.get("primary_role") == "decorative":
            classes.append("decorative")
        rows.append(
            "<tr class='{cls}'><td>{block}</td><td>{role}</td><td>{content}</td><td>{noise}</td><td>{conf:.2f}</td><td>{resolution}</td><td>{text}</td></tr>".format(
                cls=" ".join(classes),
                block=html.escape(block["block_id"]),
                role=html.escape(str(tag.get("primary_role"))),
                content=html.escape(",".join(tag.get("content_tags", []))),
                noise=html.escape(",".join(tag.get("noise_tags", []))),
                conf=float(tag.get("confidence") or 0.0),
                resolution="yes" if tag.get("needs_resolution") else "",
                text=html.escape(compact_text(block.get("display_markdown") or block.get("text") or "", 260)),
            )
        )
    issue_text = html.escape(json.dumps(issues[:100], ensure_ascii=False, indent=2))
    html_text = (
        "<!doctype html><meta charset='utf-8'><title>DOCX Block Tagger Trace</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;background:#f5f7fb;color:#102033}"
        "table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #d8e0eb;padding:6px;vertical-align:top}"
        "th{background:#eef3f9}.resolution{background:#fff7ed}.decorative{color:#667085}.issues{white-space:pre-wrap;background:#fff;border:1px solid #d8e0eb;padding:12px}</style>"
        "<h1>DOCX Block Tagger Trace</h1>"
        f"<p>blocks={len(blocks)} tags={len(tags)} issues={len(issues)}</p>"
        f"<div class='issues'>{issue_text}</div>"
        "<table><thead><tr><th>block</th><th>primary_role</th><th>content_tags</th><th>noise_tags</th><th>confidence</th><th>resolution</th><th>display_markdown</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )
    (out_dir / "block_tagger_trace.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.time()
    config = read_json(args.config)
    system_prompt = load_system_prompt(config)
    paragraph_stream = read_json(args.paragraph_stream)
    blocks = build_blocks(paragraph_stream)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_native_block_tagger_v0_1")
    out_dir = out_root / args.run_id / slug_for(args.paragraph_stream)
    raw_dir = out_dir / "raw_model_responses"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    window_cfg = config.get("window", {}) or {}
    runner_cfg = config.get("runner", {}) or {}
    core = int(args.core_blocks or window_cfg.get("core_blocks") or 48)
    stride = int(args.stride_blocks or window_cfg.get("stride_blocks") or core)
    left = int(args.context_left_blocks or window_cfg.get("context_left_blocks") or 4)
    right = int(args.context_right_blocks or window_cfg.get("context_right_blocks") or 4)
    preview_chars = int(args.preview_chars or window_cfg.get("max_block_preview_chars") or 360)
    windows = plan_windows(blocks, core, left, right, stride)
    if args.max_windows > 0:
        windows = windows[: args.max_windows]
    write_json(out_dir / "window_plan.json", {"windows": [window.__dict__ for window in windows]})
    write_json(
        out_dir / "immutable_block_stream.json",
        {
            "schema_version": "docx_native_block_stream_for_tagger.v0.1",
            "source_docx": paragraph_stream.get("source_docx", ""),
            "source_paragraph_stream": str(args.paragraph_stream),
            "block_count": len(blocks),
            "blocks": blocks,
        },
    )

    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    model = args.model or str(config.get("default_model_endpoint_id") or "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    config_hash = stable_hash(config)
    max_workers = max(1, int(args.max_workers or runner_cfg.get("max_workers") or 1))
    timeout = int(args.timeout or runner_cfg.get("per_window_timeout_seconds") or 90)
    resume = bool(runner_cfg.get("resume", True)) and not args.no_resume

    window_results: list[dict[str, Any]] = []
    if args.no_model:
        for window in windows:
            core_ids = [f"b_{idx:06d}" for idx in range(window.core_start, window.core_end_exclusive)]
            result = {
                "window_id": window.window_id,
                "source": "no_model",
                "tags": [fallback_tag(block_id, "model_skipped") for block_id in core_ids],
                "issues": [{"type": "model_skipped", "window_id": window.window_id, "block_ids": core_ids}],
                "usage": {},
                "finish_reason": "skipped",
                "latency_seconds": 0.0,
            }
            write_json(raw_dir / f"{window.window_id}.validated.json", result)
            window_results.append(result)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    run_one_window,
                    window=window,
                    blocks=blocks,
                    raw_dir=raw_dir,
                    api_key=api_key,
                    model=model,
                    preview_chars=preview_chars,
                    config_hash=config_hash,
                    timeout=timeout,
                    resume=resume,
                    system_prompt=system_prompt,
                )
                for window in windows
            ]
            for future in concurrent.futures.as_completed(futures):
                window_results.append(future.result())
    window_results.sort(key=lambda item: source_order(item["window_id"]))

    tag_votes = [tag for item in window_results for tag in item.get("tags", [])]
    tag_votes.sort(key=lambda tag: source_order(tag["block_id"]))
    tags, dedupe_audit = reconcile_duplicate_tags(tag_votes)
    issues = [issue for item in window_results for issue in item.get("issues", [])]
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    for item in window_results:
        usage = item.get("usage") or {}
        usage_totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        usage_totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        usage_totals["total_tokens"] += int(usage.get("total_tokens") or 0)
        usage_totals["reasoning_tokens"] += int(((usage.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0)

    write_json(out_dir / "block_tags.json", {"schema_version": "docx_native_block_tags.v0.1", "tags": tags})
    write_json(out_dir / "tag_votes.json", {"schema_version": "docx_native_block_tag_votes.v0.1", "tags": tag_votes})
    write_json(out_dir / "tag_dedupe_audit.json", {"schema_version": "docx_native_block_tag_dedupe_audit.v0.1", "items": dedupe_audit})
    write_json(out_dir / "window_results.json", {"schema_version": "docx_native_block_tagger_windows.v0.1", "windows": window_results})
    write_json(out_dir / "issues.json", {"schema_version": "docx_native_block_tagger_issues.v0.1", "issues": issues})
    render_trace_html(out_dir, blocks, tags, issues)
    summary = build_summary(
        out_dir=out_dir,
        paragraph_stream_path=args.paragraph_stream,
        blocks=blocks,
        windows=windows,
        tags=tags,
        issues=issues,
        usage_totals=usage_totals,
        window_results=window_results,
        tag_vote_count=len(tag_votes),
        dedupe_audit=dedupe_audit,
        started_at=started_at,
        model=model,
        config=config,
        system_prompt=system_prompt,
    )
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX native block-only model tagger v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--core-blocks", type=int, default=0)
    parser.add_argument("--stride-blocks", type=int, default=0)
    parser.add_argument("--context-left-blocks", type=int, default=0)
    parser.add_argument("--context-right-blocks", type=int, default=0)
    parser.add_argument("--preview-chars", type=int, default=0)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
