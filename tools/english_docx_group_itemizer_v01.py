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
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_itemizer_v01.json"
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


def compact(value: str, limit: int) -> str:
    text = str(value or "").strip()
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


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return -1


def load_blocks(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    blocks: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(payload.get("blocks") or []):
        block_id = str(block.get("block_id") or f"b_{index:06d}")
        blocks[block_id] = {
            "block_id": block_id,
            "source_order": int(block.get("source_order") if block.get("source_order") is not None else index),
            "display_markdown": str(block.get("display_markdown") or block.get("markdown") or ""),
            "plain_text_lossy": str(block.get("plain_text_lossy") or block.get("text") or ""),
            "blank_refs": [item for item in (block.get("blank_refs") or []) if isinstance(item, dict)],
            "response_area_refs": [item for item in (block.get("response_area_refs") or []) if isinstance(item, dict)],
            "asset_refs": [item for item in (block.get("asset_refs") or []) if isinstance(item, dict)],
        }
    return blocks


def block_for_model(block: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "source_order": block["source_order"],
        "display_markdown": compact(block["display_markdown"], max_chars),
        "plain_text_lossy": compact(block["plain_text_lossy"], max_chars),
        "blank_refs": block.get("blank_refs") or [],
        "response_area_refs": block.get("response_area_refs") or [],
        "asset_refs": [
            {
                "asset_id": item.get("asset_id"),
                "asset_role": item.get("asset_role"),
                "visual_label_zh": item.get("visual_label_zh"),
            }
            for item in block.get("asset_refs") or []
        ],
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
    content = str(raw_response["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "raw_response": raw_response,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "elapsed_seconds": round(time.time() - started, 3),
        "usage": raw_response.get("usage") or {},
    }


def validate_itemizer(
    parsed: dict[str, Any] | None,
    *,
    record: dict[str, Any],
    source_blocks: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    issues: list[str] = []
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    cleaned = dict(parsed)
    allowed_ids = {str(block["block_id"]) for block in source_blocks}
    allowed_kinds = set(config.get("allowed_item_kinds") or [])
    if str(cleaned.get("group_id") or "") != str(record.get("group_id") or ""):
        issues.append("group_id_mismatch")
    if str(cleaned.get("parent_kind") or "") != str(record.get("normalized_kind") or ""):
        issues.append("parent_kind_mismatch")
    items = cleaned.get("items")
    if not isinstance(items, list) or not items:
        issues.append("items_empty")
        items = []
    item_ids: set[str] = set()
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"item_{item_index}_not_object")
            continue
        item_id = str(item.get("item_id") or "")
        if not item_id:
            issues.append(f"item_{item_index}_missing_item_id")
        elif item_id in item_ids:
            issues.append(f"duplicate_item_id:{item_id}")
        item_ids.add(item_id)
        kind = str(item.get("item_kind") or "")
        if kind not in allowed_kinds:
            issues.append(f"invalid_item_kind:{item_id}:{kind}")
        for key in ["question_block_ids", "option_block_ids", "response_area_block_ids", "explanation_block_ids"]:
            ids = item.get(key)
            if ids is None:
                item[key] = []
                ids = []
            if not isinstance(ids, list):
                issues.append(f"{item_id}:{key}_not_list")
                item[key] = []
                continue
            normalized_ids = [str(value) for value in ids]
            item[key] = sorted(normalized_ids, key=source_order)
            for block_id in normalized_ids:
                if block_id not in allowed_ids:
                    issues.append(f"{item_id}:{key}_unknown_block_id:{block_id}")
        for key in ["item_no", "source_item_no", "anchor", "answer_text", "confidence"]:
            item[key] = str(item.get(key) or "")
    shared_fields = cleaned.get("shared_fields")
    if not isinstance(shared_fields, dict):
        cleaned["shared_fields"] = {}
    if not isinstance(cleaned.get("warnings"), list):
        cleaned["warnings"] = []
    if not isinstance(cleaned.get("unassigned_item_block_ids"), list):
        cleaned["unassigned_item_block_ids"] = []
    return not issues, issues, cleaned


def materialize_item(item: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def md(ids: list[str]) -> str:
        rows = [blocks_by_id[block_id]["display_markdown"] for block_id in ids if block_id in blocks_by_id]
        return "\n\n".join(row for row in rows if row.strip())

    return {
        **item,
        "question_markdown": md(item.get("question_block_ids") or []),
        "options_markdown": md(item.get("option_block_ids") or []),
        "response_area_markdown": md(item.get("response_area_block_ids") or []),
        "explanation_markdown": md(item.get("explanation_block_ids") or []),
    }


def merge_writing_task_items(record: dict[str, Any], cleaned: dict[str, Any]) -> dict[str, Any]:
    parent_kind = str(record.get("normalized_kind") or "")
    if parent_kind not in {"writing_letter", "continuation_writing"}:
        return cleaned
    field_block_ids = record.get("field_block_ids") or {}

    def ids_for(*fields: str) -> list[str]:
        ids: list[str] = []
        for field in fields:
            ids.extend(str(item) for item in field_block_ids.get(field, []) or [])
        return sorted(dict.fromkeys(ids), key=source_order)

    item_kind = "continuation_writing_task" if parent_kind == "continuation_writing" else "writing_task"
    group_id = str(record.get("group_id") or "group")
    merged = {
        "item_id": f"{group_id}_q_001",
        "item_no": "1",
        "item_kind": item_kind,
        "anchor": "continuation writing task" if parent_kind == "continuation_writing" else "writing task",
        "question_block_ids": ids_for("instruction", "passage", "question_items"),
        "option_block_ids": [],
        "response_area_block_ids": ids_for("response_area"),
        "answer_text": str((record.get("fields") or {}).get("sample_answer") or ""),
        "explanation_block_ids": ids_for("explanation"),
        "confidence": "high",
    }
    updated = dict(cleaned)
    updated["items"] = [merged]
    updated["warnings"] = list(updated.get("warnings") or [])
    updated["warnings"].append("writing_parent_group_collapsed_to_single_business_item")
    return updated


def apply_parent_local_numbering(cleaned: dict[str, Any]) -> dict[str, Any]:
    updated = dict(cleaned)
    items = [item for item in (updated.get("items") or []) if isinstance(item, dict)]
    group_id = str(updated.get("group_id") or "group")
    for index, item in enumerate(items, start=1):
        previous_no = str(item.get("item_no") or "")
        if previous_no and not str(item.get("source_item_no") or ""):
            item["source_item_no"] = previous_no
        item["item_no"] = str(index)
        item["item_id"] = f"{group_id}_q_{index:03d}"
    updated["items"] = items
    return updated


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    record: dict[str, Any],
    source_blocks: list[dict[str, Any]],
) -> str:
    fields = {
        key: compact(value, int(config.get("max_field_chars") or 6000))
        for key, value in (record.get("fields") or {}).items()
        if str(value or "").strip()
    }
    field_block_ids = record.get("field_block_ids") or {}
    return render_template(
        template,
        {
            "doc_id": str(record.get("doc_id") or ""),
            "group_id": str(record.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "normalized_kind": str(record.get("normalized_kind") or "mixed_or_unknown"),
            "field_block_ids_json": json.dumps(field_block_ids, ensure_ascii=False, indent=2),
            "fields_json": json.dumps(fields, ensure_ascii=False, indent=2),
            "source_blocks_json": json.dumps(source_blocks, ensure_ascii=False, indent=2),
        },
    )


def process_record(
    *,
    config: dict[str, Any],
    record: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
    no_model: bool,
) -> dict[str, Any]:
    group_id = str(record.get("group_id") or "group")
    source_ids = [str(item) for item in record.get("source_block_ids") or []]
    source_blocks = [
        block_for_model(blocks_by_id[block_id], int(config.get("max_block_chars") or 1600))
        for block_id in source_ids
        if block_id in blocks_by_id
    ]
    prompt = render_user_prompt(config, user_template, record=record, source_blocks=source_blocks)
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": prompt})
    if no_model:
        return {
            "group_id": group_id,
            "status": "skipped_no_model",
            "normalized_kind": record.get("normalized_kind"),
            "items": [],
            "issues": ["no_model"],
            "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
        }
    timeout = int((config.get("runner") or {}).get("per_group_timeout_seconds") or 240)
    max_attempts = int((config.get("runner") or {}).get("max_group_attempts") or 3)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            result = call_model(config, system_prompt, prompt, api_key, timeout)
            write_json(raw_dir / f"attempt{attempt}.raw.json", result["raw_response"])
            (raw_dir / f"attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result["parsed"] is not None:
                write_json(raw_dir / f"attempt{attempt}.parsed.json", result["parsed"])
            ok, issues, cleaned = validate_itemizer(result["parsed"], record=record, source_blocks=source_blocks, config=config)
            if ok:
                cleaned = merge_writing_task_items(record, cleaned)
                cleaned = apply_parent_local_numbering(cleaned)
                materialized_items = [
                    materialize_item(item, blocks_by_id)
                    for item in cleaned.get("items") or []
                    if isinstance(item, dict)
                ]
                cleaned["items"] = materialized_items
                return {
                    "group_id": group_id,
                    "status": "ok",
                    "normalized_kind": record.get("normalized_kind"),
                    "item_count": len(materialized_items),
                    "item_kind_counts": dict(Counter(item.get("item_kind") for item in materialized_items)),
                    "result": cleaned,
                    "issues": [],
                    "usage": result.get("usage") or {},
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
                }
            last_error = ";".join(issues)
            write_json(raw_dir / f"attempt{attempt}.issues.json", issues)
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": last_error})
    return {
        "group_id": group_id,
        "status": "failed",
        "normalized_kind": record.get("normalized_kind"),
        "items": [],
        "issues": [last_error or "unknown_failure"],
        "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
    }


def render_index(records: list[dict[str, Any]], out_path: Path) -> None:
    sections = []
    for record in records:
        result = record.get("result") or {}
        items = result.get("items") or []
        item_rows = []
        for item in items:
            item_rows.append(
                "<li>"
                f"<b>{html.escape(str(item.get('item_id') or ''))}</b> "
                f"{html.escape(str(item.get('item_kind') or ''))} "
                f"{html.escape(str(item.get('anchor') or ''))} "
                f"ans={html.escape(str(item.get('answer_text') or ''))}"
                "</li>"
            )
        sections.append(
            "<section>"
            f"<h2>{html.escape(str(record.get('group_id')))} | {html.escape(str(record.get('normalized_kind')))} | "
            f"{html.escape(str(record.get('status')))} | items={len(items)}</h2>"
            f"<ul>{''.join(item_rows)}</ul>"
            f"<pre>{html.escape(json.dumps(record.get('issues') or [], ensure_ascii=False, indent=2))}</pre>"
            "</section>"
        )
    out_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>English itemizer</title>"
        "<style>body{font:14px/1.55 sans-serif;margin:24px}section{border-bottom:1px solid #ddd;padding:12px 0}"
        "li{margin:4px 0}</style>"
        + "\n".join(sections),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-normalized", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-output-name", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    normalized = read_json(args.input_normalized)
    source_block_stream = Path(str(normalized.get("source_block_stream") or ""))
    if not source_block_stream.is_absolute():
        source_block_stream = ROOT / source_block_stream
    blocks_by_id = load_blocks(source_block_stream)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    api_key = os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.no_model and not api_key:
        raise SystemExit(f"missing api key env: {config.get('api_key_env')}")
    records = list(normalized.get("records") or [])
    if args.max_groups:
        records = records[: args.max_groups]
    output_root = Path(str(config.get("owned_output_root") or "outputs/english_docx_group_itemizer_v0_1"))
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    doc_name = args.doc_output_name or str(normalized.get("doc_id") or args.input_normalized.parent.name)
    out_dir = output_root / args.run_id / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)

    max_workers = 1 if args.no_model else int((config.get("runner") or {}).get("max_workers") or 1)
    worker_args = [
        {
            "config": config,
            "record": {**record, "doc_id": normalized.get("doc_id")},
            "blocks_by_id": blocks_by_id,
            "system_prompt": system_prompt,
            "user_template": user_template,
            "api_key": api_key,
            "out_dir": out_dir,
            "no_model": args.no_model,
        }
        for record in records
    ]
    results: list[dict[str, Any]] = []
    if max_workers <= 1:
        for item in worker_args:
            results.append(process_record(**item))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_record, **item) for item in worker_args]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: str(item.get("group_id") or ""))

    itemized_records = [item.get("result") for item in results if item.get("result")]
    payload = {
        "schema_version": "english_docx_group_itemizer_results.v0.1",
        "doc_id": normalized.get("doc_id"),
        "run_id": args.run_id,
        "source_normalized_groups": safe_rel(args.input_normalized),
        "source_block_stream": safe_rel(source_block_stream),
        "records": itemized_records,
        "results": results,
    }
    write_json(out_dir / "itemized_groups.json", payload)
    summary = {
        "schema_version": "english_docx_group_itemizer_summary.v0.1",
        "doc_id": normalized.get("doc_id"),
        "run_id": args.run_id,
        "status_counts": dict(Counter(item.get("status") for item in results)),
        "group_count": len(results),
        "ok_group_count": sum(1 for item in results if item.get("status") == "ok"),
        "item_count": sum(int(item.get("item_count") or 0) for item in results),
        "item_kind_counts": dict(Counter(kind for item in results for kind, count in (item.get("item_kind_counts") or {}).items() for _ in range(count))),
        "issue_count": sum(len(item.get("issues") or []) for item in results),
        "usage": {
            "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in results),
            "prompt_tokens": sum(int((item.get("usage") or {}).get("prompt_tokens") or 0) for item in results),
            "completion_tokens": sum(int((item.get("usage") or {}).get("completion_tokens") or 0) for item in results),
        },
        "artifacts": {
            "itemized_groups": safe_rel(out_dir / "itemized_groups.json"),
            "summary": safe_rel(out_dir / "summary.json"),
            "index": safe_rel(out_dir / "index.html"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    render_index(results, out_dir / "index.html")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
