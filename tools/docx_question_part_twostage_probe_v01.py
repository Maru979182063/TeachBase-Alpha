from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import docx_question_part_normalizer_v01 as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_part_twostage_probe_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
        "raw_response": raw_response,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def compact_blocks(blocks: list[dict[str, Any]], tags: dict[str, dict[str, Any]], preview_chars: int) -> list[dict[str, Any]]:
    return [base.block_for_model(block, tags.get(block["block_id"], {}), preview_chars) for block in blocks]


def block_ids(parts_or_zones: list[dict[str, Any]], type_key: str, wanted: str) -> list[str]:
    ids: list[str] = []
    for item in parts_or_zones:
        if item.get(type_key) == wanted:
            ids.extend(str(block_id) for block_id in item.get("block_ids", []) or [])
    return sorted(dict.fromkeys(ids), key=base.source_order)


def validate_partition(items: list[dict[str, Any]], type_key: str, valid_ids: set[str], allowed: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            issues.append({"type": "invalid_item_shape"})
            continue
        item_type = str(item.get(type_key) or "")
        if item_type not in allowed:
            issues.append({"type": "invalid_type", "value": item_type})
            continue
        ids = sorted(dict.fromkeys(str(block_id) for block_id in item.get("block_ids", []) or [] if str(block_id) in valid_ids), key=base.source_order)
        for block_id in ids:
            if block_id in seen:
                issues.append({"type": "duplicate_block_assignment", "block_id": block_id, "first": seen[block_id], "second": item_type})
            seen[block_id] = item_type
        if ids:
            out.append({type_key: item_type, "block_ids": ids, "confidence": str(item.get("confidence") or "unknown")})
    missing = sorted(valid_ids - set(seen), key=base.source_order)
    if missing:
        issues.append({"type": "unaccounted_block_ids", "block_ids": missing})
    return out, issues


def make_prompt(template: str, values: dict[str, Any]) -> str:
    return render_template(template, {key: json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (list, dict)) else value for key, value in values.items()})


