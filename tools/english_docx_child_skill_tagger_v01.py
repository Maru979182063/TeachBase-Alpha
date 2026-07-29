from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "english_docx_native_md" / "child_skill_tagger_v01.json"
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


def child_for_model(child: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return {
        "item_id": child.get("item_id"),
        "item_no": child.get("item_no"),
        "item_kind": child.get("item_kind"),
        "question": compact(child.get("question") or "", max_chars),
        "options": compact(child.get("options") or "", max_chars),
        "answer": compact(child.get("answer") or "", 300),
        "explanation": compact(child.get("explanation") or "", max_chars),
    }


def render_user_prompt(
    config: dict[str, Any],
    template: str,
    *,
    doc_key: str,
    group: dict[str, Any],
) -> str:
    max_chars = int(config.get("max_child_text_chars") or 1200)
    children = [child_for_model(child, max_chars) for child in group.get("children") or []]
    return render_template(
        template,
        {
            "doc_key": doc_key,
            "group_id": str(group.get("group_id") or ""),
            "prompt_version": str(config.get("prompt_version") or ""),
            "parent_kind": str(group.get("parent_kind") or ""),
            "children_json": json.dumps(children, ensure_ascii=False, indent=2),
        },
    )


def validate_tags(parsed: dict[str, Any] | None, *, doc_key: str, group: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    if not isinstance(parsed, dict):
        return False, ["model_output_not_json_object"], {}
    issues: list[str] = []
    cleaned = dict(parsed)
    group_id = str(group.get("group_id") or "")
    if str(cleaned.get("doc_id") or "") != doc_key:
        issues.append("doc_id_mismatch")
    if str(cleaned.get("group_id") or "") != group_id:
        issues.append("group_id_mismatch")
    supplied = {str(child.get("item_id") or ""): str(child.get("item_no") or "") for child in group.get("children") or []}
    items = cleaned.get("items")
    if not isinstance(items, list):
        return False, issues + ["items_not_list"], cleaned
    seen: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"item_{index}_not_object")
            continue
        item_id = str(item.get("item_id") or "")
        item_no = str(item.get("item_no") or "")
        if item_id not in supplied:
            issues.append(f"unknown_item_id:{item_id}")
        elif supplied[item_id] != item_no:
            issues.append(f"item_no_mismatch:{item_id}")
        if item_id in seen:
            issues.append(f"duplicate_item_id:{item_id}")
        seen.add(item_id)
        secondary = item.get("secondary_tags_zh") or []
        if not isinstance(secondary, list):
            secondary = []
        normalized_items.append(
            {
                "item_id": item_id,
                "item_no": item_no,
                "primary_label_zh": str(item.get("primary_label_zh") or "未知"),
                "primary_label_en": str(item.get("primary_label_en") or "unknown"),
                "category": str(item.get("category") or "unknown"),
                "secondary_tags_zh": [str(value) for value in secondary[:3]],
                "evidence": str(item.get("evidence") or ""),
                "confidence": str(item.get("confidence") or "low"),
            }
        )
    missing = set(supplied) - seen
    for item_id in sorted(missing):
        issues.append(f"missing_item_id:{item_id}")
    cleaned["items"] = normalized_items
    if not isinstance(cleaned.get("warnings"), list):
        cleaned["warnings"] = []
    return not issues, issues, cleaned


def merge_tags(group: dict[str, Any], tag_result: dict[str, Any]) -> dict[str, Any]:
    tags = {item.get("item_id"): item for item in tag_result.get("items") or []}
    merged = dict(group)
    children = []
    for child in group.get("children") or []:
        updated = dict(child)
        updated["skill_tags"] = tags.get(child.get("item_id")) or {
            "primary_label_zh": "未知",
            "primary_label_en": "unknown",
            "category": "unknown",
            "secondary_tags_zh": [],
            "evidence": "",
            "confidence": "low",
        }
        children.append(updated)
    merged["children"] = children
    return merged


def process_group(
    *,
    config: dict[str, Any],
    group: dict[str, Any],
    doc_key: str,
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
    no_model: bool,
) -> dict[str, Any]:
    group_id = str(group.get("group_id") or "group")
    prompt = render_user_prompt(config, user_template, doc_key=doc_key, group=group)
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "prompt.json", {"system": system_prompt, "user": prompt})
    if no_model:
        return {
            "group_id": group_id,
            "status": "skipped_no_model",
            "tagged_group": group,
            "issues": ["no_model"],
            "usage": {},
        }
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
            ok, issues, cleaned = validate_tags(result.get("parsed"), doc_key=doc_key, group=group)
            if ok:
                return {
                    "group_id": group_id,
                    "status": "ok",
                    "tagged_group": merge_tags(group, cleaned),
                    "issues": [],
                    "warnings": cleaned.get("warnings") or [],
                    "usage": result.get("usage") or {},
                    "elapsed_seconds": result.get("elapsed_seconds"),
                    "prompt_sha256": sha256_text(system_prompt + "\n" + prompt),
                }
            last_issues = issues
            write_json(raw_dir / f"attempt{attempt}.issues.json", issues)
        except Exception as exc:  # noqa: BLE001
            last_issues = [repr(exc)]
            write_json(raw_dir / f"attempt{attempt}.exception.json", {"error": repr(exc)})
    return {
        "group_id": group_id,
        "status": "failed",
        "tagged_group": group,
        "issues": last_issues or ["unknown_failure"],
        "usage": {},
    }


