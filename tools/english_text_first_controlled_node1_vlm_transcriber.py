from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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


def validate_output(payload: dict[str, Any], *, doc_id: str, page_number: int, requires_block_attributes: bool = False) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required = ["schema", "doc_id", "page", "page_start", "page_end", "page_visual_flags", "blocks", "qa_flags"]
    for key in required:
        if key not in payload:
            errors.append({"path": "$", "message": f"missing {key}"})
    if payload.get("schema") != "vlm_page_transcription_v0.2":
        errors.append({"path": "$.schema", "message": "schema must be vlm_page_transcription_v0.2"})
    if payload.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": f"doc_id mismatch: {payload.get('doc_id')} != {doc_id}"})
    if payload.get("page") != page_number:
        errors.append({"path": "$.page", "message": f"page mismatch: {payload.get('page')} != {page_number}"})
    for obj_key in ("page_start", "page_end"):
        if not isinstance(payload.get(obj_key), dict):
            errors.append({"path": f"$.{obj_key}", "message": "must be object"})
    page_visual_flags = payload.get("page_visual_flags")
    if not isinstance(page_visual_flags, dict):
        errors.append({"path": "$.page_visual_flags", "message": "must be object"})
    else:
        for key in (
            "has_table",
            "has_diagram",
            "has_image",
            "has_writing_surface",
            "has_non_text_visual",
            "visual_review_required",
        ):
            if not isinstance(page_visual_flags.get(key), bool):
                errors.append({"path": f"$.page_visual_flags.{key}", "message": "must be boolean"})
        if page_visual_flags.get("confidence") not in {"low", "medium", "high"}:
            errors.append({"path": "$.page_visual_flags.confidence", "message": "confidence must be low|medium|high"})
    blocks = payload.get("blocks", [])
    if not isinstance(blocks, list):
        errors.append({"path": "$.blocks", "message": "must be array"})
        blocks = []
    labels = {
        "header_footer",
        "section_heading",
        "knowledge_text",
        "passage_text",
        "question_text",
        "option_text",
        "answer_text",
        "analysis_text",
        "translation_text",
        "example_text",
        "exercise_text",
        "table_text",
        "diagram_text",
        "image_caption",
        "unknown_text",
    }
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append({"path": f"$.blocks[{index}]", "message": "block must be object"})
            continue
        expected_id = f"b{index + 1}"
        if block.get("block_id") != expected_id:
            warnings.append({"path": f"$.blocks[{index}].block_id", "message": f"expected sequential {expected_id}, got {block.get('block_id')}"})
        if block.get("label") not in labels:
            errors.append({"path": f"$.blocks[{index}].label", "message": f"invalid label {block.get('label')}"})
        if not isinstance(block.get("text"), str):
            errors.append({"path": f"$.blocks[{index}].text", "message": "text must be string"})
        if not isinstance(block.get("bbox_hint"), str):
            warnings.append({"path": f"$.blocks[{index}].bbox_hint", "message": "bbox_hint should be string"})
        if not isinstance(block.get("is_complete"), bool):
            warnings.append({"path": f"$.blocks[{index}].is_complete", "message": "is_complete should be boolean"})
        if requires_block_attributes:
            attrs = block.get("content_attributes")
            if not isinstance(attrs, dict):
                errors.append({"path": f"$.blocks[{index}].content_attributes", "message": "content_attributes must be object"})
                continue
            visual_forms = {
                "plain_text",
                "heading",
                "list",
                "table",
                "diagram",
                "question_stem",
                "options",
                "answer_key",
                "worked_example",
                "writing_surface",
                "unknown",
            }
            learning_functions = {
                "navigation",
                "knowledge_explanation",
                "passage",
                "activity_instruction",
                "student_task",
                "solution_reference",
                "teacher_annotation",
                "visual_structure",
                "surface_for_response",
                "unknown",
            }
            if attrs.get("visual_form") not in visual_forms:
                errors.append({"path": f"$.blocks[{index}].content_attributes.visual_form", "message": f"invalid visual_form {attrs.get('visual_form')}"})
            if attrs.get("learning_function") not in learning_functions:
                errors.append({"path": f"$.blocks[{index}].content_attributes.learning_function", "message": f"invalid learning_function {attrs.get('learning_function')}"})
            if not isinstance(attrs.get("requires_visual_preservation"), bool):
                errors.append({"path": f"$.blocks[{index}].content_attributes.requires_visual_preservation", "message": "requires_visual_preservation must be boolean"})
            if attrs.get("attribute_confidence") not in {"low", "medium", "high"}:
                errors.append({"path": f"$.blocks[{index}].content_attributes.attribute_confidence", "message": f"invalid attribute_confidence {attrs.get('attribute_confidence')}"})
            if not isinstance(attrs.get("evidence_note"), str):
                warnings.append({"path": f"$.blocks[{index}].content_attributes.evidence_note", "message": "evidence_note should be string"})
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "block_count": len(blocks),
    }


