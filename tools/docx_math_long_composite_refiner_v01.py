from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = "docx_math_long_composite_plan_v0.1"
SEGMENT_SCHEMA = "docx_math_long_composite_segment_v0.1"
PACKET_SCHEMA = "docx_math_long_composite_refined_packet_v0.1"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value or "")).strip("_") or "doc"


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


def asset_tokens(text: str) -> list[str]:
    return sorted(set(re.findall(r"asset://([A-Za-z0-9_\-]+)", str(text or ""))))


def split_field_blocks(field: dict[str, Any]) -> list[dict[str, Any]]:
    block_ids = [str(item) for item in field.get("block_ids") or []]
    markdown = str(field.get("markdown") or "")
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", markdown) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for index, block_id in enumerate(block_ids):
        chunk = chunks[index] if index < len(chunks) else ""
        blocks.append({"block_id": block_id, "markdown": chunk, "asset_ids": asset_tokens(chunk)})
    if not block_ids and markdown.strip():
        blocks.append({"block_id": "", "markdown": markdown.strip(), "asset_ids": asset_tokens(markdown)})
    return blocks


def load_drafts(input_root: Path, doc_id_contains: list[str], group_ids: set[str]) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    for path in sorted(input_root.glob("*/source_backed_draft/docx_math_source_backed_draft_items.json")):
        payload = read_json(path)
        doc_id = str(payload.get("doc_id") or "")
        if doc_id_contains and not any(fragment in doc_id for fragment in doc_id_contains):
            continue
        for draft in payload.get("draft_items") or []:
            if group_ids and draft.get("source_group_id") not in group_ids and draft.get("draft_id") not in group_ids:
                continue
            drafts.append(draft)
    return drafts