def render_text(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = re.sub(
        r"\[\[CURRENT_BLANK_(\d+)\]\]",
        lambda match: f'<span class="current-blank" title="CURRENT_BLANK_{match.group(1)}"></span>',
        escaped,
    )
    return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


def render_index(groups: list[dict[str, Any]], out_path: Path) -> None:
    sections: list[str] = []
    for group in groups:
        child_bits: list[str] = []
        for child in group.get("children") or []:
            tag = child.get("skill_tags") or {}
            secondaries = " / ".join(tag.get("secondary_tags_zh") or [])
            child_bits.append(
                '<article class="child">'
                f'<h4>第 {html.escape(str(child.get("item_no") or ""))} 题 '
                f'<span>{html.escape(str(child.get("item_kind") or ""))}</span></h4>'
                f'<div class="tags"><b>{html.escape(str(tag.get("primary_label_zh") or ""))}</b>'
                f'<span>{html.escape(str(tag.get("category") or ""))}</span>'
                f'<em>{html.escape(secondaries)}</em></div>'
                f'<div class="evidence">{html.escape(str(tag.get("evidence") or ""))}</div>'
                f'<h5>题目</h5>{render_text(child.get("question") or "")}'
                f'<h5>答案</h5>{render_text(child.get("answer") or "")}'
                f'<h5>解析</h5>{render_text(child.get("explanation") or "")}'
                "</article>"
            )
        sections.append(
            '<section class="group">'
            f'<h2>{html.escape(str(group.get("group_id") or ""))} '
            f'<span>{html.escape(str(group.get("parent_kind") or ""))} · children={len(group.get("children") or [])}</span></h2>'
            f'{"".join(child_bits)}'
            "</section>"
        )
    out_path.write_text(
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{margin:0;background:#eef2f5;color:#1f2933;font:16px/1.65 "Times New Roman","Microsoft YaHei",serif}
header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #d0d7de;padding:14px 28px}
h1{margin:0;font:600 18px/1.35 "Microsoft YaHei",sans-serif}
main{width:min(1120px,calc(100vw - 32px));margin:22px auto 56px}
.group{margin:0 0 22px;padding:22px 26px;background:#fffefa;border:1px solid #d0d7de;border-radius:6px}
h2{margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid #d0d7de;font:700 20px/1.3 "Microsoft YaHei",sans-serif}
h2 span,h4 span{color:#667085;font-size:13px;font-weight:500}
.child{padding:12px 14px;margin:10px 0;background:#fff;border:1px solid #d8dee5;border-radius:6px}
h4{margin:0 0 8px;color:#1d4ed8;font:700 15px/1.35 "Microsoft YaHei",sans-serif}
h5{margin:10px 0 3px;color:#0f766e;font:700 13px/1.35 "Microsoft YaHei",sans-serif}
p{margin:5px 0;white-space:pre-wrap}.tags{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
.tags b{display:inline-block;padding:2px 8px;border-radius:999px;background:#e0f2fe;color:#075985;font:700 13px/1.4 "Microsoft YaHei",sans-serif}
.tags span,.tags em{color:#667085;font:12px/1.4 "Microsoft YaHei",sans-serif}.evidence{color:#8a4b00;font:13px/1.5 "Microsoft YaHei",sans-serif}
.current-blank{display:inline-block;width:5.2em;height:.95em;margin:0 .18em;border-bottom:2px solid #111827;vertical-align:-.08em;background:#fff7cc}
</style></head><body><header><h1>英语子题考点标签预览</h1></header><main>"""
        + "\n".join(sections)
        + "</main></body></html>",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-parent-child", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-output-name", default="")
    parser.add_argument("--only-groups", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    parent_child = read_json(args.input_parent_child)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    api_key = os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.no_model and not api_key:
        raise SystemExit(f"missing api key env: {config.get('api_key_env')}")
    groups = list(parent_child.get("records") or [])
    if args.only_groups.strip():
        wanted = {item.strip() for item in args.only_groups.split(",") if item.strip()}
        groups = [group for group in groups if str(group.get("group_id") or "") in wanted]
    if args.max_groups:
        groups = groups[: args.max_groups]
    output_root = Path(str(config.get("owned_output_root") or "outputs/english_docx_child_skill_tagger_v0_1"))
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    doc_name = args.doc_output_name or str(parent_child.get("doc_id") or args.input_parent_child.parent.name)
    doc_key = "doc_" + sha256_text(str(parent_child.get("doc_id") or doc_name))[:12]
    out_dir = output_root / args.run_id / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)
    worker_args = [
        {
            "config": config,
            "group": group,
            "doc_key": doc_key,
            "system_prompt": system_prompt,
            "user_template": user_template,
            "api_key": api_key,
            "out_dir": out_dir,
            "no_model": args.no_model,
        }
        for group in groups
    ]
    max_workers = 1 if args.no_model else int((config.get("runner") or {}).get("max_workers") or 1)
    results: list[dict[str, Any]] = []
    if max_workers <= 1:
        for item in worker_args:
            results.append(process_group(**item))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_group, **item) for item in worker_args]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: str(item.get("group_id") or ""))
    tagged_groups = [result.get("tagged_group") for result in results if result.get("tagged_group")]
    payload = {
        "schema_version": "english_docx_child_skill_tagger_results.v0.1",
        "doc_id": parent_child.get("doc_id"),
        "run_id": args.run_id,
        "source_parent_child_groups": safe_rel(args.input_parent_child),
        "records": tagged_groups,
        "results": [
            {key: value for key, value in result.items() if key != "tagged_group"}
            for result in results
        ],
    }
    write_json(out_dir / "tagged_parent_child_groups.json", payload)
    render_index(tagged_groups, out_dir / "index.html")
    label_counts = Counter(
        ((child.get("skill_tags") or {}).get("primary_label_zh") or "未知")
        for group in tagged_groups
        for child in group.get("children") or []
    )
    summary = {
        "schema_version": "english_docx_child_skill_tagger_summary.v0.1",
        "doc_id": parent_child.get("doc_id"),
        "run_id": args.run_id,
        "status_counts": dict(Counter(result.get("status") for result in results)),
        "group_count": len(results),
        "child_count": sum(len((result.get("tagged_group") or {}).get("children") or []) for result in results),
        "label_counts": dict(label_counts),
        "issue_count": sum(len(result.get("issues") or []) for result in results),
        "usage": {
            "total_tokens": sum(int((result.get("usage") or {}).get("total_tokens") or 0) for result in results),
            "prompt_tokens": sum(int((result.get("usage") or {}).get("prompt_tokens") or 0) for result in results),
            "completion_tokens": sum(int((result.get("usage") or {}).get("completion_tokens") or 0) for result in results),
        },
        "artifacts": {
            "tagged_parent_child_groups": safe_rel(out_dir / "tagged_parent_child_groups.json"),
            "summary": safe_rel(out_dir / "summary.json"),
            "index": safe_rel(out_dir / "index.html"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
