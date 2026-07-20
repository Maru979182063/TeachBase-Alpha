from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from english_text_first_normalizer.common import extract_json, read_json, rel_workspace, render_template, workspace_path, write_json, write_text


PROMPT_VERSION = "english_question_render_normalizer_v0.1_one_packet_surface_restore_20260720"


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


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value))


def page_image_paths(packet: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in (packet.get("asset_refs") or {}).get("page_image_refs") or []:
        path = workspace_path(item.get("path") or "")
        if path.exists() and path not in paths:
            paths.append(path)
    return paths[:3]


def build_input_payload(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_packet_id": packet.get("source_packet_id"),
        "source_group_id": packet.get("source_group_id"),
        "packet_family": packet.get("packet_family"),
        "refine_status": packet.get("refine_status"),
        "standard_question": packet.get("standard_question") or {},
        "final_markdown": packet.get("final_markdown") or "",
        "source_refs": packet.get("source_refs") or {},
        "asset_refs": packet.get("asset_refs") or {},
        "warnings": packet.get("warnings") or [],
        "status_breakdown": packet.get("status_breakdown") or {},
    }


def is_renderable_question(packet: dict[str, Any]) -> bool:
    if packet.get("refine_status") == "PRESERVED_NON_DIRECT":
        return False
    question = packet.get("standard_question") or {}
    return bool(str(question.get("stem") or "").strip() and str(question.get("answer") or "").strip())


def call_model(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path],
    api_key: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}})
    body = {
        "model": node["model"],
        "temperature": node.get("temperature", 0),
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
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
    raw_content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(raw_content)
    return {
        "request_body": body,
        "raw_response": raw,
        "raw_content": raw_content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def repair_shape(payload: dict[str, Any] | None, packet: dict[str, Any]) -> dict[str, Any]:
    q = packet.get("standard_question") or {}
    if not isinstance(payload, dict):
        payload = {}
    display = payload.get("display_question")
    if not isinstance(display, dict):
        display = {}
    display.setdefault("title", q.get("title") or packet.get("source_packet_id") or "")
    display.setdefault("stem_markdown", q.get("stem") or "")
    display.setdefault("answer_markdown", q.get("answer") or "")
    display.setdefault("analysis_markdown", q.get("analysis") or "")
    display.setdefault("translation_markdown", q.get("translation") or "")
    display.setdefault("items", [])
    display.setdefault("rendering_blocks", [])
    payload.update(
        {
            "schema": "rendered_question_record_v0.1",
            "doc_id": packet.get("doc_id"),
            "source_packet_id": packet.get("source_packet_id"),
            "source_group_id": packet.get("source_group_id"),
            "prompt_version": PROMPT_VERSION,
            "render_status": payload.get("render_status") if payload.get("render_status") in {"READY", "NEEDS_REVIEW", "SOURCE_IMAGE_REQUIRED", "BLOCKED"} else "NEEDS_REVIEW",
            "display_question": display,
            "source_refs_used": payload.get("source_refs_used") if isinstance(payload.get("source_refs_used"), list) else [],
            "unresolved_issues": payload.get("unresolved_issues") if isinstance(payload.get("unresolved_issues"), list) else [],
            "normalization_actions": payload.get("normalization_actions") if isinstance(payload.get("normalization_actions"), list) else [],
        }
    )
    return payload


def validate_record(record: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for key in [
        "schema",
        "doc_id",
        "source_packet_id",
        "source_group_id",
        "prompt_version",
        "render_status",
        "display_question",
        "source_refs_used",
        "unresolved_issues",
        "normalization_actions",
    ]:
        if key not in record:
            errors.append({"path": f"$.{key}", "message": "missing required key"})
    if record.get("schema") != "rendered_question_record_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if record.get("doc_id") != packet.get("doc_id"):
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if record.get("source_packet_id") != packet.get("source_packet_id"):
        errors.append({"path": "$.source_packet_id", "message": "source_packet_id mismatch"})
    display = record.get("display_question") or {}
    for key in ["title", "stem_markdown", "answer_markdown", "analysis_markdown", "translation_markdown", "items", "rendering_blocks"]:
        if key not in display:
            errors.append({"path": f"$.display_question.{key}", "message": "missing display field"})
    if not str(display.get("stem_markdown") or "").strip():
        errors.append({"path": "$.display_question.stem_markdown", "message": "empty stem_markdown"})
    stem_markdown = str(display.get("stem_markdown") or "")
    for index, item in enumerate(display.get("items") or []):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if len(prompt) >= 12 and prompt not in stem_markdown:
            warnings.append(
                {
                    "path": f"$.display_question.items[{index}].prompt",
                    "message": "item prompt is not literally included in stem_markdown; verify display stem is self-contained",
                }
            )
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def render_review(records: list[dict[str, Any]]) -> str:
    cards = []
    for item in records:
        record = item["rendered_record"]
        display = record["display_question"]
        page_figs = []
        for path in item.get("page_images") or []:
            abs_path = workspace_path(path)
            url = abs_path.resolve().as_uri()
            page_figs.append(f"<figure><a href='{html.escape(url)}' target='_blank'><img src='{html.escape(url)}'></a><figcaption>{html.escape(path)}</figcaption></figure>")
        cards.append(
            f"""
<section class="card">
  <h2>{html.escape(record['source_group_id'])} / {html.escape(record['source_packet_id'])} - {html.escape(record['render_status'])}</h2>
  <div class="grid">
    <div><h3>原页</h3><div class="pages">{''.join(page_figs)}</div></div>
    <div>
      <h3>格式还原题面</h3><pre>{html.escape(display.get('stem_markdown') or '')}</pre>
      <h3>格式还原答案</h3><pre>{html.escape(display.get('answer_markdown') or '')}</pre>
      <h3>Items</h3><pre>{html.escape(json.dumps(display.get('items') or [], ensure_ascii=False, indent=2))}</pre>
      <h3>原 standard_question.stem</h3><pre>{html.escape(item.get('source_stem') or '')}</pre>
      <h3>原 final_markdown</h3><pre>{html.escape(item.get('source_final_markdown') or '')}</pre>
      <h3>Validation</h3><pre>{html.escape(json.dumps(item.get('validation'), ensure_ascii=False, indent=2))}</pre>
      <h3>Issues / Actions</h3><pre>{html.escape(json.dumps({'unresolved_issues': record.get('unresolved_issues'), 'normalization_actions': record.get('normalization_actions')}, ensure_ascii=False, indent=2))}</pre>
    </div>
  </div>
</section>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Question Render Normalizer Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:20px;line-height:1.45}}
.card{{border:1px solid #ddd;margin:18px 0;padding:14px}}
.grid{{display:grid;grid-template-columns:minmax(360px,42vw) 1fr;gap:16px;align-items:start}}
.pages{{display:flex;gap:12px;flex-wrap:wrap}}
figure{{margin:0;max-width:320px}}
img{{width:310px;border:1px solid #ccc;background:white}}
figcaption{{font-size:12px;word-break:break-all;color:#555}}
pre{{white-space:pre-wrap;background:#f7f7f7;padding:10px}}
</style>
<h1>Question Render Normalizer Review</h1>
<p>Node6b smoke output. This node restores display formatting only; it does not import Runtime payloads or write DB.</p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node6b_question_render_normalizer"]
    api_key = str(os.environ.get(config.get("api_key_env", "ARK_API_KEY")) or "").strip()
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")

    refined_payload = read_json(workspace_path(args.refined_packets_json))
    packets = refined_payload.get("refined_packets") or []
    selected = set(args.group_ids or [])
    if selected:
        packets = [packet for packet in packets if packet.get("source_group_id") in selected or packet.get("source_packet_id") in selected]
    if args.renderable_only:
        packets = [packet for packet in packets if is_renderable_question(packet)]
    if args.max_packets:
        packets = packets[: args.max_packets]

    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    def process_packet(packet: dict[str, Any]) -> dict[str, Any]:
        packet_dir = out_root / "records" / safe_id(packet.get("source_packet_id") or packet.get("source_group_id"))
        images = page_image_paths(packet)
        input_payload = build_input_payload(packet)
        user_prompt = render_template(
            user_template,
            {
                "prompt_version": PROMPT_VERSION,
                "doc_id": packet.get("doc_id"),
                "source_packet_id": packet.get("source_packet_id"),
                "source_group_id": packet.get("source_group_id"),
                "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            },
        )
        attempts: list[dict[str, Any]] = []
        model_result = call_model(config=config, node=node, system_prompt=system_prompt, user_prompt=user_prompt, image_paths=images, api_key=api_key)
        attempts.append(model_result)
        record = repair_shape(model_result["parsed"], packet)
        validation = validate_record(record, packet)
        if not validation["valid"]:
            retry_prompt = (
                user_prompt
                + "\n\nRETRY_CONSTRAINT:\n"
                + "Your previous response failed local validation. "
                + "The display_question.stem_markdown must be self-contained and include every item prompt/list/table needed for a student to answer. "
                + "Return one complete JSON object only. "
                + f"Validation errors: {json.dumps(validation['errors'], ensure_ascii=False)[:1200]}"
            )
            retry_result = call_model(config=config, node=node, system_prompt=system_prompt, user_prompt=retry_prompt, image_paths=images, api_key=api_key)
            attempts.append(retry_result)
            retry_record = repair_shape(retry_result["parsed"], packet)
            retry_validation = validate_record(retry_record, packet)
            if retry_validation["valid"]:
                user_prompt = retry_prompt
                model_result = retry_result
                record = retry_record
                validation = retry_validation
        write_text(packet_dir / "used_system_prompt.md", system_prompt)
        write_text(packet_dir / "used_user_prompt.md", user_prompt)
        write_json(packet_dir / "request_messages.full.local.json", model_result["request_body"])
        write_json(packet_dir / "raw_response.json", model_result["raw_response"])
        write_text(packet_dir / "raw_content.txt", model_result["raw_content"])
        write_json(
            packet_dir / "model_attempts_summary.json",
            [
                {
                    "attempt": index + 1,
                    "parsed": attempt["parsed"] is not None,
                    "parse_error": attempt.get("parse_error"),
                    "latency_seconds": attempt.get("latency_seconds"),
                    "usage": attempt.get("raw_response", {}).get("usage", {}),
                }
                for index, attempt in enumerate(attempts)
            ],
        )
        write_json(packet_dir / "rendered_question_record.json", record)
        write_json(packet_dir / "validation_report.json", validation)
        return {
            "source_packet_id": packet.get("source_packet_id"),
            "source_group_id": packet.get("source_group_id"),
            "render_status": record.get("render_status"),
            "parsed": model_result["parsed"] is not None,
            "parse_error": model_result.get("parse_error"),
            "validation": validation,
            "latency_seconds": model_result["latency_seconds"],
            "usage": model_result["raw_response"].get("usage", {}),
            "attempt_count": len(attempts),
            "artifact_path": rel_workspace(packet_dir / "rendered_question_record.json"),
            "page_images": [rel_workspace(path) for path in images],
            "page_image_sha256": {rel_workspace(path): sha256_file(path) for path in images},
            "source_stem": (packet.get("standard_question") or {}).get("stem") or "",
            "source_final_markdown": packet.get("final_markdown") or "",
            "rendered_record": record,
        }
    records: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_packet = {executor.submit(process_packet, packet): packet for packet in packets}
        for future in concurrent.futures.as_completed(future_by_packet):
            records.append(future.result())
    records.sort(key=lambda item: (str(item.get("source_group_id") or ""), str(item.get("source_packet_id") or "")))
    payload = {
        "schema": "rendered_question_records_batch_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": PROMPT_VERSION,
        "doc_id": refined_payload.get("doc_id"),
        "records": records,
        "summary": {
            "record_count": len(records),
            "valid_count": sum(1 for record in records if record["validation"]["valid"]),
            "render_status_counts": {
                status: sum(1 for record in records if record["render_status"] == status)
                for status in sorted({record["render_status"] for record in records})
            },
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        },
    }
    summary = {
        "schema": "english_question_render_normalizer.run_summary",
        "generated_at": payload["generated_at"],
        "doc_id": payload["doc_id"],
        "prompt_version": PROMPT_VERSION,
        "out_dir": rel_workspace(out_root),
        **payload["summary"],
        "rendered_records_json": rel_workspace(out_root / "rendered_question_records.json"),
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "rendered_question_records.json", payload)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(records))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--refined-packets-json", required=True)
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--renderable-only", action="store_true")
    parser.add_argument("--max-packets", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
