from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


VISUAL_FORMS = {
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
    "image",
    "mixed",
    "unknown",
}
CONTENT_ROLES = {
    "navigation",
    "knowledge_explanation",
    "reading_passage",
    "activity_instruction",
    "student_task",
    "solution_reference",
    "analysis_explanation",
    "translation",
    "example",
    "visual_structure",
    "response_surface",
    "teacher_note",
    "unknown",
}
RELATION_HINTS = {
    "none",
    "introduces_following",
    "depends_on_previous",
    "answer_for_previous",
    "analysis_for_previous",
    "surface_for_previous",
    "context_for_following",
    "unknown",
}
COMPOSITION_RELEVANCE = {
    "main_candidate",
    "context_candidate",
    "evidence_only",
    "unknown",
}
PRESERVATION_REASONS = {
    "none",
    "table_layout_needed",
    "diagram_layout_needed",
    "writing_surface_needed",
    "checklist_or_form_needed",
    "image_content_needed",
    "spatial_relation_needed",
    "unknown",
}


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
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
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


def validate_tags(payload: dict[str, Any], *, doc_id: str, page_number: int, prompt_version: str, input_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if payload.get("schema") != "block_attribute_tags_v0.3":
        errors.append({"path": "$.schema", "message": "schema must be block_attribute_tags_v0.3"})
    if payload.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": f"doc_id mismatch: {payload.get('doc_id')} != {doc_id}"})
    if payload.get("page") != page_number:
        errors.append({"path": "$.page", "message": f"page mismatch: {payload.get('page')} != {page_number}"})
    if payload.get("prompt_version") != prompt_version:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        errors.append({"path": "$.tags", "message": "tags must be array"})
        tags = []
    input_ids = [str(block.get("block_id", "")) for block in input_blocks]
    tag_ids = [str(tag.get("block_id", "")) for tag in tags if isinstance(tag, dict)]
    if len(tags) != len(input_blocks):
        errors.append({"path": "$.tags", "message": f"tag count {len(tags)} != input block count {len(input_blocks)}"})
    if sorted(tag_ids) != sorted(input_ids):
        errors.append({"path": "$.tags", "message": f"tag block ids do not match input block ids: tags={tag_ids}, input={input_ids}"})
    if len(set(tag_ids)) != len(tag_ids):
        errors.append({"path": "$.tags", "message": "duplicate block_id in tags"})
    for index, tag in enumerate(tags):
        if not isinstance(tag, dict):
            errors.append({"path": f"$.tags[{index}]", "message": "tag must be object"})
            continue
        if "text" in tag:
            errors.append({"path": f"$.tags[{index}].text", "message": "Node1b must not output text"})
        if tag.get("visual_form") not in VISUAL_FORMS:
            errors.append({"path": f"$.tags[{index}].visual_form", "message": f"invalid visual_form {tag.get('visual_form')}"})
        if tag.get("content_role") not in CONTENT_ROLES:
            errors.append({"path": f"$.tags[{index}].content_role", "message": f"invalid content_role {tag.get('content_role')}"})
        if tag.get("relation_hint") not in RELATION_HINTS:
            errors.append({"path": f"$.tags[{index}].relation_hint", "message": f"invalid relation_hint {tag.get('relation_hint')}"})
        if tag.get("composition_relevance") not in COMPOSITION_RELEVANCE:
            errors.append({"path": f"$.tags[{index}].composition_relevance", "message": f"invalid composition_relevance {tag.get('composition_relevance')}"})
        if tag.get("relevance_confidence") not in {"low", "medium", "high"}:
            errors.append({"path": f"$.tags[{index}].relevance_confidence", "message": f"invalid relevance_confidence {tag.get('relevance_confidence')}"})
        if not isinstance(tag.get("requires_visual_preservation"), bool):
            errors.append({"path": f"$.tags[{index}].requires_visual_preservation", "message": "requires_visual_preservation must be boolean"})
        if tag.get("preservation_reason") not in PRESERVATION_REASONS:
            errors.append({"path": f"$.tags[{index}].preservation_reason", "message": f"invalid preservation_reason {tag.get('preservation_reason')}"})
        if tag.get("confidence") not in {"low", "medium", "high"}:
            errors.append({"path": f"$.tags[{index}].confidence", "message": f"invalid confidence {tag.get('confidence')}"})
        if "evidence_note" in tag:
            errors.append({"path": f"$.tags[{index}].evidence_note", "message": "evidence_note is not allowed in v0.2"})
        if tag.get("requires_visual_preservation") is False and tag.get("preservation_reason") != "none":
            warnings.append({"path": f"$.tags[{index}].preservation_reason", "message": "preservation_reason should be none when visual preservation is false"})
        block_id = str(tag.get("block_id", ""))
        source_block = next((block for block in input_blocks if str(block.get("block_id", "")) == block_id), None)
        if tag.get("content_role") == "navigation" and source_block and source_block.get("label") != "header_footer":
            warnings.append({
                "path": f"$.tags[{index}].content_role",
                "message": "navigation should be reserved for header_footer/page chrome; review this non-header block",
                "block_id": block_id,
                "source_label": source_block.get("label"),
            })
    return {"valid": not errors, "errors": errors, "warnings": warnings, "tag_count": len(tags)}


def page_image_path(config: dict[str, Any], doc_id: str, page_number: int) -> Path:
    return workspace_path(config["documents"][doc_id]["page_images_dir"]) / f"page_{page_number:03d}.png"


def selected_pages(args: argparse.Namespace) -> list[tuple[str, int]]:
    pairs = []
    for value in args.pages:
        if ":" not in value:
            raise SystemExit(f"page selector must be doc_id:page_number, got {value}")
        doc_id, page_raw = value.split(":", 1)
        pairs.append((doc_id, int(page_raw)))
    return pairs


def node1a_output_path(input_run: Path, doc_id: str, page_number: int) -> Path:
    return input_run / doc_id / f"page_{page_number:03d}" / "vlm_page_transcription.json"


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


def render_review(out_dir: Path, records: list[dict[str, Any]]) -> None:
    role_cn = {
        "navigation": "导航/页眉页脚",
        "knowledge_explanation": "知识讲解",
        "reading_passage": "阅读文章",
        "activity_instruction": "活动指令",
        "student_task": "学生任务/练习",
        "solution_reference": "答案/参考解答",
        "analysis_explanation": "解析说明",
        "translation": "翻译",
        "example": "例子",
        "visual_structure": "视觉结构",
        "response_surface": "作答区域",
        "teacher_note": "教师备注",
        "unknown": "未知",
    }
    form_cn = {
        "plain_text": "普通文本",
        "heading": "标题",
        "list": "列表",
        "table": "表格",
        "diagram": "图示",
        "question_stem": "题干",
        "options": "选项",
        "answer_key": "答案",
        "worked_example": "例题/例句",
        "writing_surface": "写作/作答版面",
        "image": "图片",
        "mixed": "混合形态",
        "unknown": "未知",
    }
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Controlled Node1b Block Attribute Review</title>",
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;line-height:1.45}.page{border:1px solid #ddd;margin:18px 0;padding:12px}.grid{display:grid;grid-template-columns:minmax(360px,42vw) 1fr;gap:16px;align-items:start}.mono{font-family:Consolas,monospace;white-space:pre-wrap}.ok{background:#eef9f0}.bad{background:#fff0f0}.tag{border-bottom:1px solid #eee;padding:8px 0}.label{font-family:Consolas,monospace;background:#eef;padding:2px 5px;border-radius:4px}img{width:100%;max-height:900px;object-fit:contain;border:1px solid #ddd}</style>",
        "<h1>Controlled Node1b BlockAttributeTagger Review</h1>",
        "<p>中文说明：Node1b 只给 Node1a 已有 block（文字块）打属性，不允许改 text（文字）、block_id（块编号）、增删块。</p>",
    ]
    for record in records:
        css = "ok" if record["validation"]["valid"] else "bad"
        tag_by_id = {tag["block_id"]: tag for tag in (record.get("parsed_output") or {}).get("tags", []) if isinstance(tag, dict)}
        parts.append(f"<div class='page {css}'>")
        parts.append(f"<h2>{html.escape(record['doc_id'])} page {record['page_number']} valid={record['validation']['valid']}</h2>")
        parts.append("<div class='grid'><div>")
        parts.append(f"<img src='{Path(record['image_abs_path']).resolve().as_uri()}'>")
        parts.append("</div><div>")
        parts.append(f"<pre class='mono'>{html.escape(json.dumps({'validation（校验）': record['validation'], 'page_visual_flags（页面级视觉风险标签）': record.get('page_visual_flags'), 'artifact_paths（产物路径）': record['artifact_paths']}, ensure_ascii=False, indent=2))}</pre>")
        for block in record["input_blocks"]:
            tag = tag_by_id.get(str(block.get("block_id")), {})
            parts.append("<div class='tag'>")
            parts.append(f"<div><span class='label'>{html.escape(str(block.get('block_id')))}</span> <span class='label'>{html.escape(str(block.get('label')))}</span></div>")
            parts.append(f"<pre class='mono'>原文（Node1a 转录文本，不允许 Node1b 修改）\n{html.escape(str(block.get('text', '')))}</pre>")
            shown = {
                "visual_form（视觉形式）": f"{tag.get('visual_form')} / {form_cn.get(str(tag.get('visual_form')), '')}",
                "content_role（内容角色）": f"{tag.get('content_role')} / {role_cn.get(str(tag.get('content_role')), '')}",
                "relation_hint（局部关系提示）": tag.get("relation_hint"),
                "composition_relevance（组题相关性）": tag.get("composition_relevance"),
                "relevance_confidence（相关性置信度）": tag.get("relevance_confidence"),
                "requires_visual_preservation（是否需要保留原始视觉形态）": tag.get("requires_visual_preservation"),
                "preservation_reason（保留原因）": tag.get("preservation_reason"),
                "confidence（置信度）": tag.get("confidence"),
            }
            parts.append(f"<pre class='mono'>{html.escape(json.dumps(shown, ensure_ascii=False, indent=2))}</pre>")
            parts.append("</div>")
        parts.append("</div></div></div>")
    write_text(out_dir / "review.html", "\n".join(parts))


