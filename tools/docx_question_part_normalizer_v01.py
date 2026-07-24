from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_part_normalizer_v01.yaml"
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
        formula_findings = [item for item in (block.get("formula_findings") or []) if isinstance(item, dict)]
        blocks.append(
            {
                "block_id": block_id,
                "source_order": index,
                "source_block_type": str(block.get("source_block_type") or "docx_block"),
                "display_markdown": str(block.get("display_markdown") or block.get("markdown") or ""),
                "text": str(block.get("plain_text_lossy") or block.get("text") or ""),
                "formula_count": int(block.get("formula_count") or 0),
                "formula_findings": formula_findings,
                "image_refs": image_refs,
            }
        )
    return blocks


def block_for_model(block: dict[str, Any], tag: dict[str, Any], preview_chars: int) -> dict[str, Any]:
    image_refs = []
    for image in block.get("image_refs") or []:
        if not isinstance(image, dict):
            continue
        image_refs.append(
            {
                "asset_id": image.get("asset_id"),
                "format": image.get("format"),
                "width_px": image.get("width_px"),
                "height_px": image.get("height_px"),
                "bytes": image.get("bytes"),
                "mode": image.get("mode"),
            }
        )
    return {
        "block_id": block["block_id"],
        "source_order": block["source_order"],
        "source_block_type": block["source_block_type"],
        "block_role": tag.get("primary_role", "unknown"),
        "content_tags": tag.get("content_tags", []),
        "noise_tags": tag.get("noise_tags", []),
        "needs_resolution": bool(tag.get("needs_resolution", False)),
        "display_markdown_preview": compact_text(block.get("display_markdown", ""), preview_chars),
        "text_preview": compact_text(block.get("text", ""), preview_chars),
        "formula_count": block.get("formula_count", 0),
        "image_ref_count": len(block.get("image_refs") or []),
        "image_refs": image_refs,
    }


def section_context_for_group(
    group: dict[str, Any],
    tags: dict[str, dict[str, Any]],
    blocks_by_id: dict[str, dict[str, Any]],
    structural_section_ids: set[str],
    max_items: int,
    preview_chars: int,
) -> list[dict[str, Any]]:
    group_ids = group.get("block_ids") or []
    if not group_ids:
        return []
    first_order = source_order(str(group_ids[0]))
    candidates: list[dict[str, Any]] = []
    for block_id in structural_section_ids:
        tag = tags.get(block_id, {})
        if tag.get("primary_role") != "section":
            continue
        if source_order(block_id) >= first_order:
            continue
        block = blocks_by_id.get(block_id)
        if not block:
            continue
        candidates.append(block)
    candidates.sort(key=lambda item: int(item["source_order"]))
    return [
        {
            "block_id": block["block_id"],
            "source_order": block["source_order"],
            "block_role": "section",
            "display_markdown_preview": compact_text(block.get("display_markdown", ""), preview_chars),
            "text_preview": compact_text(block.get("text", ""), preview_chars),
        }
        for block in candidates[-max_items:]
    ]


def group_span(group: dict[str, Any]) -> tuple[int, int] | None:
    ids = [str(item) for item in group.get("block_ids", []) or []]
    if not ids:
        return None
    orders = [source_order(block_id) for block_id in ids]
    return min(orders), max(orders)


