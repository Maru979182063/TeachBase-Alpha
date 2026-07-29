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
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_local_number_normalizer_v01.json"
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

FIELD_LABELS = {
    "source_label": "来源",
    "instruction": "题干",
    "passage": "材料",
    "question_items": "小题",
    "options": "选项",
    "response_area": "作答区",
    "answer": "答案",
    "guide": "导语",
    "explanation": "解析",
    "sample_answer": "范文",
    "teaching_note": "教学补充",
    "unknown": "未归类",
}


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


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    normalized_record: dict[str, Any],
    itemized_record: dict[str, Any],
    doc_id: str,
    doc_key: str,
) -> str:
    max_field_chars = int(config.get("max_field_chars") or 9000)
    fields = {
        key: compact(value, max_field_chars)
        for key, value in (normalized_record.get("fields") or {}).items()
        if str(value or "").strip()
    }
    items = [
        {
            "item_id": item.get("item_id"),
            "item_no": item.get("item_no"),
            "source_item_no": item.get("source_item_no"),
            "item_kind": item.get("item_kind"),
            "anchor": item.get("anchor"),
            "answer_text": compact(item.get("answer_text") or "", 600),
        }
        for item in itemized_record.get("items") or []
    ]
    return render_template(
        template,
        {
            "doc_id": doc_id,
            "doc_key": doc_key,
            "group_id": str(normalized_record.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "parent_kind": str(itemized_record.get("parent_kind") or normalized_record.get("normalized_kind") or ""),
            "items_json": json.dumps(items, ensure_ascii=False, indent=2),
            "fields_json": json.dumps(fields, ensure_ascii=False, indent=2),
        },
    )


def validate_plan(
    parsed: dict[str, Any] | None,
    *,
    doc_id: str,
    group_id: str,
    number_map: dict[str, str],
    fields: dict[str, str],
) -> tuple[bool, list[str], dict[str, Any]]:
    issues: list[str] = []
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    cleaned = dict(parsed)
    if str(cleaned.get("doc_id") or "") != str(doc_id):
        issues.append("doc_id_mismatch")
    if str(cleaned.get("group_id") or "") != str(group_id):
        issues.append("group_id_mismatch")
    edits = cleaned.get("edits")
    if edits is None:
        edits = []
    if not isinstance(edits, list):
        return False, ["edits_not_list"], cleaned
    normalized_edits: list[dict[str, Any]] = []
    allowed_fields = set(FIELD_ORDER)
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            issues.append(f"edit_{index}_not_object")
            continue
        field = str(edit.get("field") or "")
        source_item_no = str(edit.get("source_item_no") or "").strip()
        item_no = str(edit.get("item_no") or "").strip()
        original_token = str(edit.get("original_token") or edit.get("original_text") or "")
        replacement_token = str(edit.get("replacement_token") or edit.get("replacement_text") or "")
        confidence = str(edit.get("confidence") or "")
        role = str(edit.get("role") or "")
        if field not in allowed_fields:
            issues.append(f"edit_{index}_invalid_field:{field}")
        if source_item_no not in number_map:
            issues.append(f"edit_{index}_unknown_source_item_no:{source_item_no}")
        elif number_map[source_item_no] != item_no:
            issues.append(f"edit_{index}_item_no_mismatch:{source_item_no}->{item_no}")
        if source_item_no == item_no:
            issues.append(f"edit_{index}_unneeded_same_number:{source_item_no}")
        if not original_token or not replacement_token:
            issues.append(f"edit_{index}_empty_text")
        if field in fields and original_token and original_token not in fields[field]:
            issues.append(f"edit_{index}_original_text_not_found:{field}:{source_item_no}")
        if confidence not in {"high", "medium", "low"}:
            issues.append(f"edit_{index}_invalid_confidence:{confidence}")
        normalized_edits.append(
            {
                "field": field,
                "role": role,
                "source_item_no": source_item_no,
                "item_no": item_no,
                "original_token": original_token,
                "replacement_token": replacement_token,
                "confidence": confidence,
            }
        )
    cleaned["edits"] = normalized_edits
    if not isinstance(cleaned.get("warnings"), list):
        cleaned["warnings"] = []
    return not issues, issues, cleaned


def apply_edits(fields: dict[str, str], edits: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    projected = dict(fields)
    applied: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, edit in enumerate(edits):
        field = str(edit.get("field") or "")
        original_token = str(edit.get("original_token") or "")
        replacement_token = str(edit.get("replacement_token") or "")
        if field not in projected:
            issues.append(f"apply_{index}_field_missing:{field}")
            continue
        if original_token not in projected[field]:
            issues.append(f"apply_{index}_original_text_not_found:{field}:{edit.get('source_item_no')}")
            continue
        projected[field] = projected[field].replace(original_token, replacement_token, 1)
        applied.append(edit)
    return projected, applied, issues


def render_html_text(text: str) -> str:
    escaped = html.escape(str(text or ""))
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


def render_index(records: list[dict[str, Any]], out_path: Path) -> None:
    sections: list[str] = []
    for record in records:
        fields = record.get("fields") or {}
        field_html = []
        for field in FIELD_ORDER:
            value = fields.get(field)
            if not str(value or "").strip():
                continue
            klass = "answerish" if field in {"answer", "guide", "explanation", "sample_answer", "teaching_note"} else ""
            field_html.append(
                f'<section class="{klass}"><h3>{html.escape(FIELD_LABELS.get(field, field))}</h3>{render_html_text(value)}</section>'
            )
        edit_count = len(record.get("applied_edits") or [])
        issue_count = len(record.get("issues") or [])
        sections.append(
            '<article class="group">'
            f'<h2>{html.escape(str(record.get("group_id") or ""))} '
            f'<span>{html.escape(str(record.get("parent_kind") or ""))} · edits={edit_count} · issues={issue_count}</span></h2>'
            f'{"".join(field_html)}'
            "</article>"
        )
    out_path.write_text(
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{margin:0;background:#eef2f5;color:#1f2933;font:16px/1.72 "Times New Roman","Microsoft YaHei",serif}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #d0d7de;padding:14px 28px}
h1{margin:0;font:600 18px/1.35 "Microsoft YaHei",sans-serif}
main{width:min(1080px,calc(100vw - 32px));margin:22px auto 56px}
.group{margin:0 0 22px;padding:22px 26px;background:#fffefa;border:1px solid #d0d7de;border-radius:6px}
h2{margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid #d0d7de;font:700 20px/1.3 "Microsoft YaHei",sans-serif}
h2 span{color:#667085;font-size:13px;font-weight:500}
h3{margin:14px 0 6px;color:#0f766e;font:700 14px/1.35 "Microsoft YaHei",sans-serif}
p{margin:7px 0;white-space:pre-wrap}.answerish{color:#8a4b00;padding-top:8px;border-top:1px dashed #d9a65f}
</style></head><body><header><h1>父组源式局部编号归一化预览</h1></header><main>"""
        + "\n".join(sections)
        + "</main></body></html>",
        encoding="utf-8",
    )


def write_group_md(record: dict[str, Any], out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {record.get('group_id')} {record.get('parent_kind')}", ""]
    for field in FIELD_ORDER:
        value = (record.get("fields") or {}).get(field)
        if not str(value or "").strip():
            continue
        lines.extend([f"## {FIELD_LABELS.get(field, field)}", "", str(value).strip(), ""])
    path = out_dir / f"{record.get('group_id')}.local_number.normalized.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def process_record(
    *,
    config: dict[str, Any],
    normalized_record: dict[str, Any],
    itemized_record: dict[str, Any],
    doc_id: str,
    doc_key: str,
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
    no_model: bool,
) -> dict[str, Any]:
    group_id = str(normalized_record.get("group_id") or "")
    fields = {key: str(value or "") for key, value in (normalized_record.get("fields") or {}).items()}
    number_map = {
        str(item.get("source_item_no") or "").strip(): str(item.get("item_no") or "").strip()
        for item in itemized_record.get("items") or []
        if str(item.get("source_item_no") or "").strip() and str(item.get("item_no") or "").strip()
    }
    needed = {src: local for src, local in number_map.items() if src != local}
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    prompt = render_user_prompt(config, user_template, normalized_record=normalized_record, itemized_record=itemized_record, doc_id=doc_id, doc_key=doc_key)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": prompt})
    if no_model or not needed:
        record = {
            "group_id": group_id,
            "parent_kind": itemized_record.get("parent_kind") or normalized_record.get("normalized_kind"),
            "item_count": len(itemized_record.get("items") or []),
            "number_map": number_map,
            "fields": fields,
            "applied_edits": [],
            "plan_warnings": [],
            "issues": ["no_model"] if no_model and needed else [],
            "status": "skipped_no_edits_needed" if not needed else "skipped_no_model",
        }
        return record
    timeout = int((config.get("runner") or {}).get("per_group_timeout_seconds") or 240)
    max_attempts = int((config.get("runner") or {}).get("max_group_attempts") or 3)
    last_issues: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            result = call_model(config, system_prompt, prompt, api_key, timeout)
            write_json(raw_dir / f"attempt{attempt}.raw.json", result["raw_response"])
            (raw_dir / f"attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result.get("parsed") is not None:
                write_json(raw_dir / f"attempt{attempt}.parsed.json", result["parsed"])
            ok, plan_issues, cleaned = validate_plan(
                result.get("parsed"),
                doc_id=doc_key,
                group_id=group_id,
                number_map=number_map,
                fields=fields,
            )
            if not ok:
                last_issues = plan_issues
                write_json(raw_dir / f"attempt{attempt}.issues.json", plan_issues)
                continue
            projected, applied, apply_issues = apply_edits(fields, cleaned.get("edits") or [])
            status = "ok" if not apply_issues else "needs_review"
            return {
                "group_id": group_id,
                "parent_kind": itemized_record.get("parent_kind") or normalized_record.get("normalized_kind"),
                "item_count": len(itemized_record.get("items") or []),
                "number_map": number_map,
                "fields": projected,
                "applied_edits": applied,
                "plan_warnings": cleaned.get("warnings") or [],
                "issues": apply_issues,
                "status": status,
                "usage": result.get("usage") or {},
                "elapsed_seconds": result.get("elapsed_seconds"),
                "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
            }
        except Exception as exc:  # noqa: BLE001
            last_issues = [repr(exc)]
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": repr(exc)})
    return {
        "group_id": group_id,
        "parent_kind": itemized_record.get("parent_kind") or normalized_record.get("normalized_kind"),
        "item_count": len(itemized_record.get("items") or []),
        "number_map": number_map,
        "fields": fields,
        "applied_edits": [],
        "plan_warnings": [],
        "issues": last_issues or ["unknown_failure"],
        "status": "failed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--normalized", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-output-name", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--only-groups", default="")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    normalized = read_json(args.normalized)
    itemized = read_json(args.itemized)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    api_key = os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.no_model and not api_key:
        raise SystemExit(f"missing api key env: {config.get('api_key_env')}")
    parents = {record.get("group_id"): record for record in normalized.get("records") or []}
    itemized_records = [record for record in itemized.get("records") or [] if record.get("group_id") in parents]
    if args.only_groups.strip():
        wanted = {item.strip() for item in args.only_groups.split(",") if item.strip()}
        itemized_records = [record for record in itemized_records if str(record.get("group_id") or "") in wanted]
    if args.max_groups:
        itemized_records = itemized_records[: args.max_groups]
    output_root = Path(str(config.get("owned_output_root") or "outputs/english_docx_group_local_number_normalizer_v0_1"))
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    doc_name = args.doc_output_name or str(normalized.get("doc_id") or args.normalized.parent.name)
    doc_key = "doc_" + sha256_text(str(normalized.get("doc_id") or doc_name))[:12]
    out_dir = output_root / args.run_id / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_args = [
        {
            "config": config,
            "normalized_record": parents[record.get("group_id")],
            "itemized_record": record,
            "doc_id": str(normalized.get("doc_id") or ""),
            "doc_key": doc_key,
            "system_prompt": system_prompt,
            "user_template": user_template,
            "api_key": api_key,
            "out_dir": out_dir,
            "no_model": args.no_model,
        }
        for record in itemized_records
    ]
    max_workers = 1 if args.no_model else int((config.get("runner") or {}).get("max_workers") or 1)
    records: list[dict[str, Any]] = []
    if max_workers <= 1:
        for item in worker_args:
            records.append(process_record(**item))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_record, **item) for item in worker_args]
            for future in concurrent.futures.as_completed(futures):
                records.append(future.result())
        records.sort(key=lambda item: str(item.get("group_id") or ""))

    md_paths = [write_group_md(record, out_dir / "groups_md") for record in records]
    payload = {
        "schema_version": "english_docx_group_local_number_normalizer_results.v0.1",
        "doc_id": normalized.get("doc_id"),
        "run_id": args.run_id,
        "source_normalized_groups": safe_rel(args.normalized),
        "source_itemized_groups": safe_rel(args.itemized),
        "records": records,
    }
    write_json(out_dir / "locally_numbered_groups.json", payload)
    render_index(records, out_dir / "index.html")
    summary = {
        "schema_version": "english_docx_group_local_number_normalizer_summary.v0.1",
        "doc_id": normalized.get("doc_id"),
        "run_id": args.run_id,
        "status_counts": dict(Counter(record.get("status") for record in records)),
        "group_count": len(records),
        "applied_edit_count": sum(len(record.get("applied_edits") or []) for record in records),
        "issue_count": sum(len(record.get("issues") or []) for record in records),
        "usage": {
            "total_tokens": sum(int((record.get("usage") or {}).get("total_tokens") or 0) for record in records),
            "prompt_tokens": sum(int((record.get("usage") or {}).get("prompt_tokens") or 0) for record in records),
            "completion_tokens": sum(int((record.get("usage") or {}).get("completion_tokens") or 0) for record in records),
        },
        "artifacts": {
            "locally_numbered_groups": safe_rel(out_dir / "locally_numbered_groups.json"),
            "summary": safe_rel(out_dir / "summary.json"),
            "index": safe_rel(out_dir / "index.html"),
            "groups_md_dir": safe_rel(out_dir / "groups_md"),
            "markdown_files": [safe_rel(Path(path)) for path in md_paths],
        },
    }
    write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