def run_model_with_retry(
    *,
    config: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    raw_dir: Path,
    stem: str,
    api_key: str,
    timeout: int,
    max_attempts: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    last: dict[str, Any] = {"parse_error": "not_run", "raw_response": {}, "usage": {}}
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            result = call_model(config, system_prompt, user_prompt, api_key, timeout)
            write_json(raw_dir / f"{stem}.attempt{attempt}.response.json", result["raw_response"])
            (raw_dir / f"{stem}.attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            if result["parsed"] is not None:
                write_json(raw_dir / f"{stem}.attempt{attempt}.parsed.json", result["parsed"])
            attempts.append({"attempt": attempt, "parse_error": result.get("parse_error", ""), "ok": result["parsed"] is not None})
            last = result
            if result["parsed"] is not None and not result.get("parse_error"):
                return result["parsed"], attempts, result
        except Exception as exc:  # noqa: BLE001
            attempts.append({"attempt": attempt, "parse_error": str(exc), "ok": False})
            last = {"parse_error": str(exc), "raw_response": {}, "usage": {}}
    return None, attempts, last


def normalize_one(
    *,
    config: dict[str, Any],
    prompts: dict[str, str],
    doc_id: str,
    group: dict[str, Any],
    section_context: list[dict[str, Any]],
    question_blocks: list[dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    raw_root: Path,
    api_key: str,
    timeout: int,
    max_attempts: int,
    solution_policy_hint: str,
) -> dict[str, Any]:
    group_id = str(group.get("group_id"))
    valid_ids = {block["block_id"] for block in question_blocks}
    zone_blocks = compact_blocks(question_blocks, tags, int(config.get("zone_preview_chars") or 420))
    zone_prompt = make_prompt(
        prompts["zone_user"],
        {
            "doc_id": doc_id,
            "question_group_id": group_id,
            "prompt_version": config.get("prompt_version"),
            "solution_policy_hint": solution_policy_hint,
            "section_context_json": section_context,
            "question_blocks_json": zone_blocks,
        },
    )
    raw_dir = raw_root / group_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "zone.prompt.json", {"system_prompt": prompts["zone_system"], "user_prompt": zone_prompt})
    zone_payload, zone_attempts, zone_raw = run_model_with_retry(
        config=config,
        system_prompt=prompts["zone_system"],
        user_prompt=zone_prompt,
        raw_dir=raw_dir,
        stem="zone",
        api_key=api_key,
        timeout=timeout,
        max_attempts=max_attempts,
    )
    if not isinstance(zone_payload, dict):
        return {
            "question_group_id": group_id,
            "status": "needs_resolution",
            "issues": [{"type": "zone_model_failed", "message": zone_raw.get("parse_error", "")}],
            "attempts": {"zone": zone_attempts},
            "normalization": {},
            "usage": (zone_raw.get("raw_response") or {}).get("usage", {}),
        }
    zones, zone_issues = validate_partition(
        zone_payload.get("zones") or [],
        "zone_type",
        valid_ids,
        {"problem_zone", "answer_zone", "explanation_zone", "teaching_zone", "other_evidence"},
    )
    problem_ids = block_ids(zones, "zone_type", "problem_zone")
    problem_blocks = [block for block in question_blocks if block["block_id"] in set(problem_ids)]
    problem_payload = {"parts": []}
    problem_attempts: list[dict[str, Any]] = []
    problem_raw: dict[str, Any] = {"raw_response": {}, "parse_error": ""}
    if problem_blocks:
        problem_model_blocks = compact_blocks(problem_blocks, tags, int(config.get("problem_preview_chars") or 900))
        problem_prompt = make_prompt(
            prompts["problem_user"],
            {
                "doc_id": doc_id,
                "question_group_id": group_id,
                "prompt_version": config.get("prompt_version"),
                "problem_blocks_json": problem_model_blocks,
            },
        )
        write_json(raw_dir / "problem.prompt.json", {"system_prompt": prompts["problem_system"], "user_prompt": problem_prompt})
        parsed_problem, problem_attempts, problem_raw = run_model_with_retry(
            config=config,
            system_prompt=prompts["problem_system"],
            user_prompt=problem_prompt,
            raw_dir=raw_dir,
            stem="problem",
            api_key=api_key,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        if isinstance(parsed_problem, dict):
            problem_payload = parsed_problem
    problem_parts, problem_issues = validate_partition(
        problem_payload.get("parts") or [],
        "part_type",
        set(problem_ids),
        {"stem", "subquestions", "options", "unknown"},
    )
    parts: list[dict[str, Any]] = []
    parts.extend(problem_parts)
    for zone_type, part_type in [
        ("answer_zone", "answer"),
        ("explanation_zone", "explanation"),
        ("teaching_zone", "teaching_note"),
        ("other_evidence", "unknown"),
    ]:
        ids = block_ids(zones, "zone_type", zone_type)
        if ids:
            parts.append({"part_type": part_type, "block_ids": ids, "confidence": "high"})
    assigned = {block_id for part in parts for block_id in part.get("block_ids", [])}
    unassigned = sorted(valid_ids - assigned, key=base.source_order)
    normalization = {
        "schema": "docx_question_part_normalizer_v0.1",
        "doc_id": doc_id,
        "question_group_id": group_id,
        "solution_policy": str(zone_payload.get("solution_policy") or solution_policy_hint or "unknown"),
        "parts": parts,
        "unassigned_block_ids": unassigned,
        "warnings": [str(item) for item in zone_payload.get("warnings", []) if isinstance(item, str)]
        + [str(item) for item in problem_payload.get("warnings", []) if isinstance(item, str)],
    }
    issues = zone_issues + problem_issues
    return {
        "question_group_id": group_id,
        "status": "ok" if not issues else "needs_resolution",
        "issues": issues,
        "attempts": {"zone": zone_attempts, "problem": problem_attempts},
        "zone_result": zone_payload,
        "problem_result": problem_payload,
        "normalization": normalization,
        "usage": Counter(
            {
                key: int(value or 0)
                for raw in [zone_raw, problem_raw]
                for key, value in ((raw.get("raw_response") or {}).get("usage") or {}).items()
                if isinstance(value, int)
            }
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config = read_json(args.config)
    prompts = {
        "zone_system": load_prompt(config, "zone_system_prompt_path"),
        "zone_user": load_prompt(config, "zone_user_prompt_path"),
        "problem_system": load_prompt(config, "problem_system_prompt_path"),
        "problem_user": load_prompt(config, "problem_user_prompt_path"),
    }
    blocks = base.load_blocks(args.paragraph_stream)
    blocks_by_id = {block["block_id"]: block for block in blocks}
    tags = base.load_tags(args.block_tags)
    membership = read_json(args.membership_groups)
    groups = membership.get("groups") or []
    wanted = {item.strip() for item in args.group_ids.split(",") if item.strip()}
    selected = [group for group in groups if not wanted or str(group.get("group_id")) in wanted]
    doc_id = args.doc_id or args.paragraph_stream.parent.name
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_question_part_twostage_probe_v0_1")
    out_dir = out_root / args.run_id / doc_id / str(config.get("output_dir_name") or "question_part_twostage_probe")
    raw_root = out_dir / "raw_model_responses"
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    section_ids = base.structural_section_ids(groups, tags)
    max_sections = int(config.get("max_section_context_blocks") or 3)
    runner = config.get("runner") or {}
    max_attempts = int(args.max_group_attempts or runner.get("max_group_attempts") or 1)
    prepared = []
    for group in selected:
        effective_ids, recovered = base.recover_internal_blocks(group, blocks, tags)
        section_context = base.section_context_for_group(group, tags, blocks_by_id, section_ids, max_sections, 280)
        question_blocks = [blocks_by_id[block_id] for block_id in effective_ids if block_id in blocks_by_id]
        prepared.append((group, section_context, question_blocks, recovered))

    def run_item(item: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]) -> dict[str, Any]:
        group, section_context, question_blocks, recovered = item
        result = normalize_one(
            config=config,
            prompts=prompts,
            doc_id=doc_id,
            group=group,
            section_context=section_context,
            question_blocks=question_blocks,
            tags=tags,
            raw_root=raw_root,
            api_key=api_key,
            timeout=args.timeout,
            max_attempts=max_attempts,
            solution_policy_hint=args.solution_policy_hint,
        )
        result["recovered_internal_block_ids"] = recovered
        return result

    if args.concurrency <= 1 or len(prepared) <= 1:
        results = [run_item(item) for item in prepared]
    else:
        by_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
            futures = {executor.submit(run_item, item): str(item[0].get("group_id")) for item in prepared}
            for future in as_completed(futures):
                by_id[futures[future]] = future.result()
        results = [by_id[str(item[0].get("group_id"))] for item in prepared]
    normalizations = [result["normalization"] for result in results if result.get("normalization")]
    usage = Counter()
    for result in results:
        usage.update(result.get("usage") or {})
    issues = [issue for result in results for issue in result.get("issues", [])]
    write_json(out_dir / "question_part_normalizations.json", {"schema_version": "docx_question_part_twostage_probe_results.v0.1", "items": normalizations})
    write_json(out_dir / "normalization_results_full.json", {"schema_version": "docx_question_part_twostage_probe_full_results.v0.1", "items": results})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_part_twostage_probe_issues.v0.1", "issues": issues})
    summary = {
        "schema_version": "docx_question_part_twostage_probe_summary.v0.1",
        "status": "ok" if not issues else "needs_resolution",
        "doc_id": doc_id,
        "input_group_count": len(groups),
        "processed_group_count": len(results),
        "ok_group_count": sum(1 for result in results if result.get("status") == "ok"),
        "needs_resolution_group_count": sum(1 for result in results if result.get("status") != "ok"),
        "issue_count": len(issues),
        "usage": dict(usage),
        "runtime_seconds": round(time.time() - started, 3),
        "artifacts": {
            "question_part_normalizations": base.safe_rel(out_dir / "question_part_normalizations.json"),
            "normalization_results_full": base.safe_rel(out_dir / "normalization_results_full.json"),
            "issues": base.safe_rel(out_dir / "issues.json"),
            "raw_model_responses": base.safe_rel(raw_root),
        },
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe two-stage DOCX question part normalization.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--membership-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-group-attempts", type=int, default=0)
    parser.add_argument("--solution-policy-hint", default="unknown", choices=["required", "optional", "absent_expected", "unknown"])
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
