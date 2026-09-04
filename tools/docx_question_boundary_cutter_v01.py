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
DEFAULT_CONFIG = ROOT / "config" / "docx_question_boundary_cutter_v01.yaml"
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
    return ("".join(chars).strip("_") or "docx_boundary_cutter")[:96]


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


def load_tags(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    tags = payload.get("tags") or payload.get("block_tags") or payload
    return {str(item.get("block_id")): item for item in tags if isinstance(item, dict)}


def load_blocks(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    paragraphs = payload.get("paragraphs") or payload.get("blocks") or []
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(paragraphs):
        block_id = str(block.get("block_id") or f"b_{index:06d}")
        image_refs = [item for item in (block.get("image_refs") or block.get("asset_refs") or []) if isinstance(item, dict)]
        blocks.append(
            {
                "block_id": block_id,
                "source_order": index,
                "source_block_type": str(block.get("source_block_type") or "docx_block"),
                "display_markdown": str(block.get("display_markdown") or block.get("markdown") or ""),
                "text": str(block.get("plain_text_lossy") or block.get("text") or ""),
                "formula_count": int(block.get("formula_count") or 0),
                "image_ref_count": len(image_refs),
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
                window_id=f"c_{index:04d}",
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


def candidate_roles(config: dict[str, Any]) -> set[str]:
    policy = config.get("assembler_policy") or {}
    return {str(x) for x in (policy.get("candidate_block_roles") or ["question_content", "unknown"])}


def build_window_payload(
    *,
    doc_id: str,
    window: Window,
    blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    preview_chars = int((config.get("window_policy") or {}).get("max_block_preview_chars") or 620)
    roles = candidate_roles(config)
    groups = {"previous_tail_blocks": [], "current_blocks": [], "next_head_blocks": [], "excluded_evidence_blocks": []}
    for index in range(window.input_start, window.input_end_exclusive):
        block = blocks[index]
        tag = tags.get(block["block_id"], {})
        scope = "previous_tail" if index < window.core_start else ("next_head" if index >= window.core_end_exclusive else "current")
        item = block_for_model(block, tag, scope, preview_chars)
        role = str(item["block_role"])
        if role in roles:
            groups[f"{scope}_blocks" if scope != "previous_tail" else "previous_tail_blocks"].append(item)
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
        "ok": parsed is not None,
        "parsed": parsed,
        "raw_content": raw_content,
        "raw_response": raw_response,
        "parse_error": parse_error,
        "usage": raw_response.get("usage", {}),
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_current_accounting(parsed: dict[str, Any], current_ids: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: dict[str, list[str]] = defaultdict(list)
    current = set(current_ids)
    for item in parsed.get("new_question_starts") or []:
        bid = str(item.get("block_id") or "")
        if bid:
            seen[bid].append("new_question_starts")
    for field in ["continuation_groups", "context_only_blocks", "decorative_or_waste_blocks", "uncertain_blocks"]:
        for item in parsed.get(field) or []:
            for bid in item.get("block_ids") or []:
                seen[str(bid)].append(field)
    for bid in sorted(current - set(seen), key=source_order):
        issues.append({"type": "unaccounted_current_block", "severity": "warning", "block_id": bid})
    for bid, fields in sorted(seen.items(), key=lambda x: source_order(x[0])):
        if bid not in current:
            issues.append({"type": "non_current_block_accounted", "severity": "warning", "block_id": bid, "fields": fields})
        if len(fields) > 1:
            issues.append({"type": "duplicate_current_accounting", "severity": "warning", "block_id": bid, "fields": fields})
    return issues


def run_one_window(
    *,
    window: Window,
    blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
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
    payload = build_window_payload(doc_id=doc_id, window=window, blocks=blocks, tags=tags, config=config)
    # 中文说明：模型只须判定 current_blocks；被排除的参考段落不属于必答集合。
    current_ids = [block["block_id"] for block in payload["current_blocks"]]
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
            "issues": validate_current_accounting(parsed, current_ids),
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
                    "issues": validate_current_accounting(parsed, current_ids),
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


def collect_boundary_events(results: list[dict[str, Any]]) -> dict[str, Any]:
    starts: list[dict[str, Any]] = []
    continuations: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    waste: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for result in results:
        wid = result["window_id"]
        parsed = result.get("parsed") or {}
        for item in parsed.get("new_question_starts") or []:
            starts.append({"window_id": wid, **item})
        for field, target in [
            ("continuation_groups", continuations),
            ("context_only_blocks", context),
            ("decorative_or_waste_blocks", waste),
            ("uncertain_blocks", uncertain),
        ]:
            for item in parsed.get(field) or []:
                target.append({"window_id": wid, "field": field, **item})
        for issue in result.get("issues") or []:
            issues.append({"window_id": wid, **issue})
    return {
        "schema_version": "docx_question_boundary_events.v0.1",
        "new_question_starts": starts,
        "continuation_groups": continuations,
        "context_only_blocks": context,
        "decorative_or_waste_blocks": waste,
        "uncertain_blocks": uncertain,
        "issues": issues,
    }


def confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(value), 0)


def choose_start_blocks(events: dict[str, Any], candidate_ids: set[str], min_votes: int) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in events.get("new_question_starts") or []:
        bid = str(item.get("block_id") or "")
        if bid in candidate_ids:
            by_id[bid].append(item)
    chosen = []
    for bid, votes in by_id.items():
        if len(votes) < min_votes:
            continue
        best = sorted(votes, key=lambda x: confidence_rank(str(x.get("confidence"))), reverse=True)[0]
        chosen.append(
            {
                "block_id": bid,
                "vote_count": len(votes),
                "best_confidence": best.get("confidence", "unknown"),
                "evidence": best.get("evidence", ""),
                "windows": sorted({str(v.get("window_id")) for v in votes}),
            }
        )
    return sorted(chosen, key=lambda x: source_order(x["block_id"]))


def resolve_context_dispositions(results: list[dict[str, Any]]) -> dict[str, Any]:
    # 中文说明：只消费模型对当前窗口的显式判定；跨窗口冲突或漏答继续阻断，不猜测语义。
    votes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        current_ids = {block["block_id"] for block in (result.get("payload", {}).get("current_blocks") or [])}
        parsed = result.get("parsed") or {}
        fields_by_id: dict[str, list[str]] = defaultdict(list)
        context_evidence: dict[str, list[str]] = defaultdict(list)
        for item in parsed.get("new_question_starts") or []:
            fields_by_id[str(item.get("block_id") or "")].append("new_question_starts")
        for field in ("continuation_groups", "context_only_blocks", "decorative_or_waste_blocks", "uncertain_blocks"):
            for item in parsed.get(field) or []:
                for bid in item.get("block_ids") or []:
                    fields_by_id[str(bid)].append(field)
                    if field == "context_only_blocks":
                        context_evidence[str(bid)].append(str(item.get("evidence") or ""))
        for bid in current_ids:
            votes[bid].append({
                "window_id": result["window_id"],
                "fields": fields_by_id[bid],
                "context_evidence": context_evidence[bid],
            })
    accepted: list[str] = []
    conflicts: list[str] = []
    decisions: list[dict[str, Any]] = []
    for bid, block_votes in sorted(votes.items(), key=lambda item: source_order(item[0])):
        if not any("context_only_blocks" in vote["fields"] for vote in block_votes):
            continue
        unanimous = all(vote["fields"] == ["context_only_blocks"] for vote in block_votes)
        (accepted if unanimous else conflicts).append(bid)
        decisions.append({"block_id": bid, "status": "context_only" if unanimous else "needs_resolution", "votes": block_votes})
    return {"schema_version": "docx_question_boundary_context_dispositions.v0.1", "context_only_block_ids": accepted, "conflicting_block_ids": conflicts, "decisions": decisions}


def assemble_packets(blocks: list[dict[str, Any]], tags: dict[str, dict[str, Any]], config: dict[str, Any], starts: list[dict[str, Any]], context_dispositions: dict[str, Any] | None = None) -> dict[str, Any]:
    roles = candidate_roles(config)
    candidate_blocks = [b for b in blocks if str(tags.get(b["block_id"], {}).get("primary_role") or "unknown") in roles]
    disposition = context_dispositions or {}
    original_candidates = {b["block_id"] for b in candidate_blocks}
    context_ids = set(disposition.get("context_only_block_ids") or []) & original_candidates
    conflict_ids = set(disposition.get("conflicting_block_ids") or []) & original_candidates
    # 中文说明：上下文从题目正文分离并单独留存；有冲突的段落必须出现在未归属清单中。
    candidate_ids = [b["block_id"] for b in candidate_blocks if b["block_id"] not in context_ids | conflict_ids]
    retained_context = sorted(context_ids, key=source_order)
    candidate_set = set(candidate_ids)
    start_ids = [s["block_id"] for s in starts if s["block_id"] in candidate_set]
    start_set = set(start_ids)
    packets: list[dict[str, Any]] = []
    unassigned_prefix: list[str] = []
    if not start_ids:
        return {
            "schema_version": "docx_question_boundary_assembled_packets.v0.1",
            "packets": [],
            "unassigned_candidate_blocks": sorted(set(candidate_ids) | conflict_ids, key=source_order),
            "context_only_blocks": retained_context,
            "start_blocks": [],
        }
    start_positions = {bid: i for i, bid in enumerate(candidate_ids) if bid in start_set}
    sorted_starts = sorted(start_ids, key=lambda bid: start_positions[bid])
    first_pos = start_positions[sorted_starts[0]]
    unassigned_prefix = sorted(set(candidate_ids[:first_pos]) | conflict_ids, key=source_order)
    start_meta = {s["block_id"]: s for s in starts}
    for index, start_id in enumerate(sorted_starts):
        start_pos = start_positions[start_id]
        end_pos = start_positions[sorted_starts[index + 1]] if index + 1 < len(sorted_starts) else len(candidate_ids)
        block_ids = candidate_ids[start_pos:end_pos]
        packets.append(
            {
                "packet_id": f"dq_{index + 1:04d}",
                "question_start_block_id": start_id,
                "start_block_id": block_ids[0],
                "end_block_id": block_ids[-1],
                "source_block_ids": block_ids,
                "block_count": len(block_ids),
                "start_vote_count": start_meta[start_id].get("vote_count"),
                "start_confidence": start_meta[start_id].get("best_confidence"),
                "start_windows": start_meta[start_id].get("windows", []),
                "start_evidence": start_meta[start_id].get("evidence", ""),
            }
        )
    return {
        "schema_version": "docx_question_boundary_assembled_packets.v0.1",
        "packets": packets,
        "unassigned_candidate_blocks": unassigned_prefix,
        "context_only_blocks": retained_context,
        "start_blocks": starts,
    }


def make_trace_html(out_dir: Path, assembled: dict[str, Any], events: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    by_id = {b["block_id"]: b for b in blocks}

    def preview(bid: str) -> str:
        block = by_id.get(bid, {})
        text = compact_text(block.get("display_markdown") or block.get("text") or "", 180)
        return html.escape(text)

    rows = []
    for packet in assembled.get("packets") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(packet['packet_id'])}</td>"
            f"<td>{html.escape(packet['start_block_id'])}-{html.escape(packet['end_block_id'])}</td>"
            f"<td>{packet['block_count']}</td>"
            f"<td>{packet.get('start_vote_count')} / {html.escape(str(packet.get('start_confidence')))}</td>"
            f"<td>{preview(packet['start_block_id'])}</td>"
            f"<td>{preview(packet['end_block_id'])}</td>"
            "</tr>"
        )
    issue_rows = []
    for issue in events.get("issues") or []:
        issue_rows.append(f"<li><code>{html.escape(issue.get('window_id',''))}</code> {html.escape(json.dumps(issue, ensure_ascii=False))}</li>")
    html_text = f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Boundary Cutter Trace</title>
<style>
body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; background: #f4f7fb; color: #0f172a; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }}
th {{ background: #e2e8f0; }}
code {{ background: #e2e8f0; padding: 2px 4px; border-radius: 4px; }}
</style>
<h1>DOCX Question Boundary Cutter Trace</h1>
<p>packets={len(assembled.get('packets') or [])} starts={len(events.get('new_question_starts') or [])} issues={len(events.get('issues') or [])}</p>
<table>
<thead><tr><th>packet</th><th>range</th><th>blocks</th><th>start votes</th><th>start</th><th>end</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<h2>Issues</h2>
<ul>{''.join(issue_rows[:200])}</ul>
"""
    (out_dir / "boundary_trace.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks = load_blocks(args.paragraph_stream)
    tags = load_tags(args.block_tags)
    doc_id = args.doc_id or slug_for(args.paragraph_stream)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_boundary_cutter_v0_1")
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
    if args.window_start:
        windows = windows[args.window_start :]
    if args.max_windows:
        windows = windows[: args.max_windows]
    write_json(out_dir / "window_plan.json", {"schema_version": "docx_question_boundary_window_plan.v0.1", "windows": [w.__dict__ for w in windows]})
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    max_attempts = int(args.max_window_attempts or (config.get("runner") or {}).get("max_window_attempts") or 1)
    if args.no_model:
        results = [{"window_id": w.window_id, "source": "no_model", "payload": {}, "parsed": {}, "issues": [{"type": "model_skipped", "severity": "error"}], "usage": {}} for w in windows]
    else:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
            futures = [
                executor.submit(
                    run_one_window,
                    window=w,
                    blocks=blocks,
                    tags=tags,
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
    write_json(out_dir / "window_results.json", {"schema_version": "docx_question_boundary_window_results.v0.1", "windows": results})
    events = collect_boundary_events(results)
    candidate_ids = {
        b["block_id"]
        for b in blocks
        if str(tags.get(b["block_id"], {}).get("primary_role") or "unknown") in candidate_roles(config)
    }
    min_votes = int((config.get("assembler_policy") or {}).get("min_start_votes") or 1)
    starts = choose_start_blocks(events, candidate_ids, min_votes)
    context_dispositions = resolve_context_dispositions(results)
    assembled = assemble_packets(blocks, tags, config, starts, context_dispositions)
    write_json(out_dir / "context_dispositions.json", context_dispositions)
    write_json(out_dir / "boundary_events.json", events)
    write_json(out_dir / "assembled_packets.json", assembled)
    make_trace_html(out_dir, assembled, events, blocks)
    usage = Counter()
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    issue_counts = Counter(issue.get("type", "unknown") for issue in events.get("issues") or [])
    summary = {
        "schema_version": "docx_question_boundary_cutter_summary.v0.1",
        "status": "ok" if not assembled.get("unassigned_candidate_blocks") and not any((r.get("source") == "failed") for r in results) else "needs_resolution",
        "doc_id": doc_id,
        "block_count": len(blocks),
        "window_count": len(windows),
        "start_event_count": len(events.get("new_question_starts") or []),
        "assembled_packet_count": len(assembled.get("packets") or []),
        "unassigned_candidate_block_count": len(assembled.get("unassigned_candidate_blocks") or []),
        "context_only_block_count": len(assembled.get("context_only_blocks") or []),
        "issue_count": len(events.get("issues") or []),
        "issue_counts": dict(issue_counts),
        "failed_window_count": sum(1 for r in results if r.get("source") == "failed"),
        "max_window_attempts": max_attempts,
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "window_plan": safe_rel(out_dir / "window_plan.json"),
            "window_results": safe_rel(out_dir / "window_results.json"),
            "boundary_events": safe_rel(out_dir / "boundary_events.json"),
            "assembled_packets": safe_rel(out_dir / "assembled_packets.json"),
            "context_dispositions": safe_rel(out_dir / "context_dispositions.json"),
            "boundary_trace": safe_rel(out_dir / "boundary_trace.html"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX question boundary cutter v0.1 isolated prototype.")
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
    parser.add_argument("--window-start", type=int, default=0)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--max-window-attempts", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