def normalize_page_visual_flags(payload: dict[str, Any]) -> None:
    flags = payload.get("page_visual_flags")
    if not isinstance(flags, dict):
        return
    flags["visual_review_required"] = any(
        bool(flags.get(key))
        for key in (
            "has_table",
            "has_diagram",
            "has_image",
            "has_writing_surface",
            "has_non_text_visual",
        )
    )


def call_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, image_path: Path, api_key: str) -> dict[str, Any]:
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            },
        ],
    }
    started = time.time()
    response = requests.post(
        config["api_url"],
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=240,
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


def page_image_path(config: dict[str, Any], doc_id: str, page_number: int) -> Path:
    doc = config["documents"][doc_id]
    return workspace_path(doc["page_images_dir"]) / f"page_{page_number:03d}.png"


def selected_pages(args: argparse.Namespace) -> list[tuple[str, int]]:
    pairs: list[tuple[str, int]] = []
    for value in args.pages:
        if ":" not in value:
            raise SystemExit(f"page selector must be doc_id:page_number, got {value}")
        doc_id, page_raw = value.split(":", 1)
        pairs.append((doc_id, int(page_raw)))
    return pairs


def render_review(out_dir: Path, records: list[dict[str, Any]]) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Controlled Node1 VLMTranscriber Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;line-height:1.45}.page{border:1px solid #ddd;margin:18px 0;padding:12px}.grid{display:grid;grid-template-columns:minmax(360px,44vw) 1fr;gap:16px;align-items:start}.mono{font-family:Consolas,monospace;white-space:pre-wrap}.ok{background:#eef9f0}.bad{background:#fff0f0}.warn{background:#fff8e1}img{width:100%;max-height:900px;object-fit:contain;border:1px solid #ddd}.block{border-bottom:1px solid #eee;padding:8px 0}.label{font-family:Consolas,monospace;background:#eef;padding:2px 5px;border-radius:4px}</style>",
        "<h1>Controlled Node1 VLMTranscriber Review</h1>",
        "<p>This page is generated only from the YAML-controlled Node1 runner. Each record persists prompts, request messages, image hash, raw response, parsed JSON, and validation report.</p>",
    ]
    for record in records:
        css = "ok" if record["validation"]["valid"] else "bad"
        parsed = record.get("parsed_output") or {}
        parts.append(f"<div class='page {css}'>")
        parts.append(f"<h2>{html.escape(record['doc_id'])} page {record['page_number']} valid={record['validation']['valid']}</h2>")
        parts.append("<div class='grid'><div>")
        parts.append(f"<img src='{Path(record['image_abs_path']).resolve().as_uri()}'>")
        parts.append("</div><div>")
        meta = {k: record[k] for k in ("doc_id", "page_number", "model", "prompt_version", "image_sha256", "latency_seconds", "artifact_paths")}
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(meta, ensure_ascii=False, indent=2))}</pre>")
        parts.append("<h3>Validation</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(record['validation'], ensure_ascii=False, indent=2))}</pre>")
        parts.append("<h3>Page Boundary</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps({'page_start': parsed.get('page_start'), 'page_end': parsed.get('page_end')}, ensure_ascii=False, indent=2))}</pre>")
        parts.append("<h3>Page Visual Flags</h3>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps(parsed.get('page_visual_flags'), ensure_ascii=False, indent=2))}</pre>")
        parts.append("<h3>Blocks</h3>")
        for block in parsed.get("blocks", []) or []:
            parts.append("<div class='block'>")
            parts.append(f"<div><span class='label'>{html.escape(str(block.get('block_id')))}</span> <span class='label'>{html.escape(str(block.get('label')))}</span> complete={html.escape(str(block.get('is_complete')))} bbox_hint={html.escape(str(block.get('bbox_hint', '')))}</div>")
            if isinstance(block.get("content_attributes"), dict):
                parts.append(f"<pre class='mono'>{html.escape(json.dumps({'content_attributes（内容属性）': block.get('content_attributes')}, ensure_ascii=False, indent=2))}</pre>")
            parts.append(f"<pre class='mono'>{html.escape(str(block.get('text', '')))}</pre>")
            parts.append("</div>")
        parts.append("</div></div></div>")
    write_text(out_dir / "review.html", "\n".join(parts))


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = workspace_path(args.config)
    config = read_json(config_path)
    node = config["nodes"][args.node]
    out_root = workspace_path(args.out or config["owned_output_root"])
    run_id = args.run_id or f"node1_controlled_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = str(os.environ.get(config["api_key_env"], "") or "").strip()
    if not api_key:
        raise SystemExit(f"missing api key env {config['api_key_env']}")

    system_prompt_path = workspace_path(node["system_prompt_path"])
    user_prompt_path = workspace_path(node["user_prompt_path"])
    system_prompt = system_prompt_path.read_text(encoding="utf-8")
    user_template = user_prompt_path.read_text(encoding="utf-8")
    write_text(out_dir / "used_system_prompt.md", system_prompt)
    write_text(out_dir / "used_user_prompt_template.md", user_template)
    write_json(out_dir / "used_config.json", config)

    records: list[dict[str, Any]] = []
    for doc_id, page_number in selected_pages(args):
        image_path = page_image_path(config, doc_id, page_number)
        if not image_path.exists():
            raise SystemExit(f"missing image: {image_path}")
        page_dir = out_dir / doc_id / f"page_{page_number:03d}"
        prompt_values = {"doc_id": doc_id, "page_number": page_number, "prompt_version": node["prompt_version"]}
        user_prompt = render_template(user_template, prompt_values)
        write_text(page_dir / "system_prompt.md", system_prompt)
        write_text(page_dir / "user_prompt.md", user_prompt)
        model_result = call_model(config, node, system_prompt, user_prompt, image_path, api_key)
        request_body = model_result["request_body"]
        redacted_request = json.loads(json.dumps(request_body, ensure_ascii=False))
        for content_item in redacted_request["messages"][1]["content"]:
            if content_item.get("type") == "image_url":
                content_item["image_url"]["url"] = f"sha256:{sha256_file(image_path)}"
        write_json(page_dir / "request_messages.redacted.json", redacted_request)
        write_json(page_dir / "request_messages.full.local.json", request_body)
        write_json(page_dir / "raw_response.json", model_result["raw_response"])
        write_text(page_dir / "raw_content.txt", model_result["raw_content"])
        parsed = model_result["parsed"] or {}
        normalize_page_visual_flags(parsed)
        validation = (
            validate_output(
                parsed,
                doc_id=doc_id,
                page_number=page_number,
                requires_block_attributes=bool(node.get("requires_block_attributes")),
            )
            if parsed
            else {"valid": False, "errors": [{"message": model_result["parse_error"]}], "warnings": []}
        )
        write_json(page_dir / "vlm_page_transcription.json", parsed)
        write_json(page_dir / "validation_report.json", validation)
        artifact_paths = {
            "system_prompt": rel_workspace(page_dir / "system_prompt.md"),
            "user_prompt": rel_workspace(page_dir / "user_prompt.md"),
            "request_messages_redacted": rel_workspace(page_dir / "request_messages.redacted.json"),
            "request_messages_full_local": rel_workspace(page_dir / "request_messages.full.local.json"),
            "raw_response": rel_workspace(page_dir / "raw_response.json"),
            "raw_content": rel_workspace(page_dir / "raw_content.txt"),
            "parsed_output": rel_workspace(page_dir / "vlm_page_transcription.json"),
            "validation_report": rel_workspace(page_dir / "validation_report.json"),
        }
        record = {
            "doc_id": doc_id,
            "page_number": page_number,
            "model": node["model"],
            "prompt_version": node["prompt_version"],
            "image_path": rel_workspace(image_path),
            "image_abs_path": str(image_path.resolve()),
            "image_sha256": sha256_file(image_path),
            "latency_seconds": model_result["latency_seconds"],
            "parsed": bool(model_result["parsed"]),
            "parse_error": model_result["parse_error"],
            "validation": validation,
            "parsed_output": parsed,
            "usage": model_result["raw_response"].get("usage", {}),
            "artifact_paths": artifact_paths,
        }
        write_json(page_dir / "record_manifest.json", record)
        records.append(record)

    summary = {
        "schema": "english_text_first_controlled_node1_vlm_transcriber.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": rel_workspace(config_path),
        "node": args.node,
        "out_dir": rel_workspace(out_dir),
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "pages_attempted": len(records),
        "pages_parsed": sum(1 for record in records if record["parsed"]),
        "pages_valid": sum(1 for record in records if record["validation"]["valid"]),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        "review_html": rel_workspace(out_dir / "review.html"),
    }
    write_json(out_dir / "run_summary.json", summary)
    render_review(out_dir, records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="YAML-controlled Node1 VLM page transcriber with full request/response persistence.")
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--node", default="node1_vlm_transcriber")
    parser.add_argument("--pages", nargs="+", required=True, help="doc_id:page_number selectors")
    parser.add_argument("--out", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
