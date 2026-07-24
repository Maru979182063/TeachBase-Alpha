from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_grouper_membership_v01.yaml"
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


def source_order(block_id: str) -> int:
    try:
        return int(str(block_id).rsplit("_", 1)[-1])
    except ValueError:
        return -1


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
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


def load_tags(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    tags = payload.get("tags") or payload.get("block_tags") or []
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


def block_for_model(block: dict[str, Any], tag: dict[str, Any], preview_chars: int) -> dict[str, Any]:
    return {
        "block_id": block["block_id"],
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "block_role": tag.get("primary_role", "unknown"),
        "display_markdown_preview": compact_text(block.get("display_markdown", ""), preview_chars),
        "text_preview": compact_text(block.get("text", ""), preview_chars),
        "formula_count": block.get("formula_count", 0),
        "image_ref_count": block.get("image_ref_count", 0),
    }


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
                window_id=f"m_{index:04d}",
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


def validate_membership(
    payload: dict[str, Any] | None,
    valid_ids: set[str],
    eligible_group_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return [], [], [{"type": "invalid_json"}]
    if payload.get("schema") != "docx_question_grouper_membership_v0.1":
        issues.append({"type": "schema_mismatch", "value": payload.get("schema")})
    groups: list[dict[str, Any]] = []
    owner: dict[str, str] = {}
    for group in payload.get("groups", []) or []:
        if not isinstance(group, dict):
            issues.append({"type": "invalid_group_shape"})
            continue
        group_id = str(group.get("group_id") or f"g_{len(groups)+1:03d}")
        ids = [str(item) for item in group.get("block_ids", []) or []]
        unknown = [block_id for block_id in ids if block_id not in valid_ids]
        if unknown:
            issues.append({"type": "unknown_block_id", "group_id": group_id, "block_ids": unknown})
            ids = [block_id for block_id in ids if block_id in valid_ids]
        deduped = sorted(dict.fromkeys(ids), key=source_order)
        if eligible_group_ids is not None:
            non_eligible = [block_id for block_id in deduped if block_id not in eligible_group_ids]
            if non_eligible:
                issues.append(
                    {
                        "type": "filtered_non_question_group_block",
                        "severity": "audit",
                        "group_id": group_id,
                        "block_ids": non_eligible,
                    }
                )
                deduped = [block_id for block_id in deduped if block_id in eligible_group_ids]
        for block_id in deduped:
            if block_id in owner:
                issues.append({"type": "duplicate_block_assignment", "block_id": block_id, "first_group": owner[block_id], "second_group": group_id})
            owner[block_id] = group_id
        if deduped:
            groups.append({"group_id": group_id, "block_ids": deduped, "confidence": str(group.get("confidence") or "unknown")})
    ungrouped = [str(item) for item in payload.get("ungrouped_block_ids", []) or []]
    unknown_ungrouped = [block_id for block_id in ungrouped if block_id not in valid_ids]
    if unknown_ungrouped:
        issues.append({"type": "unknown_ungrouped_block_id", "block_ids": unknown_ungrouped})
    ungrouped = sorted(dict.fromkeys([block_id for block_id in ungrouped if block_id in valid_ids]), key=source_order)
    assigned = {block_id for group in groups for block_id in group["block_ids"]}
    required_ids = eligible_group_ids if eligible_group_ids is not None else valid_ids
    missing = sorted(required_ids - assigned - set(ungrouped), key=source_order)
    if missing:
        issues.append({"type": "unaccounted_block_ids", "block_ids": missing})
    return groups, ungrouped, issues


def has_blocking_issues(issues: list[dict[str, Any]]) -> bool:
    return any(str(issue.get("severity") or "blocking") != "audit" for issue in issues)


def render_membership_prompt(
    *,
    config: dict[str, Any],
    user_template: str,
    doc_id: str,
    sample_id: str,
    model_blocks: list[dict[str, Any]],
) -> str:
    return render_template(
        user_template,
        {
            "doc_id": doc_id,
            "sample_id": sample_id,
            "prompt_version": config.get("prompt_version"),
            "blocks_json": json.dumps(model_blocks, ensure_ascii=False, indent=2),
        },
    )


def run_one_sample(
    *,
    config: dict[str, Any],
    system_prompt: str,
    user_template: str,
    doc_id: str,
    sample_id: str,
    model_blocks: list[dict[str, Any]],
    out_dir: Path,
    api_key: str,
    timeout: int,
    resume: bool,
) -> dict[str, Any]:
    prompt = render_membership_prompt(config=config, user_template=user_template, doc_id=doc_id, sample_id=sample_id, model_blocks=model_blocks)
    raw_dir = out_dir / "raw_model_responses" / sample_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = raw_dir / "prompt.json"
    response_path = raw_dir / "response.json"
    content_path = raw_dir / "content.json"
    parsed_path = raw_dir / "parsed.json"
    write_json(prompt_path, {"blocks": model_blocks, "system_prompt": system_prompt, "user_prompt": prompt})
    if resume and parsed_path.exists():
        parsed = read_json(parsed_path)
        raw_response = read_json(response_path) if response_path.exists() else {}
        result = {"parsed": parsed, "raw_response": raw_response, "raw_content": "", "parse_error": "", "latency_seconds": 0.0, "source": "replay"}
    else:
        if not api_key:
            raise RuntimeError("missing_api_key_for_model_call")
        result = call_model(config, system_prompt, prompt, api_key, timeout)
        write_json(response_path, result["raw_response"])
        content_path.write_text(result["raw_content"], encoding="utf-8")
        if result["parsed"] is not None:
            write_json(parsed_path, result["parsed"])
        result["source"] = "model"
    valid_ids = {block["block_id"] for block in model_blocks}
    eligible_group_ids = {block["block_id"] for block in model_blocks if block.get("block_role") == "question_content"}
    groups, ungrouped, issues = validate_membership(result["parsed"], valid_ids, eligible_group_ids)
    return {
        "sample_id": sample_id,
        "source": result["source"],
        "groups": groups,
        "ungrouped_block_ids": ungrouped,
        "issues": issues,
        "parse_error": result.get("parse_error", ""),
        "latency_seconds": result.get("latency_seconds"),
        "usage": (result.get("raw_response") or {}).get("usage", {}),
    }


def merge_window_groups(raw_groups: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parent = list(range(len(raw_groups)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    owners: dict[str, int] = {}
    for index, group in enumerate(raw_groups):
        for block_id in group.get("block_ids", []):
            if block_id in owners:
                union(index, owners[block_id])
            else:
                owners[block_id] = index

    components: dict[int, list[dict[str, Any]]] = {}
    for index, group in enumerate(raw_groups):
        components.setdefault(find(index), []).append(group)

    audit: list[dict[str, Any]] = []
    merged: list[dict[str, Any]] = []
    for groups in components.values():
        ids = sorted({block_id for group in groups for block_id in group.get("block_ids", [])}, key=source_order)
        windows = sorted({str(group.get("window_id")) for group in groups})
        confidences = {str(group.get("confidence")) for group in groups}
        merged.append(
            {
                "group_id": "",
                "block_ids": ids,
                "confidence": "high" if "high" in confidences else ("medium" if "medium" in confidences else "low"),
                "merged_from_windows": windows,
                "raw_group_count": len(groups),
            }
        )
        if len(groups) > 1:
            audit.append({"type": "merge_shared_membership_groups", "windows": windows, "block_ids": ids, "raw_group_count": len(groups)})
    merged.sort(key=lambda item: source_order(item["block_ids"][0]) if item["block_ids"] else 10**9)
    for index, group in enumerate(merged, start=1):
        group["group_id"] = f"mg_{index:04d}"
    return merged, audit


def run_full_doc(args: argparse.Namespace, config: dict[str, Any], system_prompt: str, user_template: str, blocks: list[dict[str, Any]], tags: dict[str, dict[str, Any]], doc_id: str, out_dir: Path, api_key: str) -> dict[str, Any]:
    started = time.time()
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
    write_json(out_dir / "window_plan.json", {"schema_version": "docx_question_grouper_membership_window_plan.v0.1", "windows": [window.__dict__ for window in windows]})

    preview_chars = int(config.get("max_block_preview_chars") or 680)
    prepared: list[tuple[Window, list[dict[str, Any]]]] = []
    for window in windows:
        selected = blocks[window.input_start : window.input_end_exclusive]
        model_blocks = [block_for_model(block, tags.get(block["block_id"], {}), preview_chars) for block in selected]
        prepared.append((window, model_blocks))

    def run_window(item: tuple[Window, list[dict[str, Any]]]) -> dict[str, Any]:
        window, model_blocks = item
        try:
            result = run_one_sample(
                config=config,
                system_prompt=system_prompt,
                user_template=user_template,
                doc_id=doc_id,
                sample_id=window.window_id,
                model_blocks=model_blocks,
                out_dir=out_dir,
                api_key=api_key,
                timeout=args.timeout,
                resume=not args.no_resume,
            )
        except Exception as exc:  # Keep a failed window visible in artifacts instead of losing the whole run.
            result = {
                "sample_id": window.window_id,
                "source": "exception",
                "groups": [],
                "ungrouped_block_ids": [],
                "issues": [{"type": "membership_window_exception", "message": str(exc)}],
                "parse_error": "",
                "latency_seconds": None,
                "usage": {},
            }
        core_ids = {blocks[index]["block_id"] for index in range(window.core_start, window.core_end_exclusive)}
        for group in result["groups"]:
            group["window_id"] = window.window_id
            group["core_overlap"] = len(set(group["block_ids"]) & core_ids)
        return result

    concurrency = max(1, int(args.concurrency or 1))
    if concurrency == 1 or len(prepared) <= 1:
        all_results = [run_window(item) for item in prepared]
    else:
        by_window_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(run_window, item): item[0].window_id for item in prepared}
            for future in as_completed(futures):
                by_window_id[futures[future]] = future.result()
        all_results = [by_window_id[item[0].window_id] for item in prepared]

    raw_groups = [
        group
        for result in all_results
        for group in result.get("groups", [])
        if int(group.get("core_overlap") or 0) > 0
    ]
    final_groups, merge_audit = merge_window_groups(raw_groups)
    assigned = {block_id for group in final_groups for block_id in group["block_ids"]}
    all_ungrouped = sorted({block_id for result in all_results for block_id in result.get("ungrouped_block_ids", []) if block_id not in assigned}, key=source_order)
    issues = [{**issue, "sample_id": result["sample_id"]} for result in all_results for issue in result.get("issues", [])]
    usage = Counter()
    for result in all_results:
        usage.update({key: int(value or 0) for key, value in (result.get("usage") or {}).items() if isinstance(value, int)})

    write_json(out_dir / "window_results.json", {"schema_version": "docx_question_grouper_membership_window_results.v0.1", "windows": all_results})
    write_json(out_dir / "raw_membership_groups.json", {"schema_version": "docx_question_grouper_membership_raw_groups.v0.1", "groups": raw_groups})
    write_json(out_dir / "membership_groups.json", {"schema_version": "docx_question_grouper_membership_groups.v0.1", "groups": final_groups, "ungrouped_block_ids": all_ungrouped})
    write_json(out_dir / "merge_audit.json", {"schema_version": "docx_question_grouper_membership_merge_audit.v0.1", "items": merge_audit})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_grouper_membership_issues.v0.1", "issues": issues})
    summary = {
        "schema_version": "docx_question_grouper_membership_summary.v0.1",
        "status": "ok" if not has_blocking_issues(issues) else "needs_resolution",
        "doc_id": doc_id,
        "sample_id": args.sample_id or "full_doc",
        "mode": "full_doc_sliding_membership",
        "concurrency": concurrency,
        "block_count": len(blocks),
        "window_count": len(windows),
        "raw_group_count": len(raw_groups),
        "group_count": len(final_groups),
        "ungrouped_count": len(all_ungrouped),
        "issue_count": len(issues),
        "merge_action_count": len(merge_audit),
        "usage": dict(usage),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "membership_groups": safe_rel(out_dir / "membership_groups.json"),
            "raw_membership_groups": safe_rel(out_dir / "raw_membership_groups.json"),
            "merge_audit": safe_rel(out_dir / "merge_audit.json"),
            "issues": safe_rel(out_dir / "issues.json"),
            "window_results": safe_rel(out_dir / "window_results.json"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
        "runtime_seconds": round(time.time() - started, 3),
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks = load_blocks(args.paragraph_stream)
    tags = load_tags(args.block_tags)
    doc_id = args.doc_id or args.paragraph_stream.parent.name
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_grouper_membership_v0_1")
    sample_id = args.sample_id or "full_doc"
    out_dir = out_root / args.run_id / doc_id / sample_id
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if args.full_doc:
        return run_full_doc(args, config, system_prompt, user_template, blocks, tags, doc_id, out_dir, api_key)

    if args.block_start is None or args.block_end is None:
        raise RuntimeError("block_start_and_block_end_required_without_full_doc")
    selected = [block for block in blocks if args.block_start <= source_order(block["block_id"]) <= args.block_end]
    preview_chars = int(config.get("max_block_preview_chars") or 680)
    model_blocks = [block_for_model(block, tags.get(block["block_id"], {}), preview_chars) for block in selected]
    result = run_one_sample(
        config=config,
        system_prompt=system_prompt,
        user_template=user_template,
        doc_id=doc_id,
        sample_id=sample_id,
        model_blocks=model_blocks,
        out_dir=out_dir,
        api_key=api_key,
        timeout=args.timeout,
        resume=not args.no_resume,
    )
    groups = result["groups"]
    ungrouped = result["ungrouped_block_ids"]
    issues = result["issues"]
    role_counter = Counter((tags.get(block["block_id"], {}).get("primary_role") or "unknown") for block in selected)
    summary = {
        "schema_version": "docx_question_grouper_membership_summary.v0.1",
        "status": "ok" if not has_blocking_issues(issues) else "needs_resolution",
        "doc_id": doc_id,
        "sample_id": sample_id,
        "block_start": args.block_start,
        "block_end": args.block_end,
        "block_count": len(model_blocks),
        "group_count": len(groups),
        "ungrouped_count": len(ungrouped),
        "issue_count": len(issues),
        "parse_error": result.get("parse_error", ""),
        "latency_seconds": result.get("latency_seconds"),
        "usage": result.get("usage", {}),
        "role_counts": dict(role_counter),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "membership_groups": safe_rel(out_dir / "membership_groups.json"),
            "issues": safe_rel(out_dir / "issues.json"),
            "raw_model_responses": safe_rel(out_dir / "raw_model_responses" / sample_id),
        },
        "no_runtime_import": True,
        "no_database_write": True,
        "runtime_seconds": round(time.time() - started, 3),
    }
    write_json(out_dir / "membership_groups.json", {"schema_version": "docx_question_grouper_membership_groups.v0.1", "groups": groups, "ungrouped_block_ids": ungrouped})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_grouper_membership_issues.v0.1", "issues": issues})
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX question grouper explicit membership sample v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sample-id", default="")
    parser.add_argument("--block-start", type=int)
    parser.add_argument("--block-end", type=int)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--full-doc", action="store_true")
    parser.add_argument("--core-blocks", type=int, default=0)
    parser.add_argument("--stride-blocks", type=int, default=0)
    parser.add_argument("--max-windows", type=int, default=0)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
