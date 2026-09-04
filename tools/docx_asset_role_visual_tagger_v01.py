from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_asset_role_visual_tagger_v01.yaml"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

ASSET_ROLES = {
    "question_stem_diagram",
    "explanation_diagram",
    "option_diagram",
    "formula_image",
    "table_image",
    "section_title_image",
    "decorative_header",
    "logo_watermark",
    "unknown",
}

TARGET_FIELDS = {
    "stem",
    "subquestions",
    "options",
    "answer",
    "explanation",
    "teaching_note",
    "context",
    "other_evidence",
    "none",
    "unknown",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

ROLE_ZH = {
    "question_stem_diagram": "题干图",
    "explanation_diagram": "解析图",
    "option_diagram": "选项图",
    "formula_image": "公式图",
    "table_image": "表格图",
    "section_title_image": "栏目图",
    "decorative_header": "装饰图",
    "logo_watermark": "水印/Logo",
    "unknown": "未确定",
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


def resolve_workspace_path(raw: str) -> Path:
    path = Path(str(raw or ""))
    return path if path.is_absolute() else ROOT / path


def load_blocks(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    paragraphs = payload.get("paragraphs") or payload.get("blocks") or []
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(paragraphs):
        item = dict(block)
        item["block_id"] = str(block.get("block_id") or f"b_{index:06d}")
        item["source_order"] = int(block.get("source_order") if block.get("source_order") is not None else index)
        item["image_refs"] = [ref for ref in (block.get("image_refs") or block.get("asset_refs") or []) if isinstance(ref, dict)]
        blocks.append(item)
    return blocks


def load_tags(path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    tags = payload.get("tags") or payload.get("block_tags") or []
    return {str(item.get("block_id")): dict(item) for item in tags if isinstance(item, dict) and item.get("block_id")}


def load_prompt(config: dict[str, Any]) -> str:
    path = Path(str(config.get("system_prompt_path") or ""))
    if not path.is_absolute():
        path = ROOT / path
    return read_text(path)


def compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "..."


def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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


def surrounding_context(
    *,
    blocks: list[dict[str, Any]],
    index: int,
    left: int,
    right: int,
    max_chars: int,
) -> dict[str, Any]:
    def row(block: dict[str, Any]) -> dict[str, Any]:
        return {
            "block_id": block.get("block_id"),
            "source_order": block.get("source_order"),
            "text": compact_text(str(block.get("text") or block.get("plain_text_lossy") or ""), max_chars),
            "display_markdown": compact_text(str(block.get("display_markdown") or block.get("markdown") or ""), max_chars),
            "formula_count": int(block.get("formula_count") or 0),
            "image_ref_count": len(block.get("image_refs") or []),
        }

    return {
        "left_context": [row(blocks[i]) for i in range(max(0, index - left), index)],
        "current_block": row(blocks[index]),
        "right_context": [row(blocks[i]) for i in range(index + 1, min(len(blocks), index + 1 + right))],
    }


def build_assets(blocks: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = config.get("context") or {}
    left = int(ctx.get("left_blocks") or 3)
    right = int(ctx.get("right_blocks") or 3)
    max_chars = int(ctx.get("max_text_chars") or 420)
    assets: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        for image_index, image in enumerate(block.get("image_refs") or []):
            asset_id = str(image.get("asset_id") or image.get("image_ref_id") or "")
            storage_key = str(image.get("storage_key") or "")
            if not asset_id:
                continue
            path = resolve_workspace_path(storage_key)
            assets.append(
                {
                    "asset_id": asset_id,
                    "occurrence_id": f"{block.get('block_id')}::{asset_id}::{image_index}",
                    "block_id": str(block.get("block_id")),
                    "source_order": block.get("source_order"),
                    "storage_key": storage_key,
                    "local_path": str(path),
                    "asset_meta": {
                        "format": image.get("format"),
                        "mime_type": image.get("mime_type"),
                        "width_px": image.get("width_px"),
                        "height_px": image.get("height_px"),
                        "bytes": image.get("bytes"),
                        "mode": image.get("mode"),
                        "placement": image.get("placement"),
                    },
                    "context": surrounding_context(blocks=blocks, index=index, left=left, right=right, max_chars=max_chars),
                }
            )
    return assets


def model_messages(system_prompt: str, asset: dict[str, Any], image_path: Path) -> list[dict[str, Any]]:
    user_payload = {
        "task": "classify this DOCX image asset ownership",
        "asset_id": asset["asset_id"],
        "block_id": asset["block_id"],
        "asset_meta": asset["asset_meta"],
        "context": asset["context"],
        "required_output": {
            "asset_id": asset["asset_id"],
            "block_id": asset["block_id"],
            "asset_role": "one allowed asset_role",
            "target_field": "one allowed target_field",
            "confidence": 0.0,
            "visual_description": "short factual description",
            "evidence": "short reason",
            "needs_resolution": False,
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False, indent=2)},
                {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
            ],
        },
    ]


def call_model(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    asset: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    image_path = Path(asset["local_path"])
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": model_messages(system_prompt, asset, image_path),
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
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_prediction(asset: dict[str, Any], parsed: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(parsed, dict):
        return fallback_prediction(asset, "model_parse_failed"), [{"code": "model_parse_failed", "asset_id": asset["asset_id"]}]
    role = str(parsed.get("asset_role") or "unknown")
    field = str(parsed.get("target_field") or "unknown")
    if role not in ASSET_ROLES:
        issues.append({"code": "invalid_asset_role", "asset_id": asset["asset_id"], "value": role})
        role = "unknown"
    if field not in TARGET_FIELDS:
        issues.append({"code": "invalid_target_field", "asset_id": asset["asset_id"], "value": field})
        field = "unknown"
    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if role == "unknown" or confidence < 0.55:
        needs_resolution = True
    else:
        needs_resolution = bool(parsed.get("needs_resolution", False))
    return (
        {
            "asset_id": asset["asset_id"],
            "block_id": asset["block_id"],
            "source_order": asset.get("source_order"),
            "storage_key": asset["storage_key"],
            "asset_meta": asset["asset_meta"],
            "asset_role": role,
            "target_field": field,
            "visual_label_zh": ROLE_ZH.get(role, "未确定"),
            "confidence": confidence,
            "visual_description": compact_text(str(parsed.get("visual_description") or ""), 240),
            "evidence": compact_text(str(parsed.get("evidence") or ""), 240),
            "needs_resolution": needs_resolution,
            "node": "docx_asset_role_visual_tagger_v01",
        },
        issues,
    )


def fallback_prediction(asset: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "block_id": asset["block_id"],
        "source_order": asset.get("source_order"),
        "storage_key": asset["storage_key"],
        "asset_meta": asset["asset_meta"],
        "asset_role": "unknown",
        "target_field": "unknown",
        "visual_label_zh": "未确定",
        "confidence": 0.0,
        "visual_description": "",
        "evidence": reason,
        "needs_resolution": True,
        "node": "docx_asset_role_visual_tagger_v01",
    }


def tag_one(
    *,
    asset: dict[str, Any],
    config: dict[str, Any],
    system_prompt: str,
    raw_dir: Path,
    api_key: str,
    timeout: int,
    attempts: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    image_path = Path(asset["local_path"])
    if not image_path.exists():
        return fallback_prediction(asset, "asset_file_missing"), [{"code": "asset_file_missing", "asset_id": asset["asset_id"]}]
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        return fallback_prediction(asset, "unsupported_visual_format"), [{"code": "unsupported_visual_format", "asset_id": asset["asset_id"], "format": image_path.suffix}]
    raw_dir.mkdir(parents=True, exist_ok=True)
    # 中文说明：同一图片可在多个段落复用；按出现位置留证，避免并发调用覆盖上下文和响应。
    trace_id = str(asset["occurrence_id"]).replace("::", "__")
    write_json(raw_dir / f"{trace_id}.prompt.json", {"asset": {k: v for k, v in asset.items() if k != "local_path"}, "system_prompt": system_prompt})
    last_issue: list[dict[str, Any]] = []
    last_prediction = fallback_prediction(asset, "not_run")
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result = call_model(api_key=api_key, model=str(config.get("default_model_endpoint_id") or ""), system_prompt=system_prompt, asset=asset, timeout=timeout)
            write_json(raw_dir / f"{trace_id}.attempt{attempt}.response.json", result["raw_response"])
            (raw_dir / f"{trace_id}.attempt{attempt}.content.json").write_text(result["raw_content"], encoding="utf-8")
            prediction, issues = validate_prediction(asset, result.get("parsed"))
            last_prediction = prediction
            last_issue = issues
            if not issues:
                return prediction, []
        except Exception as exc:  # noqa: BLE001
            last_prediction = fallback_prediction(asset, f"model_call_failed:{exc}")
            last_issue = [{"code": "model_call_failed", "asset_id": asset["asset_id"], "message": str(exc)[:500]}]
    return last_prediction, last_issue


def role_to_tag_update(prediction: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    role = str(prediction.get("asset_role") or "unknown")
    updated = dict(existing)
    visual_roles = list(updated.get("visual_asset_roles") or [])
    role_item = {
        "asset_id": prediction.get("asset_id"),
        "asset_role": role,
        "visual_label_zh": prediction.get("visual_label_zh") or ROLE_ZH.get(role, "未确定"),
        "target_field": prediction.get("target_field"),
        "confidence": prediction.get("confidence"),
        "needs_resolution": prediction.get("needs_resolution"),
    }
    visual_roles = [item for item in visual_roles if not (isinstance(item, dict) and item.get("asset_id") == prediction.get("asset_id"))]
    visual_roles.append(role_item)
    updated["visual_asset_roles"] = visual_roles
    content_tags = set(str(item) for item in updated.get("content_tags") or [])
    content_tags.add("visual")
    updated["content_tags"] = sorted(content_tags)
    noise_tags = set(str(item) for item in updated.get("noise_tags") or [])
    if role in {"decorative_header", "logo_watermark", "section_title_image"}:
        noise_tags.add("decorative_image")
        updated["noise_tags"] = sorted(noise_tags)
        updated["primary_role"] = "decorative" if role != "section_title_image" else "section"
    elif role in {"question_stem_diagram", "explanation_diagram", "option_diagram", "formula_image", "table_image"}:
        updated["primary_role"] = "question_content"
        updated["noise_tags"] = sorted(noise_tags - {"decorative_image"})
    else:
        updated["needs_resolution"] = True
        updated["noise_tags"] = sorted(noise_tags)
    if bool(prediction.get("needs_resolution")):
        updated["needs_resolution"] = True
    updated["asset_role_tagger_version"] = "docx_asset_role_visual_tagger_v01"
    return updated


def enhance_tags(tags_payload: dict[str, Any], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    tags = [dict(item) for item in tags_payload.get("tags") or tags_payload.get("block_tags") or [] if isinstance(item, dict)]
    by_id = {str(item.get("block_id")): item for item in tags if item.get("block_id")}
    for prediction in predictions:
        block_id = str(prediction.get("block_id") or "")
        if block_id not in by_id:
            by_id[block_id] = {"block_id": block_id, "primary_role": "unknown", "content_tags": [], "noise_tags": []}
            tags.append(by_id[block_id])
        by_id[block_id] = role_to_tag_update(prediction, by_id[block_id])
    for index, item in enumerate(tags):
        block_id = str(item.get("block_id") or "")
        tags[index] = by_id.get(block_id, item)
    payload = dict(tags_payload)
    payload["tags"] = tags
    payload["asset_role_tagger"] = {
        "schema_version": "docx_asset_role_visual_tagger_enhancement.v0.1",
        "prediction_count": len(predictions),
    }
    return payload


def build_review_html(out_dir: Path, predictions: list[dict[str, Any]]) -> None:
    rows = []
    for item in predictions:
        storage = str(item.get("storage_key") or "")
        path = resolve_workspace_path(storage)
        src = safe_rel(path) if path.exists() else ""
        img = f"<img src='../../../../{src}' loading='lazy'>" if src else ""
        rows.append(
            "<tr>"
            f"<td>{item.get('block_id')}</td>"
            f"<td>{item.get('asset_id')}</td>"
            f"<td>{img}</td>"
            f"<td>{item.get('asset_role')}</td>"
            f"<td>{item.get('target_field')}</td>"
            f"<td>{item.get('confidence')}</td>"
            f"<td>{item.get('evidence')}</td>"
            "</tr>"
        )
    html = """<!doctype html><meta charset="utf-8"><title>DOCX Asset Role Visual Tagger</title>
<style>body{font-family:Arial,sans-serif;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:8px;vertical-align:top}img{max-width:260px;max-height:180px}</style>
<h1>DOCX Asset Role Visual Tagger</h1>
<table><thead><tr><th>block</th><th>asset</th><th>image</th><th>role</th><th>field</th><th>conf</th><th>evidence</th></tr></thead><tbody>
""" + "\n".join(rows) + "</tbody></table>"
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(args.config)
    out_root = Path(args.out_root or config.get("owned_output_root") or "outputs/docx_asset_role_visual_tagger_v0_1")
    run_id = args.run_id
    out_dir = out_root / run_id
    if args.clean and out_dir.exists():
        import shutil

        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw_model_responses"
    blocks = load_blocks(args.paragraph_stream)
    tags_payload = read_json(args.block_tags)
    assets = build_assets(blocks, config)
    system_prompt = load_prompt(config)
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    runner = config.get("runner") or {}
    timeout = int(args.timeout or runner.get("per_asset_timeout_seconds") or 120)
    attempts = int(args.max_asset_attempts or runner.get("max_asset_attempts") or 2)
    workers = int(args.max_workers or runner.get("max_workers") or 4)

    predictions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if not api_key and assets:
        issues.append({"code": "missing_api_key", "message": "visual tagging skipped because API key is missing"})
        predictions = [fallback_prediction(asset, "missing_api_key") for asset in assets]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(
                    tag_one,
                    asset=asset,
                    config=config,
                    system_prompt=system_prompt,
                    raw_dir=raw_dir,
                    api_key=api_key,
                    timeout=timeout,
                    attempts=attempts,
                ): asset
                for asset in assets
            }
            for future in concurrent.futures.as_completed(future_map):
                prediction, item_issues = future.result()
                predictions.append(prediction)
                issues.extend(item_issues)
    predictions.sort(key=lambda item: (int(item.get("source_order") or 0), str(item.get("asset_id") or "")))
    asset_role_map = {
        "schema_version": "docx_asset_role_visual_tagger_results.v0.1",
        "run_id": run_id,
        "doc_id": args.doc_id,
        "source_paragraph_stream": safe_rel(args.paragraph_stream),
        "source_block_tags": safe_rel(args.block_tags),
        "prompt_version": config.get("prompt_version"),
        "items": predictions,
        "summary": {
            "asset_count": len(assets),
            "tagged_count": len(predictions),
            "needs_resolution_count": sum(1 for item in predictions if item.get("needs_resolution")),
            "role_counts": dict(Counter(str(item.get("asset_role") or "unknown") for item in predictions)),
            "issue_count": len(issues),
        },
    }
    enhanced_tags = enhance_tags(tags_payload, predictions)
    write_json(out_dir / "asset_role_map.json", asset_role_map)
    write_json(out_dir / "enhanced_block_tags.json", enhanced_tags)
    write_json(out_dir / "issues.json", {"schema_version": "docx_asset_role_visual_tagger_issues.v0.1", "issues": issues})
    build_review_html(out_dir, predictions)
    summary = {
        "schema_version": "docx_asset_role_visual_tagger_summary.v0.1",
        "node": "docx_asset_role_visual_tagger_v01",
        "status": "ok" if not [i for i in issues if i.get("code") not in {"unsupported_visual_format"}] else "needs_review",
        "run_id": run_id,
        "doc_id": args.doc_id,
        "asset_count": len(assets),
        "tagged_count": len(predictions),
        "needs_resolution_count": asset_role_map["summary"]["needs_resolution_count"],
        "role_counts": asset_role_map["summary"]["role_counts"],
        "issue_count": len(issues),
        "artifacts": {
            "asset_role_map": safe_rel(out_dir / "asset_role_map.json"),
            "enhanced_block_tags": safe_rel(out_dir / "enhanced_block_tags.json"),
            "issues": safe_rel(out_dir / "issues.json"),
            "review_html": safe_rel(out_dir / "index.html"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Visually classify DOCX native image assets by business role.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=0)
    parser.add_argument("--max-asset-attempts", type=int, default=0)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    started = datetime.now().isoformat(timespec="seconds")
    summary = run(args)
    summary["started_at"] = started
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