def build_planner_input(draft: dict[str, Any]) -> dict[str, Any]:
    fields = draft.get("fields") or {}
    field_blocks = {
        name: split_field_blocks(fields.get(name) or {})
        for name in ["stem", "subquestions", "answer", "explanation", "teaching_note", "context"]
    }
    return {
        "draft_id": draft.get("draft_id"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "record_kind": draft.get("record_kind"),
        "solution_policy": draft.get("solution_policy"),
        "route_signals": {
            "stem_block_count": len(field_blocks["stem"]),
            "subquestion_block_count": len(field_blocks["subquestions"]),
            "answer_block_count": len(field_blocks["answer"]),
            "explanation_block_count": len(field_blocks["explanation"]),
            "asset_count": len(draft.get("asset_refs") or []),
        },
        "field_blocks": field_blocks,
        "asset_refs": draft.get("asset_refs") or [],
        "source_refs": draft.get("source_refs") or [],
    }


def allowed_block_ids(planner_input: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for blocks in (planner_input.get("field_blocks") or {}).values():
        for block in blocks:
            if block.get("block_id"):
                out.add(str(block["block_id"]))
    return out


def allowed_asset_ids(planner_input: dict[str, Any]) -> set[str]:
    out = set()
    for asset in planner_input.get("asset_refs") or []:
        if isinstance(asset, dict) and asset.get("asset_id"):
            out.add(str(asset["asset_id"]))
    for blocks in (planner_input.get("field_blocks") or {}).values():
        for block in blocks:
            out.update(str(item) for item in block.get("asset_ids") or [])
    return out


def call_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_plan(plan: dict[str, Any], planner_input: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if plan.get("schema") != PLAN_SCHEMA:
        errors.append({"path": "$.schema", "message": "invalid schema"})
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append({"path": "$.segments", "message": "missing segments"})
        return {"valid": False, "errors": errors}
    block_ids = allowed_block_ids(planner_input)
    asset_ids = allowed_asset_ids(planner_input)
    seen: set[str] = set()
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append({"path": f"$.segments[{index}]", "message": "must be object"})
            continue
        segment_id = str(segment.get("segment_id") or "")
        if not segment_id:
            errors.append({"path": f"$.segments[{index}].segment_id", "message": "empty segment_id"})
        if segment_id in seen:
            errors.append({"path": f"$.segments[{index}].segment_id", "message": "duplicate segment_id"})
        seen.add(segment_id)
        if segment.get("role") != "stem" and not str(segment.get("label") or "").strip():
            errors.append({"path": f"$.segments[{index}].label", "message": "empty segment label"})
        for key in ["question_block_ids", "answer_block_ids", "explanation_block_ids"]:
            if not isinstance(segment.get(key), list):
                errors.append({"path": f"$.segments[{index}].{key}", "message": "must be array"})
                continue
            for value in segment.get(key) or []:
                if value not in block_ids:
                    errors.append({"path": f"$.segments[{index}].{key}", "message": f"invented block id {value}"})
        for value in segment.get("asset_ids") or []:
            if value not in asset_ids:
                errors.append({"path": f"$.segments[{index}].asset_ids", "message": f"invented asset id {value}"})
    return {"valid": not errors, "errors": errors}


def blocks_by_id(planner_input: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for field_name, blocks in (planner_input.get("field_blocks") or {}).items():
        for block in blocks:
            block_id = str(block.get("block_id") or "")
            if block_id:
                out[block_id] = {**block, "field": field_name}
    return out


def materialize_segment_input(segment: dict[str, Any], planner_input: dict[str, Any]) -> dict[str, Any]:
    by_id = blocks_by_id(planner_input)
    def get_blocks(key: str) -> list[dict[str, Any]]:
        return [by_id[value] for value in segment.get(key) or [] if value in by_id]
    return {
        "doc_id": planner_input.get("doc_id"),
        "source_draft_id": planner_input.get("draft_id"),
        "source_group_id": planner_input.get("source_group_id"),
        "segment_id": segment.get("segment_id"),
        "label": segment.get("label"),
        "level": segment.get("level"),
        "parent_id": segment.get("parent_id"),
        "role": segment.get("role"),
        "child_segment_ids": segment.get("children") or [],
        "question_blocks": get_blocks("question_block_ids"),
        "answer_blocks": get_blocks("answer_block_ids"),
        "explanation_blocks": get_blocks("explanation_block_ids"),
        "asset_ids": segment.get("asset_ids") or [],
    }


def validate_segment(segment: dict[str, Any], segment_input: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if segment.get("schema") != SEGMENT_SCHEMA:
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if segment.get("segment_id") != segment_input.get("segment_id"):
        errors.append({"path": "$.segment_id", "message": "segment_id mismatch"})
    if segment.get("role") not in {"stem", "subquestion", "context"}:
        errors.append({"path": "$.role", "message": "invalid role"})
    if segment.get("role") != "stem" and not str(segment.get("label") or "").strip():
        errors.append({"path": "$.label", "message": "empty label"})
    allowed_assets = set(segment_input.get("asset_ids") or [])
    all_text = "\n".join(
        str(segment.get(key) or "") for key in ["prompt_md", "answer_md", "explanation_md"]
    )
    for asset_id in asset_tokens(all_text):
        if asset_id not in allowed_assets:
            errors.append({"path": "$", "message": f"invented asset {asset_id}"})
    for key in ["prompt_md", "answer_md", "explanation_md"]:
        value = str(segment.get(key) or "")
        if value.count("$") % 2:
            errors.append({"path": f"$.{key}", "message": "unbalanced_math_dollar_delimiter"})
        if "\t" in value:
            errors.append({"path": f"$.{key}", "message": "lost_latex_backslash_tab_escape"})
        if re.search(r"(?<!\\)\b(?:triangle|angle|frac|sqrt|parallel|perp)\b", value):
            errors.append({"path": f"$.{key}", "message": "lost_or_bare_latex_command"})
    return {"valid": not errors, "errors": errors}


def refine_segment(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    system_prompt: str,
    user_template: str,
    repair_template: str,
    segment_input: dict[str, Any],
    api_key: str,
    out_dir: Path,
) -> dict[str, Any]:
    segment_id = str(segment_input["segment_id"])
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(segment_input, ensure_ascii=False, indent=2),
            "segment_id": segment_id,
            "label": segment_input.get("label") or "",
        },
    )
    result = call_model(config, node, system_prompt, user_prompt, api_key)
    segment_dir = out_dir / "segments" / safe_name(segment_id)
    write_json(segment_dir / "segment_input.json", segment_input)
    write_text(segment_dir / "used_system_prompt.md", system_prompt)
    write_text(segment_dir / "used_user_prompt.md", user_prompt)
    write_json(segment_dir / "raw_response.json", result["raw_response"])
    write_text(segment_dir / "raw_content.txt", result["raw_content"])
    if result["parsed"] is None:
        refined = {
            "schema": SEGMENT_SCHEMA,
            "segment_id": segment_id,
            "label": segment_input.get("label") or "",
            "level": segment_input.get("level") or 0,
            "parent_id": segment_input.get("parent_id") or "",
            "role": segment_input.get("role") or "subquestion",
            "prompt_md": "\n\n".join(block["markdown"] for block in segment_input.get("question_blocks") or []),
            "answer_md": "\n\n".join(block["markdown"] for block in segment_input.get("answer_blocks") or []),
            "explanation_md": "\n\n".join(block["markdown"] for block in segment_input.get("explanation_blocks") or []),
            "asset_ids": segment_input.get("asset_ids") or [],
            "source_refs": {
                "question_block_ids": [block["block_id"] for block in segment_input.get("question_blocks") or []],
                "answer_block_ids": [block["block_id"] for block in segment_input.get("answer_blocks") or []],
                "explanation_block_ids": [block["block_id"] for block in segment_input.get("explanation_blocks") or []],
            },
            "warnings": [{"code": "segment_parse_failed", "message": result["parse_error"]}],
        }
    else:
        refined = result["parsed"]
    if isinstance(refined, dict):
        refined["segment_id"] = segment_id
        refined["label"] = segment_input.get("label") or ""
        refined["level"] = segment_input.get("level") or 0
        refined["parent_id"] = segment_input.get("parent_id") or ""
        refined["role"] = segment_input.get("role") or "subquestion"
    validation = validate_segment(refined, segment_input)
    repair_called = False
    repair_parsed = False
    repair_usage: dict[str, Any] = {}
    if not validation["valid"]:
        repair_called = True
        repair_prompt = render_template(
            repair_template,
            {
                "input_json": json.dumps(segment_input, ensure_ascii=False, indent=2),
                "previous_output_json": json.dumps(refined, ensure_ascii=False, indent=2),
                "validation_errors_json": json.dumps(validation["errors"], ensure_ascii=False, indent=2),
            },
        )
        repair_result = call_model(config, node, system_prompt, repair_prompt, api_key)
        repair_parsed = repair_result["parsed"] is not None
        repair_usage = repair_result["raw_response"].get("usage", {})
        write_text(segment_dir / "repair_user_prompt.md", repair_prompt)
        write_json(segment_dir / "repair_raw_response.json", repair_result["raw_response"])
        write_text(segment_dir / "repair_raw_content.txt", repair_result["raw_content"])
        if repair_result["parsed"] is not None:
            refined = repair_result["parsed"]
            if isinstance(refined, dict):
                refined["segment_id"] = segment_id
                refined["label"] = segment_input.get("label") or ""
                refined["level"] = segment_input.get("level") or 0
                refined["parent_id"] = segment_input.get("parent_id") or ""
                refined["role"] = segment_input.get("role") or "subquestion"
            validation = validate_segment(refined, segment_input)
    write_json(segment_dir / "refined_segment.json", refined)
    write_json(segment_dir / "validation_report.json", validation)
    return {
        "segment_id": segment_id,
        "parsed": result["parsed"] is not None,
        "valid": validation["valid"],
        "errors": validation["errors"],
        "usage": result["raw_response"].get("usage", {}),
        "repair_called": repair_called,
        "repair_parsed": repair_parsed,
        "repair_usage": repair_usage,
        "latency_seconds": result["latency_seconds"],
        "artifact_path": rel(segment_dir / "refined_segment.json"),
    }


def render_tree(segments: list[dict[str, Any]]) -> str:
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        by_parent.setdefault(str(segment.get("parent_id") or ""), []).append(segment)
    for items in by_parent.values():
        items.sort(key=lambda item: (int(item.get("level") or 0), str(item.get("segment_id") or "")))
    def walk(parent_id: str, depth: int = 0) -> list[str]:
        lines: list[str] = []
        for segment in by_parent.get(parent_id, []):
            if segment.get("role") == "stem":
                text = str(segment.get("prompt_md") or "").strip()
                if text:
                    lines.append(text)
            else:
                prefix = "  " * max(depth, 0)
                label = str(segment.get("label") or "").strip()
                prompt = str(segment.get("prompt_md") or "").strip()
                lines.append(f"{prefix}{label} {prompt}".strip())
            child_lines = walk(str(segment.get("segment_id") or ""), depth + 1)
            lines.extend(child_lines)
        return lines
    return "\n\n".join(line for line in walk("") if line.strip())


def segment_has_children(segment: dict[str, Any], plan: dict[str, Any]) -> bool:
    segment_id = str(segment.get("segment_id") or "")
    for planned in plan.get("segments") or []:
        if str(planned.get("segment_id") or "") == segment_id:
            return bool(planned.get("children"))
    return False


def assemble_packet(draft: dict[str, Any], plan: dict[str, Any], refined_segments: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    segment_by_id = {segment["segment_id"]: segment for segment in refined_segments}
    stem_segment = next((segment for segment in refined_segments if segment.get("role") == "stem"), None)
    subquestions = [segment for segment in refined_segments if segment.get("role") != "stem"]
    leaf_or_terminal_subquestions = [segment for segment in subquestions if not segment_has_children(segment, plan)]
    prompt_md = render_tree(refined_segments)
    answer_md = "\n\n".join(
        f"{segment.get('label','')} {segment.get('answer_md','')}".strip()
        for segment in leaf_or_terminal_subquestions
        if str(segment.get("answer_md") or "").strip()
    )
    explanation_md = "\n\n".join(
        f"{segment.get('label','')} {segment.get('explanation_md','')}".strip()
        for segment in leaf_or_terminal_subquestions
        if str(segment.get("explanation_md") or "").strip()
    )
    assets = []
    for asset in draft.get("asset_refs") or []:
        asset_id = asset.get("asset_id") if isinstance(asset, dict) else str(asset)
        if asset_id and any(asset_id in (segment.get("asset_ids") or []) for segment in refined_segments):
            assets.append(asset)
    render_markdown = "\n\n".join(part for part in [prompt_md, "【答案】\n" + answer_md if answer_md else "", "【解析】\n" + explanation_md if explanation_md else ""] if part.strip())
    return {
        "schema": PACKET_SCHEMA,
        "doc_id": draft.get("doc_id"),
        "source_draft_id": draft.get("draft_id"),
        "source_group_id": draft.get("source_group_id"),
        "route": "long_composite",
        "planner_prompt_version": config["nodes"]["node4a_structure_planner"]["prompt_version"],
        "segment_prompt_version": config["nodes"]["node4b_segment_refiner"]["prompt_version"],
        "status": "READY" if all(segment.get("_validation_valid", True) for segment in refined_segments) else "NEEDS_REVIEW",
        "standard_question": {
            "question_type": "composite",
            "stem_md": str((stem_segment or {}).get("prompt_md") or ""),
            "nested_subquestions": subquestions,
            "answer_md": answer_md,
            "explanation_md": explanation_md,
            "render_markdown": render_markdown,
        },
        "asset_refs": {"visual_refs": assets},
        "plan": plan,
        "segment_ids": list(segment_by_id),
    }


def render_review(packet: dict[str, Any], summary: dict[str, Any]) -> str:
    q = packet["standard_question"]
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Long Composite Refiner Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f5f7fb;color:#111827;line-height:1.55}}
.card{{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:16px;margin:16px 0}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;overflow:auto}}
code{{background:#eef2f7;padding:2px 5px;border-radius:4px}}
</style>
<h1>Long Composite Refiner Review</h1>
<p>run=<code>{html.escape(summary['run_id'])}</code> status=<code>{html.escape(packet['status'])}</code> segments=<code>{len(packet['segment_ids'])}</code></p>
<div class="card"><h2>Stem</h2><pre>{html.escape(q.get('stem_md',''))}</pre></div>
<div class="card"><h2>Nested Subquestions</h2><pre>{html.escape(json.dumps(q.get('nested_subquestions') or [], ensure_ascii=False, indent=2))}</pre></div>
<div class="card"><h2>Answer</h2><pre>{html.escape(q.get('answer_md',''))}</pre></div>
<div class="card"><h2>Explanation</h2><pre>{html.escape(q.get('explanation_md',''))}</pre></div>
<div class="card"><h2>Render Markdown</h2><pre>{html.escape(q.get('render_markdown',''))}</pre></div>
<div class="card"><h2>Plan</h2><pre>{html.escape(json.dumps(packet.get('plan') or {}, ensure_ascii=False, indent=2))}</pre></div>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    planner_node = config["nodes"]["node4a_structure_planner"]
    segment_node = config["nodes"]["node4b_segment_refiner"]
    input_root = workspace_path(args.input_draft_root)
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    drafts = load_drafts(input_root, args.doc_id_contains or [], set(args.group_ids or []))
    if len(drafts) != 1:
        raise SystemExit(f"expected exactly one draft for experiment, got {len(drafts)}")
    draft = drafts[0]
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not api_key and not args.prepare_only:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')} or --api-key")

    planner_input = build_planner_input(draft)
    planner_system = workspace_path(planner_node["system_prompt_path"]).read_text(encoding="utf-8")
    planner_template = workspace_path(planner_node["user_prompt_path"]).read_text(encoding="utf-8")
    planner_prompt = render_template(
        planner_template,
        {
            "input_json": json.dumps(planner_input, ensure_ascii=False, indent=2),
            "doc_id": draft.get("doc_id", ""),
            "source_draft_id": draft.get("draft_id", ""),
            "source_group_id": draft.get("source_group_id", ""),
            "prompt_version": planner_node["prompt_version"],
        },
    )
    write_json(out_root / "node4a_planner" / "planner_input.json", planner_input)
    write_text(out_root / "node4a_planner" / "used_system_prompt.md", planner_system)
    write_text(out_root / "node4a_planner" / "used_user_prompt.md", planner_prompt)
    if args.prepare_only:
        summary = {
            "schema": "docx_math_long_composite_refiner.prepare_summary",
            "run_id": args.run_id,
            "out_dir": rel(out_root),
            "planner_prompt_chars": len(planner_prompt),
            "route_signals": planner_input["route_signals"],
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        }
        write_json(out_root / "prepare_summary.json", summary)
        return summary

    planner_result = call_model(config, planner_node, planner_system, planner_prompt, api_key)
    write_json(out_root / "node4a_planner" / "raw_response.json", planner_result["raw_response"])
    write_text(out_root / "node4a_planner" / "raw_content.txt", planner_result["raw_content"])
    if planner_result["parsed"] is None:
        raise SystemExit(f"planner parse failed: {planner_result['parse_error']}")
    plan = planner_result["parsed"]
    plan_validation = validate_plan(plan, planner_input)
    write_json(out_root / "node4a_planner" / "plan.json", plan)
    write_json(out_root / "node4a_planner" / "validation_report.json", plan_validation)
    if not plan_validation["valid"]:
        raise SystemExit(f"planner validation failed: {plan_validation['errors'][:3]}")

    segment_system = workspace_path(segment_node["system_prompt_path"]).read_text(encoding="utf-8")
    segment_template = workspace_path(segment_node["user_prompt_path"]).read_text(encoding="utf-8")
    segment_repair_template = workspace_path(segment_node["repair_user_prompt_path"]).read_text(encoding="utf-8")
    segment_inputs = [materialize_segment_input(segment, planner_input) for segment in plan["segments"]]
    segment_out = out_root / "node4b_segments"
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.max_workers or 1))) as executor:
        future_map = {
            executor.submit(
                refine_segment,
                config=config,
                node=segment_node,
                system_prompt=segment_system,
                user_template=segment_template,
                repair_template=segment_repair_template,
                segment_input=segment_input,
                api_key=api_key,
                out_dir=segment_out,
            ): segment_input
            for segment_input in segment_inputs
        }
        for future in concurrent.futures.as_completed(future_map):
            records.append(future.result())
    records.sort(key=lambda item: item["segment_id"])
    refined_segments: list[dict[str, Any]] = []
    for record in records:
        segment = read_json(workspace_path(record["artifact_path"]))
        segment["_validation_valid"] = bool(record["valid"])
        refined_segments.append(segment)
    packet = assemble_packet(draft, plan, refined_segments, config)
    summary = {
        "schema": "docx_math_long_composite_refiner.run_summary",
        "run_id": args.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": rel(out_root),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "planner_parsed": True,
        "planner_valid": plan_validation["valid"],
        "segment_count": len(records),
        "segment_valid_count": sum(1 for item in records if item["valid"]),
        "segment_parse_failed_count": sum(1 for item in records if not item["parsed"]),
        "segment_repair_called_count": sum(1 for item in records if item.get("repair_called")),
        "segment_repair_parsed_count": sum(1 for item in records if item.get("repair_parsed")),
        "packet_status": packet["status"],
        "total_tokens": int((planner_result["raw_response"].get("usage") or {}).get("total_tokens") or 0)
        + sum(
            int((record.get("usage") or {}).get("total_tokens") or 0)
            + int((record.get("repair_usage") or {}).get("total_tokens") or 0)
            for record in records
        ),
        "planner_tokens": planner_result["raw_response"].get("usage", {}),
        "segment_records": records,
        "packet_json": rel(out_root / "long_composite_refined_packet.json"),
        "review_html": rel(out_root / "review.html"),
    }
    write_json(out_root / "long_composite_refined_packet.json", packet)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(packet, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/docx_math_long_composite_refiner_v01.yaml")
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id-contains", nargs="*", default=[])
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