def run(args: argparse.Namespace) -> dict[str, Any]:
    config_path = workspace_path(args.config)
    config = read_json(config_path)
    node = config["nodes"]["node1b_block_attribute_tagger"]
    input_run = workspace_path(args.input_run)
    out_root = workspace_path(args.out or config["owned_output_root"])
    run_id = args.run_id or f"node1b_attrs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = str(os.environ.get(config["api_key_env"], "") or "").strip()
    if not api_key:
        raise SystemExit(f"missing api key env {config['api_key_env']}")
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    write_text(out_dir / "used_system_prompt.md", system_prompt)
    write_text(out_dir / "used_user_prompt_template.md", user_template)
    write_json(out_dir / "used_config.json", config)
    records: list[dict[str, Any]] = []
    for doc_id, page_number in selected_pages(args):
        node1a_path = node1a_output_path(input_run, doc_id, page_number)
        node1a = read_json(node1a_path)
        input_blocks = list(node1a.get("blocks", []) or [])
        page_visual_flags = node1a.get("page_visual_flags", {})
        image_path = page_image_path(config, doc_id, page_number)
        page_dir = out_dir / doc_id / f"page_{page_number:03d}"
        blocks_payload = [
            {
                "block_id": block.get("block_id"),
                "label": block.get("label"),
                "text": block.get("text"),
                "bbox_hint": block.get("bbox_hint"),
                "is_complete": block.get("is_complete"),
            }
            for block in input_blocks
        ]
        user_prompt = render_template(
            user_template,
            {
                "doc_id": doc_id,
                "page_number": page_number,
                "prompt_version": node["prompt_version"],
                "page_visual_flags_json": json.dumps(page_visual_flags, ensure_ascii=False, indent=2),
                "blocks_json": json.dumps(blocks_payload, ensure_ascii=False, indent=2),
            },
        )
        write_text(page_dir / "system_prompt.md", system_prompt)
        write_text(page_dir / "user_prompt.md", user_prompt)
        model_result = call_model(config, node, system_prompt, user_prompt, api_key)
        request_body = model_result["request_body"]
        redacted_request = json.loads(json.dumps(request_body, ensure_ascii=False))
        write_json(page_dir / "request_messages.redacted.json", redacted_request)
        write_json(page_dir / "request_messages.full.local.json", request_body)
        write_json(page_dir / "raw_response.json", model_result["raw_response"])
        write_text(page_dir / "raw_content.txt", model_result["raw_content"])
        parsed = model_result["parsed"] or {}
        validation = (
            validate_tags(parsed, doc_id=doc_id, page_number=page_number, prompt_version=node["prompt_version"], input_blocks=input_blocks)
            if parsed
            else {"valid": False, "errors": [{"message": model_result["parse_error"]}], "warnings": []}
        )
        write_json(page_dir / "block_attribute_tags.json", parsed)
        write_json(page_dir / "validation_report.json", validation)
        artifact_paths = {
            "node1a_source": rel_workspace(node1a_path),
            "system_prompt": rel_workspace(page_dir / "system_prompt.md"),
            "user_prompt": rel_workspace(page_dir / "user_prompt.md"),
            "request_messages_redacted": rel_workspace(page_dir / "request_messages.redacted.json"),
            "request_messages_full_local": rel_workspace(page_dir / "request_messages.full.local.json"),
            "raw_response": rel_workspace(page_dir / "raw_response.json"),
            "raw_content": rel_workspace(page_dir / "raw_content.txt"),
            "parsed_output": rel_workspace(page_dir / "block_attribute_tags.json"),
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
            "node1a_source": rel_workspace(node1a_path),
            "latency_seconds": model_result["latency_seconds"],
            "parsed": bool(model_result["parsed"]),
            "parse_error": model_result["parse_error"],
            "validation": validation,
            "parsed_output": parsed,
            "input_blocks": input_blocks,
            "page_visual_flags": page_visual_flags,
            "usage": model_result["raw_response"].get("usage", {}),
            "artifact_paths": artifact_paths,
        }
        write_json(page_dir / "record_manifest.json", record)
        records.append(record)
    summary = {
        "schema": "english_text_first_controlled_node1b_attribute_tagger.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": rel_workspace(config_path),
        "node": "node1b_block_attribute_tagger",
        "input_run": rel_workspace(input_run),
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
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="YAML-controlled Node1b block attribute tagger using fixed Node1a blocks.")
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--input-run", required=True)
    parser.add_argument("--pages", nargs="+", required=True, help="doc_id:page_number selectors")
    parser.add_argument("--out", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
