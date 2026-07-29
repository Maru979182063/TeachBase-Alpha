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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_field_normalizer_v01.json"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


FIELD_ORDER = [
    "source_label",
    "instruction",
    "passage",
    "question_items",
    "options",
    "response_area",
    "answer",
    "guide",
    "explanation",
    "sample_answer",
    "teaching_note",
    "unknown",
]


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


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return -1


def compact_text(value: str, limit: int) -> str:
    text = str(value or "").replace("\r", "\n").strip()
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


def load_blocks(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = read_json(path)
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(payload.get("blocks") or []):
        block_id = str(block.get("block_id") or f"b_{index:06d}")
        blocks.append(
            {
                "block_id": block_id,
                "source_order": int(block.get("source_order") if block.get("source_order") is not None else index),
                "source_block_type": str(block.get("source_block_type") or "docx_block"),
                "display_markdown": str(block.get("display_markdown") or block.get("markdown") or ""),
                "plain_text_lossy": str(block.get("plain_text_lossy") or block.get("text") or ""),
                "asset_refs": [item for item in (block.get("asset_refs") or block.get("image_refs") or []) if isinstance(item, dict)],
                "blank_refs": [item for item in (block.get("blank_refs") or []) if isinstance(item, dict)],
                "response_area_refs": [item for item in (block.get("response_area_refs") or []) if isinstance(item, dict)],
                "content_loss_flags": list(block.get("content_loss_flags") or []),
            }
        )
    return blocks, payload


def block_for_model(block: dict[str, Any], preview_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "display_markdown": compact_text(block.get("display_markdown", ""), preview_chars),
        "plain_text_lossy": compact_text(block.get("plain_text_lossy", ""), preview_chars),
        "asset_refs": [
            {
                "asset_id": item.get("asset_id"),
                "asset_role": item.get("asset_role"),
                "visual_label_zh": item.get("visual_label_zh"),
                "visual_description": item.get("visual_description"),
            }
            for item in block.get("asset_refs") or []
        ],
        "blank_count": len(block.get("blank_refs") or []),
        "response_area_count": len(block.get("response_area_refs") or []),
        "content_loss_flags": block.get("content_loss_flags") or [],
    }


def section_context(groups: list[dict[str, Any]], group: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]], max_items: int, preview_chars: int) -> list[dict[str, Any]]:
    start = source_order(str(group.get("start_block_id") or ""))
    if start < 0:
        ids = [str(item) for item in group.get("source_block_ids") or []]
        start = min([source_order(item) for item in ids] or [0])
    covered = {bid for item in groups for bid in item.get("source_block_ids", []) or []}
    candidates = []
    for block in blocks_by_id.values():
        bid = str(block.get("block_id") or "")
        if bid in covered:
            continue
        if int(block.get("source_order") or 0) >= start:
            continue
        if not str(block.get("display_markdown") or "").strip():
            continue
        candidates.append(block)
    candidates.sort(key=lambda item: int(item["source_order"]))
    return [
        {
            "block_id": block["block_id"],
            "source_order": block["source_order"],
            "display_markdown": compact_text(block["display_markdown"], preview_chars),
            "plain_text_lossy": compact_text(block["plain_text_lossy"], preview_chars),
        }
        for block in candidates[-max_items:]
    ]


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    doc_id: str,
    group: dict[str, Any],
    group_blocks: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]],
) -> str:
    return render_template(
        template,
        {
            "doc_id": doc_id,
            "group_id": str(group.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "group_kind": str(group.get("group_kind") or "mixed_or_unknown"),
            "section_context_json": json.dumps(section_blocks, ensure_ascii=False, indent=2),
            "group_blocks_json": json.dumps(group_blocks, ensure_ascii=False, indent=2),
        },
    )


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
        "raw_response": raw_response,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_payload(payload: dict[str, Any] | None, *, doc_id: str, group_id: str, valid_ids: set[str], config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    allowed_kinds = set(config.get("allowed_kinds") or [])
    allowed_parts = set(config.get("allowed_part_types") or [])
    if not isinstance(payload, dict):
        return {
            "schema": "english_docx_group_field_normalizer_v0.1",
            "doc_id": doc_id,
            "group_id": group_id,
            "normalized_kind": "mixed_or_unknown",
            "parts": [],
            "unassigned_block_ids": sorted(valid_ids, key=source_order),
            "warnings": [],
        }, [{"type": "invalid_json"}]
    if payload.get("schema") != "english_docx_group_field_normalizer_v0.1":
        issues.append({"type": "schema_mismatch", "value": payload.get("schema")})
    if payload.get("group_id") != group_id:
        issues.append({"type": "group_id_mismatch", "value": payload.get("group_id")})
    kind = str(payload.get("normalized_kind") or "mixed_or_unknown")
    if kind not in allowed_kinds:
        issues.append({"type": "invalid_normalized_kind", "value": kind})
        kind = "mixed_or_unknown"
    owner: dict[str, str] = {}
    parts: list[dict[str, Any]] = []
    for item in payload.get("parts") or []:
        if not isinstance(item, dict):
            issues.append({"type": "invalid_part_shape"})
            continue
        part_type = str(item.get("part_type") or "unknown")
        if part_type not in allowed_parts:
            issues.append({"type": "invalid_part_type", "value": part_type})
            part_type = "unknown"
        ids = [str(value) for value in item.get("block_ids") or []]
        unknown_ids = [bid for bid in ids if bid not in valid_ids]
        if unknown_ids:
            issues.append({"type": "unknown_block_ids", "part_type": part_type, "block_ids": unknown_ids})
        clean_ids = sorted(dict.fromkeys([bid for bid in ids if bid in valid_ids]), key=source_order)
        for bid in clean_ids:
            if bid in owner:
                issues.append({"type": "duplicate_assignment", "block_id": bid, "first_part": owner[bid], "second_part": part_type})
            owner[bid] = part_type
        if clean_ids:
            parts.append({"part_type": part_type, "block_ids": clean_ids, "confidence": str(item.get("confidence") or "unknown")})
    unassigned = [str(value) for value in payload.get("unassigned_block_ids") or []]
    unknown_unassigned = [bid for bid in unassigned if bid not in valid_ids]
    if unknown_unassigned:
        issues.append({"type": "unknown_unassigned_block_ids", "block_ids": unknown_unassigned})
    clean_unassigned = sorted(dict.fromkeys([bid for bid in unassigned if bid in valid_ids]), key=source_order)
    missing = sorted(valid_ids - set(owner) - set(clean_unassigned), key=source_order)
    if missing:
        issues.append({"type": "unaccounted_group_block_ids", "block_ids": missing})
        clean_unassigned = sorted(set(clean_unassigned) | set(missing), key=source_order)
    overlap = sorted(set(owner) & set(clean_unassigned), key=source_order)
    if overlap:
        issues.append({"type": "assigned_and_unassigned_block_ids", "block_ids": overlap})
        clean_unassigned = [bid for bid in clean_unassigned if bid not in owner]
    if not any(part["part_type"] in {"source_label", "instruction", "passage", "question_items"} for part in parts):
        issues.append({"type": "missing_front_matter_part", "severity": "warning"})
    return {
        "schema": "english_docx_group_field_normalizer_v0.1",
        "doc_id": doc_id,
        "group_id": group_id,
        "normalized_kind": kind,
        "parts": parts,
        "unassigned_block_ids": clean_unassigned,
        "warnings": [str(value) for value in payload.get("warnings", []) if isinstance(value, str)],
    }, issues


def has_blocking_issues(issues: list[dict[str, Any]]) -> bool:
    return any(str(issue.get("severity") or "blocking") != "warning" for issue in issues)


def materialize_markdown(block_ids: list[str], blocks_by_id: dict[str, dict[str, Any]]) -> str:
    parts = []
    for bid in sorted(block_ids, key=source_order):
        block = blocks_by_id.get(bid)
        if not block:
            continue
        md = str(block.get("display_markdown") or "").strip()
        if md:
            parts.append(md)
    return "\n\n".join(parts).strip()


def field_assets(block_ids: list[str], blocks_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for bid in sorted(block_ids, key=source_order):
        block = blocks_by_id.get(bid) or {}
        for asset in block.get("asset_refs") or []:
            if isinstance(asset, dict):
                refs.append({"block_id": bid, **asset})
    return refs


def materialize_record(normalized: dict[str, Any], group: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    field_block_ids: dict[str, list[str]] = {field: [] for field in FIELD_ORDER}
    field_confidence: dict[str, str] = {}
    for part in normalized.get("parts") or []:
        part_type = str(part.get("part_type") or "unknown")
        if part_type not in field_block_ids:
            part_type = "unknown"
        ids = [str(item) for item in part.get("block_ids") or []]
        field_block_ids[part_type].extend(ids)
        field_confidence[part_type] = str(part.get("confidence") or field_confidence.get(part_type) or "unknown")
    fields = {field: materialize_markdown(ids, blocks_by_id) for field, ids in field_block_ids.items()}
    field_asset_refs = {field: field_assets(ids, blocks_by_id) for field, ids in field_block_ids.items() if field_assets(ids, blocks_by_id)}
    return {
        "group_id": group.get("group_id"),
        "upstream_group_kind": group.get("group_kind"),
        "normalized_kind": normalized.get("normalized_kind"),
        "source_block_ids": group.get("source_block_ids") or [],
        "field_block_ids": {field: ids for field, ids in field_block_ids.items() if ids},
        "field_confidence": field_confidence,
        "fields": fields,
        "field_asset_refs": field_asset_refs,
        "unassigned_block_ids": normalized.get("unassigned_block_ids") or [],
        "warnings": normalized.get("warnings") or [],
        "source_trace": {
            "start_block_id": group.get("start_block_id"),
            "end_block_id": group.get("end_block_id"),
            "end_source": group.get("end_source"),
        },
    }


def normalize_one(
    *,
    config: dict[str, Any],
    system_prompt: str,
    user_template: str,
    doc_id: str,
    group: dict[str, Any],
    group_blocks: list[dict[str, Any]],
    section_blocks: list[dict[str, Any]],
    blocks_by_id: dict[str, dict[str, Any]],
    out_dir: Path,
    api_key: str,
    timeout: int,
    max_attempts: int,
    no_resume: bool,
) -> dict[str, Any]:
    group_id = str(group.get("group_id") or "")
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    prompt = render_user_prompt(config, user_template, doc_id=doc_id, group=group, group_blocks=group_blocks, section_blocks=section_blocks)
    write_json(raw_dir / "prompt.json", {"system_prompt": system_prompt, "user_prompt": prompt, "group_blocks": group_blocks, "section_context": section_blocks})
    parsed_path = raw_dir / "parsed.json"
    response_path = raw_dir / "response.json"
    valid_ids = {str(block.get("block_id")) for block in group_blocks}
    if parsed_path.exists() and not no_resume:
        parsed = read_json(parsed_path)
        normalized, issues = validate_payload(parsed, doc_id=doc_id, group_id=group_id, valid_ids=valid_ids, config=config)
        return {
            "group_id": group_id,
            "source": "resume",
            "status": "ok" if not has_blocking_issues(issues) else "needs_resolution",
            "normalization": normalized,
            "record": materialize_record(normalized, group, blocks_by_id),
            "issues": issues,
            "usage": {},
            "latency_seconds": 0.0,
        }
    last_result: dict[str, Any] = {"parsed": None, "raw_response": {}, "parse_error": "not_run", "latency_seconds": 0.0}
    normalized: dict[str, Any] = {}
    issues: list[dict[str, Any]] = [{"type": "not_run"}]
    attempts = []
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            result = call_model(config, system_prompt, prompt, api_key, timeout)
            last_result = result
            write_json(raw_dir / f"attempt{attempt}.response.json", result["raw_response"])
            (raw_dir / f"attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result["parsed"] is not None:
                write_json(raw_dir / f"attempt{attempt}.parsed.json", result["parsed"])
            normalized, issues = validate_payload(result["parsed"], doc_id=doc_id, group_id=group_id, valid_ids=valid_ids, config=config)
            attempts.append({"attempt": attempt, "status": "ok" if not has_blocking_issues(issues) else "needs_resolution", "issue_count": len(issues), "parse_error": result.get("parse_error", "")})
            if not result.get("parse_error") and not has_blocking_issues(issues):
                write_json(response_path, result["raw_response"])
                write_json(parsed_path, result["parsed"])
                break
        except Exception as exc:  # noqa: BLE001
            issues = [{"type": "model_exception", "message": str(exc)[:500]}]
            attempts.append({"attempt": attempt, "status": "needs_resolution", "issue_count": 1, "parse_error": str(exc)[:500]})
    return {
        "group_id": group_id,
        "source": "model" if not has_blocking_issues(issues) else "failed",
        "status": "ok" if not has_blocking_issues(issues) else "needs_resolution",
        "normalization": normalized,
        "record": materialize_record(normalized, group, blocks_by_id) if normalized else {},
        "issues": issues,
        "attempts": attempts,
        "usage": (last_result.get("raw_response") or {}).get("usage", {}),
        "latency_seconds": last_result.get("latency_seconds", 0.0),
    }


def build_review_html(out_dir: Path, results: list[dict[str, Any]]) -> None:
    rows = []
    for item in results:
        record = item.get("record") or {}
        fields = record.get("fields") or {}
        field_cells = []
        for field in FIELD_ORDER:
            text = str(fields.get(field) or "")
            if text:
                field_cells.append(f"<h3>{html.escape(field)}</h3><pre>{html.escape(compact_text(text, 1200))}</pre>")
        rows.append(
            "<section>"
            f"<h2>{html.escape(str(item.get('group_id')))} | {html.escape(str(record.get('normalized_kind')))} | {html.escape(str(item.get('status')))}</h2>"
            f"<div>issues={html.escape(json.dumps(item.get('issues') or [], ensure_ascii=False))}</div>"
            + "".join(field_cells)
            + "</section>"
        )
    html_text = """<!doctype html><meta charset="utf-8"><title>English DOCX Field Normalizer Review</title>
<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f8fb;color:#172033}section{background:white;border:1px solid #d8e0ec;border-radius:8px;margin:0 0 18px;padding:16px}pre{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;padding:10px}</style>
<h1>English DOCX Field Normalizer Review</h1>
""" + "\n".join(rows)
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks, block_payload = load_blocks(args.block_stream)
    blocks_by_id = {block["block_id"]: block for block in blocks}
    groups_payload = read_json(args.assembled_groups)
    groups = groups_payload.get("groups") or []
    doc_id = args.doc_id or args.block_stream.parent.name
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/english_docx_group_field_normalizer_v0_1")
    out_dir = out_root / args.run_id / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_chars = int(config.get("max_block_preview_chars") or 2200)
    max_sections = int(config.get("max_section_context_blocks") or 4)
    selected_groups = groups
    if args.group_ids:
        wanted = {value.strip() for value in args.group_ids.split(",") if value.strip()}
        selected_groups = [group for group in groups if str(group.get("group_id")) in wanted]
    if args.max_groups:
        selected_groups = selected_groups[: args.max_groups]
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.no_model:
        raise RuntimeError("missing_api_key")
    runner = config.get("runner") or {}
    timeout = int(args.timeout or runner.get("per_group_timeout_seconds") or 240)
    max_attempts = int(args.max_group_attempts or runner.get("max_group_attempts") or 1)
    max_workers = int(args.max_workers or runner.get("max_workers") or 1)

    prepared = []
    for group in selected_groups:
        ids = [str(value) for value in group.get("source_block_ids") or []]
        group_blocks = [block_for_model(blocks_by_id[bid], preview_chars) for bid in ids if bid in blocks_by_id]
        prepared.append(
            {
                "group": group,
                "group_blocks": group_blocks,
                "section_context": section_context(groups, group, blocks_by_id, max_sections, preview_chars),
            }
        )
    write_json(out_dir / "normalizer_inputs.json", {"schema_version": "english_docx_group_field_normalizer_inputs.v0.1", "doc_id": doc_id, "groups": prepared})
    if args.no_model:
        results = [
            {
                "group_id": str(item["group"].get("group_id") or ""),
                "source": "no_model",
                "status": "needs_resolution",
                "normalization": {},
                "record": {},
                "issues": [{"type": "model_skipped"}],
                "usage": {},
            }
            for item in prepared
        ]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            future_map = {
                executor.submit(
                    normalize_one,
                    config=config,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    doc_id=doc_id,
                    group=item["group"],
                    group_blocks=item["group_blocks"],
                    section_blocks=item["section_context"],
                    blocks_by_id=blocks_by_id,
                    out_dir=out_dir,
                    api_key=api_key,
                    timeout=timeout,
                    max_attempts=max_attempts,
                    no_resume=args.no_resume,
                ): item
                for item in prepared
            }
            results = [future.result() for future in concurrent.futures.as_completed(future_map)]
        results.sort(key=lambda item: source_order(str((item.get("record") or {}).get("source_trace", {}).get("start_block_id") or "")))
    records = [item.get("record") for item in results if item.get("record")]
    issue_counts = Counter(issue.get("type", "unknown") for result in results for issue in result.get("issues") or [])
    usage = Counter()
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                usage[key] += value
    status = "ok" if all(item.get("status") == "ok" for item in results) else "needs_resolution"
    output = {
        "schema_version": "english_docx_group_field_normalizer_results.v0.1",
        "doc_id": doc_id,
        "run_id": args.run_id,
        "source_block_stream": safe_rel(args.block_stream),
        "source_assembled_groups": safe_rel(args.assembled_groups),
        "records": records,
        "results": results,
    }
    write_json(out_dir / "normalized_groups.json", output)
    build_review_html(out_dir, results)
    summary = {
        "schema_version": "english_docx_group_field_normalizer_summary.v0.1",
        "pipeline_id": "english_docx_group_field_normalizer_v01",
        "run_id": args.run_id,
        "doc_id": doc_id,
        "status": status,
        "group_count": len(selected_groups),
        "ok_group_count": sum(1 for item in results if item.get("status") == "ok"),
        "needs_resolution_group_count": sum(1 for item in results if item.get("status") != "ok"),
        "kind_counts": dict(Counter(str((record or {}).get("normalized_kind") or "unknown") for record in records)),
        "issue_count": sum(len(item.get("issues") or []) for item in results),
        "issue_counts": dict(issue_counts),
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "prompt_version": config.get("prompt_version"),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "normalizer_inputs": safe_rel(out_dir / "normalizer_inputs.json"),
            "normalized_groups": safe_rel(out_dir / "normalized_groups.json"),
            "review_html": safe_rel(out_dir / "index.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize already-cut English DOCX groups into source-backed fields.")
    parser.add_argument("--block-stream", required=True, type=Path)
    parser.add_argument("--assembled-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--max-group-attempts", type=int, default=0)
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