def recover_internal_blocks(
    group: dict[str, Any],
    blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
    base_ids = {str(item) for item in group.get("block_ids", []) or []}
    span = group_span(group)
    if span is None:
        return [], []
    start, end = span
    recovered: list[str] = []
    for block in blocks:
        block_id = block["block_id"]
        if block_id in base_ids:
            continue
        order = int(block["source_order"])
        if order < start or order > end:
            continue
        role = str(tags.get(block_id, {}).get("primary_role") or "unknown")
        if role in {"blank", "decorative", "document_meta"}:
            continue
        if not compact_text(block.get("display_markdown") or block.get("text") or "", 80):
            continue
        recovered.append(block_id)
    effective = sorted(base_ids | set(recovered), key=source_order)
    return effective, recovered


def structural_section_ids(groups: list[dict[str, Any]], tags: dict[str, dict[str, Any]]) -> set[str]:
    spans = [span for group in groups if (span := group_span(group)) is not None]
    result: set[str] = set()
    for block_id, tag in tags.items():
        if tag.get("primary_role") != "section":
            continue
        order = source_order(block_id)
        if any(start <= order <= end for start, end in spans):
            continue
        result.add(block_id)
    return result


def call_model(config: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str, timeout: int) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError("missing_api_key_for_model_call")
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


def validate_parts(
    payload: dict[str, Any] | None,
    *,
    doc_id: str,
    question_group_id: str,
    valid_ids: set[str],
    allowed_part_types: set[str],
    allowed_solution_policies: set[str],
    solution_policy_hint: str = "unknown",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return {
            "schema": "docx_question_part_normalizer_v0.1",
            "doc_id": doc_id,
            "question_group_id": question_group_id,
            "solution_policy": "unknown",
            "parts": [],
            "unassigned_block_ids": sorted(valid_ids, key=source_order),
            "warnings": [],
        }, [{"type": "invalid_json"}]

    if payload.get("schema") != "docx_question_part_normalizer_v0.1":
        issues.append({"type": "schema_mismatch", "value": payload.get("schema")})
    if payload.get("question_group_id") != question_group_id:
        issues.append({"type": "question_group_id_mismatch", "value": payload.get("question_group_id")})

    solution_policy = str(payload.get("solution_policy") or "unknown")
    if solution_policy not in allowed_solution_policies:
        issues.append({"type": "invalid_solution_policy", "value": solution_policy})
        solution_policy = "unknown"

    owner: dict[str, str] = {}
    parts: list[dict[str, Any]] = []
    for part in payload.get("parts", []) or []:
        if not isinstance(part, dict):
            issues.append({"type": "invalid_part_shape"})
            continue
        part_type = str(part.get("part_type") or "unknown")
        if part_type not in allowed_part_types:
            issues.append({"type": "invalid_part_type", "value": part_type})
            part_type = "unknown"
        raw_ids = [str(item) for item in part.get("block_ids", []) or []]
        unknown = [block_id for block_id in raw_ids if block_id not in valid_ids]
        if unknown:
            issues.append({"type": "unknown_block_id_in_part", "part_type": part_type, "block_ids": unknown})
        ids = sorted(dict.fromkeys([block_id for block_id in raw_ids if block_id in valid_ids]), key=source_order)
        for block_id in ids:
            if block_id in owner:
                issues.append({"type": "duplicate_block_assignment", "block_id": block_id, "first_part": owner[block_id], "second_part": part_type})
            owner[block_id] = part_type
        if ids:
            parts.append({"part_type": part_type, "block_ids": ids, "confidence": str(part.get("confidence") or "unknown")})

    unassigned = [str(item) for item in payload.get("unassigned_block_ids", []) or []]
    unknown_unassigned = [block_id for block_id in unassigned if block_id not in valid_ids]
    if unknown_unassigned:
        issues.append({"type": "unknown_unassigned_block_id", "block_ids": unknown_unassigned})
    unassigned = sorted(dict.fromkeys([block_id for block_id in unassigned if block_id in valid_ids]), key=source_order)

    assigned = set(owner)
    missing = sorted(valid_ids - assigned - set(unassigned), key=source_order)
    if missing:
        issues.append({"type": "unaccounted_question_block_ids", "block_ids": missing})
        unassigned = sorted(set(unassigned) | set(missing), key=source_order)

    overlap_unassigned = sorted(assigned & set(unassigned), key=source_order)
    if overlap_unassigned:
        issues.append({"type": "assigned_and_unassigned_block_ids", "block_ids": overlap_unassigned})
        unassigned = [block_id for block_id in unassigned if block_id not in assigned]

    stem_ids = [block_id for part in parts if part["part_type"] == "stem" for block_id in part["block_ids"]]
    if not stem_ids:
        issues.append({"type": "missing_stem_part", "severity": "warning"})
    part_types = {part["part_type"] for part in parts}
    if solution_policy_hint in allowed_solution_policies and solution_policy_hint != "unknown":
        if solution_policy_hint == "absent_expected" and "answer" not in part_types and "explanation" not in part_types:
            solution_policy = "absent_expected"
        elif solution_policy_hint in {"required", "optional"}:
            solution_policy = solution_policy_hint
    if solution_policy == "required" and "answer" not in part_types:
        issues.append({"type": "missing_required_answer_part", "severity": "warning"})
    if solution_policy == "required" and "explanation" not in part_types:
        issues.append({"type": "missing_required_explanation_part", "severity": "warning"})

    normalized = {
        "schema": "docx_question_part_normalizer_v0.1",
        "doc_id": doc_id,
        "question_group_id": question_group_id,
        "solution_policy": solution_policy,
        "parts": parts,
        "unassigned_block_ids": unassigned,
        "warnings": [str(item) for item in payload.get("warnings", []) if isinstance(item, str)],
    }
    return normalized, issues


def has_blocking_issues(issues: list[dict[str, Any]]) -> bool:
    return any(str(issue.get("severity") or "blocking") != "warning" for issue in issues)


def render_user_prompt(
    config: dict[str, Any],
    user_template: str,
    *,
    doc_id: str,
    question_group_id: str,
    section_context: list[dict[str, Any]],
    question_blocks: list[dict[str, Any]],
    solution_policy_hint: str,
) -> str:
    return render_template(
        user_template,
        {
            "doc_id": doc_id,
            "question_group_id": question_group_id,
            "prompt_version": config.get("prompt_version"),
            "solution_policy_hint": solution_policy_hint,
            "section_context_json": json.dumps(section_context, ensure_ascii=False, indent=2),
            "question_blocks_json": json.dumps(question_blocks, ensure_ascii=False, indent=2),
        },
    )


def normalize_one_group(
    *,
    config: dict[str, Any],
    system_prompt: str,
    user_template: str,
    doc_id: str,
    group: dict[str, Any],
    section_context: list[dict[str, Any]],
    question_blocks: list[dict[str, Any]],
    solution_policy_hint: str,
    out_dir: Path,
    api_key: str,
    timeout: int,
    resume: bool,
) -> dict[str, Any]:
    group_id = str(group.get("group_id"))
    prompt = render_user_prompt(
        config,
        user_template,
        doc_id=doc_id,
        question_group_id=group_id,
        section_context=section_context,
        question_blocks=question_blocks,
        solution_policy_hint=solution_policy_hint,
    )
    raw_dir = out_dir / "raw_model_responses" / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = raw_dir / "prompt.json"
    response_path = raw_dir / "response.json"
    content_path = raw_dir / "content.json"
    parsed_path = raw_dir / "parsed.json"
    write_json(prompt_path, {"section_context": section_context, "question_blocks": question_blocks, "system_prompt": system_prompt, "user_prompt": prompt})
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

    valid_ids = {block["block_id"] for block in question_blocks}
    normalized, issues = validate_parts(
        result["parsed"],
        doc_id=doc_id,
        question_group_id=group_id,
        valid_ids=valid_ids,
        allowed_part_types=set(config.get("allowed_part_types") or []),
        allowed_solution_policies=set(config.get("solution_policies") or []),
        solution_policy_hint=solution_policy_hint,
    )
    return {
        "question_group_id": group_id,
        "source": result["source"],
        "section_context": section_context,
        "normalization": normalized,
        "issues": issues,
        "status": "ok" if not has_blocking_issues(issues) else "needs_resolution",
        "parse_error": result.get("parse_error", ""),
        "latency_seconds": result.get("latency_seconds"),
        "usage": (result.get("raw_response") or {}).get("usage", {}),
    }


def build_question_blocks(block_ids: list[str], blocks_by_id: dict[str, dict[str, Any]], tags: dict[str, dict[str, Any]], preview_chars: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block_id in block_ids:
        block = blocks_by_id.get(str(block_id))
        if not block:
            continue
        items.append(block_for_model(block, tags.get(str(block_id), {}), preview_chars))
    return items


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    system_prompt = load_prompt(config, "system_prompt_path")
    user_template = load_prompt(config, "user_prompt_path")
    blocks = load_blocks(args.paragraph_stream)
    blocks_by_id = {block["block_id"]: block for block in blocks}
    tags = load_tags(args.block_tags)
    membership = read_json(args.membership_groups)
    groups = membership.get("groups") or []
    doc_id = args.doc_id or args.paragraph_stream.parent.name
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_part_normalizer_v0_1")
    out_dir = out_root / args.run_id / doc_id / "question_part_normalization"
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    preview_chars = int(config.get("max_block_preview_chars") or 1400)
    max_sections = int(config.get("max_section_context_blocks") or 3)
    solution_policy_hint = str(args.solution_policy_hint or "unknown")
    section_ids = structural_section_ids(groups, tags)

    selected_groups = groups
    if args.group_ids:
        wanted = {item.strip() for item in args.group_ids.split(",") if item.strip()}
        selected_groups = [group for group in groups if str(group.get("group_id")) in wanted]
    if args.max_groups:
        selected_groups = selected_groups[: args.max_groups]

    prepared: list[dict[str, Any]] = []
    for group in selected_groups:
        effective_block_ids, recovered_internal_block_ids = recover_internal_blocks(group, blocks, tags)
        section_context = section_context_for_group(group, tags, blocks_by_id, section_ids, max_sections, preview_chars)
        question_blocks = build_question_blocks(effective_block_ids, blocks_by_id, tags, preview_chars)
        prepared.append(
            {
                "group": group,
                "section_context": section_context,
                "question_blocks": question_blocks,
                "recovered_internal_block_ids": recovered_internal_block_ids,
            }
        )

    def run_prepared(item: dict[str, Any]) -> dict[str, Any]:
        group = item["group"]
        group_id = str(group.get("group_id"))
        try:
            result = normalize_one_group(
                config=config,
                system_prompt=system_prompt,
                user_template=user_template,
                doc_id=doc_id,
                group=group,
                section_context=item["section_context"],
                question_blocks=item["question_blocks"],
                solution_policy_hint=solution_policy_hint,
                out_dir=out_dir,
                api_key=api_key,
                timeout=args.timeout,
                resume=not args.no_resume,
            )
        except Exception as exc:  # Keep one failed question from erasing the whole regression artifact.
            result = {
                "question_group_id": group_id,
                "source": "exception",
                "section_context": item["section_context"],
                "normalization": {
                    "schema": "docx_question_part_normalizer_v0.1",
                    "doc_id": doc_id,
                    "question_group_id": group_id,
                    "solution_policy": "unknown",
                    "parts": [],
                    "unassigned_block_ids": [block["block_id"] for block in item["question_blocks"]],
                    "warnings": [],
                },
                "issues": [{"type": "normalizer_exception", "message": str(exc)}],
                "status": "needs_resolution",
                "parse_error": "",
                "latency_seconds": None,
                "usage": {},
            }
        result["recovered_internal_block_ids"] = item["recovered_internal_block_ids"]
        return result

    concurrency = max(1, int(args.concurrency or 1))
    if concurrency == 1 or len(prepared) <= 1:
        results = [run_prepared(item) for item in prepared]
    else:
        by_group_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(run_prepared, item): str(item["group"].get("group_id")) for item in prepared}
            for future in as_completed(futures):
                by_group_id[futures[future]] = future.result()
        results = [by_group_id[str(item["group"].get("group_id"))] for item in prepared]

    recovered_internal_block_count = sum(len(result.get("recovered_internal_block_ids") or []) for result in results)

    usage = Counter()
    for result in results:
        usage.update({key: int(value or 0) for key, value in (result.get("usage") or {}).items() if isinstance(value, int)})
    blocking = [issue for result in results for issue in result.get("issues", []) if str(issue.get("severity") or "blocking") != "warning"]
    warnings = [issue for result in results for issue in result.get("issues", []) if str(issue.get("severity") or "blocking") == "warning"]
    normalizations = [result["normalization"] for result in results]

    write_json(out_dir / "question_part_normalizations.json", {"schema_version": "docx_question_part_normalizer_results.v0.1", "items": normalizations})
    write_json(out_dir / "normalization_results_full.json", {"schema_version": "docx_question_part_normalizer_full_results.v0.1", "items": results})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_part_normalizer_issues.v0.1", "issues": [issue for result in results for issue in result.get("issues", [])]})
    summary = {
        "schema_version": "docx_question_part_normalizer_summary.v0.1",
        "status": "ok" if not blocking else "needs_resolution",
        "doc_id": doc_id,
        "mode": "per_question_group",
        "concurrency": concurrency,
        "input_group_count": len(groups),
        "processed_group_count": len(results),
        "ok_group_count": sum(1 for result in results if result.get("status") == "ok"),
        "needs_resolution_group_count": sum(1 for result in results if result.get("status") != "ok"),
        "blocking_issue_count": len(blocking),
        "warning_count": len(warnings),
        "recovered_internal_block_count": recovered_internal_block_count,
        "usage": dict(usage),
        "prompt_hashes": {"system": sha256_text(system_prompt), "user": sha256_text(user_template)},
        "artifacts": {
            "question_part_normalizations": safe_rel(out_dir / "question_part_normalizations.json"),
            "normalization_results_full": safe_rel(out_dir / "normalization_results_full.json"),
            "issues": safe_rel(out_dir / "issues.json"),
            "raw_model_responses": safe_rel(out_dir / "raw_model_responses"),
        },
        "no_runtime_import": True,
        "no_database_write": True,
        "runtime_seconds": round(time.time() - started, 3),
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX question part normalizer v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--membership-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--solution-policy-hint", default="unknown", choices=["required", "optional", "absent_expected", "unknown"])
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
