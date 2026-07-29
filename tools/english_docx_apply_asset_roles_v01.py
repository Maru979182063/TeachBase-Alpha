from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

KEEP_ROLES = {
    "question_stem_diagram",
    "explanation_diagram",
    "option_diagram",
    "formula_image",
    "table_image",
    "unknown",
}

DROP_ROLES = {
    "section_title_image",
    "decorative_header",
    "logo_watermark",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def compact_text(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "..."


def asset_role_items(asset_role_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = asset_role_map.get("items") or []
    by_asset: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("asset_id") or "")
        bid = str(item.get("block_id") or "")
        if aid:
            by_asset[aid] = item
        if aid and bid:
            by_asset[f"{bid}::{aid}"] = item
    return by_asset


def decision_for(asset_id: str, block_id: str, role_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = role_map.get(f"{block_id}::{asset_id}") or role_map.get(asset_id) or {}
    role = str(item.get("asset_role") or "unknown")
    if role in DROP_ROLES:
        keep = False
        reason = "visual_role_drop"
    elif role in KEEP_ROLES:
        keep = True
        reason = "visual_role_keep"
    else:
        keep = True
        reason = "unknown_role_keep_for_review"
    label = str(item.get("visual_label_zh") or "")
    description = str(item.get("visual_description") or "")
    if not label:
        label = {
            "question_stem_diagram": "题干图",
            "explanation_diagram": "解析图",
            "option_diagram": "选项图",
            "formula_image": "公式图",
            "table_image": "表格图",
            "section_title_image": "栏目图",
            "decorative_header": "装饰图",
            "logo_watermark": "水印/Logo",
            "unknown": "图片",
        }.get(role, "图片")
    return {
        "asset_id": asset_id,
        "block_id": block_id,
        "keep": keep,
        "decision": "keep" if keep else "drop",
        "decision_reason": reason,
        "asset_role": role,
        "target_field": item.get("target_field", "unknown"),
        "visual_label_zh": label,
        "visual_description": compact_text(description, 180),
        "evidence": compact_text(str(item.get("evidence") or ""), 220),
        "confidence": item.get("confidence", 0.0),
        "needs_resolution": bool(item.get("needs_resolution", False)),
    }


def image_markdown(asset_id: str, decision: dict[str, Any]) -> str:
    desc = str(decision.get("visual_description") or "").strip()
    label = str(decision.get("visual_label_zh") or "图片").strip()
    alt = label if not desc else f"{label}：{desc}"
    return f"![{alt}](asset://{asset_id})"


def rebuild_markdown_from_tokens(tokens: list[dict[str, Any]]) -> str:
    return "".join(str(token.get("markdown") or "") for token in tokens).strip()


def plain_text_from_tokens(tokens: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token.get("type") == "image":
            continue
        parts.append(str(token.get("source_text") if "source_text" in token else token.get("markdown") or ""))
    return "".join(parts).strip()


def apply_to_block(block: dict[str, Any], role_map: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = dict(block)
    decisions: list[dict[str, Any]] = []
    new_tokens: list[dict[str, Any]] = []
    block_id = str(block.get("block_id") or "")
    for token in block.get("tokens") or []:
        token = dict(token)
        if token.get("type") != "image":
            new_tokens.append(token)
            continue
        asset_id = str(token.get("asset_id") or "")
        decision = decision_for(asset_id, block_id, role_map)
        decisions.append(decision)
        if not decision["keep"]:
            continue
        token.update(
            {
                "markdown": image_markdown(asset_id, decision),
                "asset_role": decision["asset_role"],
                "target_field": decision["target_field"],
                "visual_label_zh": decision["visual_label_zh"],
                "visual_description": decision["visual_description"],
                "asset_keep_decision": decision["decision"],
                "asset_keep_reason": decision["decision_reason"],
                "asset_role_confidence": decision["confidence"],
                "asset_role_needs_resolution": decision["needs_resolution"],
            }
        )
        new_tokens.append(token)
    updated["tokens"] = new_tokens
    updated["image_refs"] = [token for token in new_tokens if token.get("type") == "image"]
    updated["asset_refs"] = list(updated["image_refs"])
    updated["display_markdown"] = rebuild_markdown_from_tokens(new_tokens)
    updated["markdown"] = updated["display_markdown"]
    updated["plain_text_lossy"] = plain_text_from_tokens(new_tokens)
    updated["text"] = updated["plain_text_lossy"]
    flags = set(str(flag) for flag in updated.get("content_loss_flags") or [])
    if any(not d["keep"] for d in decisions):
        flags.add("invalid_or_decorative_images_dropped")
    if any(d["keep"] for d in decisions):
        flags.add("image_assets_visual_labeled")
    updated["content_loss_flags"] = sorted(flags)
    updated["asset_decisions"] = decisions
    return updated, decisions


def build_document_markdown(blocks: list[dict[str, Any]]) -> str:
    parts = [str(block.get("display_markdown") or "") for block in blocks if str(block.get("display_markdown") or "").strip()]
    return "\n\n".join(parts).rstrip() + "\n"


def render_preview(out_dir: Path, blocks: list[dict[str, Any]], kept_assets: list[dict[str, Any]]) -> None:
    asset_by_id = {asset["asset_id"]: asset for asset in kept_assets}

    def render_md(markdown: str) -> str:
        escaped = html.escape(markdown)
        pattern = re.compile(r"!\[([^\]]*)\]\(asset://([^)]+)\)")
        for match in list(pattern.finditer(markdown)):
            alt, asset_id = match.group(1), match.group(2)
            asset = asset_by_id.get(asset_id)
            if not asset:
                continue
            token = html.escape(match.group(0))
            replacement = (
                f"<figure><img src='{html.escape(asset.get('preview_src') or '')}' alt='{html.escape(alt)}'>"
                f"<figcaption>{html.escape(alt)}</figcaption></figure>"
            )
            escaped = escaped.replace(token, replacement)
        return "<p>" + escaped.replace("\n", "<br>") + "</p>"

    rows = []
    for block in blocks:
        markdown = str(block.get("display_markdown") or "")
        if not markdown:
            continue
        rows.append(
            "<article>"
            f"<div class='meta'>{html.escape(str(block.get('block_id')))} flags={html.escape(','.join(block.get('content_loss_flags') or []))}</div>"
            f"{render_md(markdown)}"
            "</article>"
        )
    html_text = """<!doctype html><meta charset="utf-8"><title>English DOCX Asset Filter Preview</title>
<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f8fb;color:#172033}article{background:white;border:1px solid #d8e0ec;border-radius:8px;margin:0 0 16px;padding:16px}.meta{color:#667899;font-size:13px}img{max-width:820px;max-height:560px;border:1px solid #cfd8e6}figcaption{font-size:13px;color:#475569;margin-top:6px}</style>
<h1>English DOCX Asset Filter Preview</h1>
""" + "\n".join(rows)
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    block_payload = read_json(args.block_stream)
    asset_manifest = read_json(args.asset_manifest)
    asset_role_map = read_json(args.asset_role_map)
    role_map = asset_role_items(asset_role_map)
    blocks: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for block in block_payload.get("blocks") or []:
        updated, block_decisions = apply_to_block(block, role_map)
        blocks.append(updated)
        decisions.extend(block_decisions)
    kept_ids = {decision["asset_id"] for decision in decisions if decision.get("keep")}
    kept_assets = [asset for asset in asset_manifest.get("assets") or [] if str(asset.get("asset_id") or "") in kept_ids]
    dropped_ids = {decision["asset_id"] for decision in decisions if not decision.get("keep")}
    out_dir = Path(args.out_root) / args.run_id / args.doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filtered_block_stream = dict(block_payload)
    counts = dict(filtered_block_stream.get("counts") or {})
    counts["image_insertions_after_asset_filter"] = sum(len(block.get("asset_refs") or []) for block in blocks)
    counts["image_assets_kept"] = len(kept_ids)
    counts["image_assets_dropped"] = len(dropped_ids)
    filtered_block_stream["counts"] = counts
    filtered_block_stream["blocks"] = blocks
    filtered_block_stream["asset_filter"] = {
        "schema_version": "english_docx_asset_filter.v0.1",
        "source_asset_role_map": safe_rel(args.asset_role_map),
        "kept_asset_ids": sorted(kept_ids),
        "dropped_asset_ids": sorted(dropped_ids),
    }
    filtered_asset_manifest = dict(asset_manifest)
    filtered_asset_manifest["assets"] = kept_assets
    filtered_asset_manifest["asset_filter"] = filtered_block_stream["asset_filter"]
    write_json(out_dir / "block_stream.image_filtered.json", filtered_block_stream)
    write_json(out_dir / "asset_manifest.image_filtered.json", filtered_asset_manifest)
    write_json(out_dir / "asset_decisions.json", {"schema_version": "english_docx_asset_decisions.v0.1", "items": decisions})
    (out_dir / "document.image_filtered.md").write_text(build_document_markdown(blocks), encoding="utf-8")
    render_preview(out_dir, blocks, kept_assets)
    summary = {
        "schema_version": "english_docx_asset_filter_summary.v0.1",
        "pipeline_id": "english_docx_apply_asset_roles_v01",
        "run_id": args.run_id,
        "doc_id": args.doc_id,
        "status": "ok",
        "source_block_stream": safe_rel(args.block_stream),
        "source_asset_manifest": safe_rel(args.asset_manifest),
        "source_asset_role_map": safe_rel(args.asset_role_map),
        "decision_count": len(decisions),
        "kept_asset_count": len(kept_ids),
        "dropped_asset_count": len(dropped_ids),
        "role_counts": dict(Counter(str(item.get("asset_role") or "unknown") for item in decisions)),
        "artifacts": {
            "block_stream": safe_rel(out_dir / "block_stream.image_filtered.json"),
            "asset_manifest": safe_rel(out_dir / "asset_manifest.image_filtered.json"),
            "asset_decisions": safe_rel(out_dir / "asset_decisions.json"),
            "document_markdown": safe_rel(out_dir / "document.image_filtered.md"),
            "preview_html": safe_rel(out_dir / "index.html"),
            "summary": safe_rel(out_dir / "summary.json"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply visual asset role decisions to English DOCX block stream.")
    parser.add_argument("--block-stream", required=True, type=Path)
    parser.add_argument("--asset-manifest", required=True, type=Path)
    parser.add_argument("--asset-role-map", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--out-root", default="outputs/english_docx_asset_filter_v0_1")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
