from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = Path("outputs/docx_native_transcription_package_v0_1")
BUILDER_VERSION = "docx_native_transcription_package_builder_v0.1_20260727"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def rel(path: Path | str) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def load_blocks(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        blocks = payload
    else:
        blocks = payload.get("blocks") or payload.get("paragraphs") or []
    if not isinstance(blocks, list):
        raise ValueError(f"Unsupported block stream shape: {path}")
    return [block for block in blocks if isinstance(block, dict)]


def load_asset_manifest(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [item for item in payload.get("assets") or [] if isinstance(item, dict)]


def load_formula_manifest(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    formulas = payload.get("formulas") if isinstance(payload, dict) else None
    return [item for item in formulas or [] if isinstance(item, dict)]


def load_draft_items(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in ("draft_items", "items", "drafts"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    return []


def load_boundary_packets(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    return [item for item in payload.get("packets") or [] if isinstance(item, dict)]


def normalize_block(block: dict[str, Any]) -> dict[str, Any]:
    block_id = str(block.get("block_id") or "")
    markdown = str(block.get("display_markdown") or block.get("markdown") or "")
    image_refs = [item for item in block.get("image_refs") or block.get("asset_refs") or [] if isinstance(item, dict)]
    inline_glyph_refs = [item for item in block.get("inline_glyph_refs") or [] if isinstance(item, dict)]
    formula_findings = [item for item in block.get("formula_findings") or [] if isinstance(item, dict)]
    table = block.get("table") if isinstance(block.get("table"), dict) else {}
    rows = block.get("rows") if isinstance(block.get("rows"), list) else table.get("rows") if isinstance(table, dict) else []
    source_type = str(block.get("source_block_type") or "")
    return {
        "block_id": block_id,
        "block_order": block.get("block_order", block.get("paragraph_index")),
        "paragraph_index": block.get("paragraph_index"),
        "source_block_type": source_type,
        "text": str(block.get("text") or ""),
        "display_markdown": markdown,
        "plain_text_lossy": str(block.get("plain_text_lossy") or block.get("text") or ""),
        "formula_count": int(block.get("formula_count") or 0),
        "formula_refs": [str(item.get("formula_id") or "") for item in formula_findings if item.get("formula_id")],
        "formula_findings": formula_findings,
        "asset_ids": unique([str(item.get("asset_id") or "") for item in image_refs + inline_glyph_refs if item.get("asset_id")]),
        "image_refs": image_refs,
        "inline_glyph_refs": inline_glyph_refs,
        "table_id": f"tbl_{int(block.get('paragraph_index') or 0):04d}" if source_type == "docx_table" or rows else "",
        "content_loss_flags": block.get("content_loss_flags") or [],
        "qa_status": block.get("qa_status", "unknown"),
    }


def build_asset_index(blocks: list[dict[str, Any]], asset_manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest_by_id = {str(item.get("asset_id") or ""): item for item in asset_manifest if item.get("asset_id")}
    anchors: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        for image in block.get("image_refs") or []:
            asset_id = str(image.get("asset_id") or "")
            if not asset_id:
                continue
            anchors.setdefault(asset_id, []).append(
                {
                    "source_block_id": block["block_id"],
                    "paragraph_index": block.get("paragraph_index"),
                    "mode": image.get("mode"),
                    "placement": image.get("placement"),
                    "display_width_in": image.get("display_width_in"),
                    "display_height_in": image.get("display_height_in"),
                }
            )
    asset_ids = sorted(set(manifest_by_id) | set(anchors))
    assets: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        native = manifest_by_id.get(asset_id, {})
        first_anchor = (anchors.get(asset_id) or [{}])[0]
        assets.append(
            {
                "asset_id": asset_id,
                "native_path": native.get("storage_key") or "",
                "zip_path": native.get("zip_path") or "",
                "format": native.get("format") or "",
                "width_px": native.get("width_px"),
                "height_px": native.get("height_px"),
                "bytes": native.get("bytes"),
                "sha256": native.get("sha256") or "",
                "anchors": anchors.get(asset_id) or [],
                "first_anchor_block_id": first_anchor.get("source_block_id", ""),
                "role": "unassigned_input_asset",
                "belongs_to_field": "",
                "quality_flags": [] if anchors.get(asset_id) else ["asset_not_referenced_by_block_stream"],
            }
        )
    return assets


def build_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for block in blocks:
        is_table = block.get("source_block_type") == "docx_table" or bool(block.get("table_id"))
        if not is_table:
            continue
        raw_rows = block.get("rows") or []
        rows: list[dict[str, Any]] = []
        if isinstance(raw_rows, list):
            for r_index, row in enumerate(raw_rows):
                cells_raw = row.get("cells") if isinstance(row, dict) else row if isinstance(row, list) else []
                cells = []
                for c_index, cell in enumerate(cells_raw or []):
                    value = cell if isinstance(cell, dict) else {"text": str(cell), "markdown": str(cell)}
                    cells.append(
                        {
                            "row": r_index,
                            "col": c_index,
                            "text": str(value.get("text") or ""),
                            "markdown": str(value.get("markdown") or value.get("text") or ""),
                            "rowspan": int(value.get("rowspan") or 1),
                            "colspan": int(value.get("colspan") or 1),
                            "formula_refs": value.get("formula_refs") or [],
                            "asset_refs": value.get("asset_refs") or [],
                        }
                    )
                rows.append({"row": r_index, "cells": cells})
        tables.append(
            {
                "table_id": block.get("table_id") or f"tbl_{len(tables) + 1:04d}",
                "source_block_id": block.get("block_id"),
                "paragraph_index": block.get("paragraph_index"),
                "rows": rows,
                "markdown_fallback": block.get("display_markdown") or "",
                "quality_flags": ["table_markdown_is_linearized"] if not rows else [],
            }
        )
    return tables


def field_from_blocks(field: str, block_ids: list[str], block_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    selected = [block_by_id[block_id] for block_id in block_ids if block_id in block_by_id]
    return {
        "field": field,
        "block_ids": block_ids,
        "markdown": "\n\n".join([str(block.get("display_markdown") or "") for block in selected if block.get("display_markdown")]),
        "asset_ids": unique([asset_id for block in selected for asset_id in block.get("asset_ids") or []]),
        "formula_refs": unique([formula_id for block in selected for formula_id in block.get("formula_refs") or []]),
        "formula_count": sum(int(block.get("formula_count") or 0) for block in selected),
        "qa_statuses": Counter(str(block.get("qa_status") or "unknown") for block in selected),
    }


def build_question_groups(
    *,
    draft_items: list[dict[str, Any]],
    boundary_packets: list[dict[str, Any]],
    block_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    if draft_items:
        for item in draft_items:
            fields_payload = item.get("fields") or {}
            fields: dict[str, Any] = {}
            all_block_ids: list[str] = []
            for field_name, value in fields_payload.items():
                if not isinstance(value, dict):
                    continue
                block_ids = [str(block_id) for block_id in value.get("block_ids") or []]
                all_block_ids.extend(block_ids)
                fields[field_name] = field_from_blocks(field_name, block_ids, block_by_id)
            groups.append(
                {
                    "group_id": str(item.get("source_group_id") or item.get("draft_id") or ""),
                    "draft_id": str(item.get("draft_id") or ""),
                    "record_kind": item.get("record_kind") or "",
                    "solution_policy": item.get("solution_policy") or "",
                    "block_ids": unique(all_block_ids),
                    "fields": fields,
                    "source": "source_backed_draft_items_with_current_block_stream",
                    "quality_flags": [],
                }
            )
        return groups

    for index, packet in enumerate(boundary_packets, start=1):
        block_ids = [str(block_id) for block_id in packet.get("source_block_ids") or []]
        group_id = str(packet.get("packet_id") or f"dq_{index:04d}")
        groups.append(
            {
                "group_id": group_id,
                "draft_id": "",
                "record_kind": "boundary_packet",
                "solution_policy": "",
                "block_ids": block_ids,
                "fields": {"content": field_from_blocks("content", block_ids, block_by_id)},
                "source": "boundary_assembled_packets_with_current_block_stream",
                "quality_flags": [],
            }
        )
    return groups


def render_review(package: dict[str, Any]) -> str:
    summary = package.get("summary") or {}
    groups = package.get("question_groups") or []
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(group.get('group_id')))}</td>"
        f"<td>{len(group.get('block_ids') or [])}</td>"
        f"<td>{html.escape(', '.join(unique([aid for field in (group.get('fields') or {}).values() for aid in field.get('asset_ids') or []]))[:180])}</td>"
        f"<td>{sum(int(field.get('formula_count') or 0) for field in (group.get('fields') or {}).values())}</td>"
        "</tr>"
        for group in groups
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Native Transcription Package</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#111827}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #d1d5db;padding:8px;vertical-align:top}}
code{{white-space:pre-wrap}}.meta{{color:#53627c}}
</style>
<h1>DOCX Native Transcription Package</h1>
<p class="meta">builder={html.escape(str(package.get('builder_version')))}</p>
<ul>
  <li>blocks: <code>{summary.get('block_count')}</code></li>
  <li>assets: <code>{summary.get('asset_count')}</code></li>
  <li>formulas: <code>{summary.get('formula_count')}</code></li>
  <li>tables: <code>{summary.get('table_count')}</code></li>
  <li>question groups: <code>{summary.get('question_group_count')}</code></li>
  <li>qa_status_counts: <code>{html.escape(json.dumps(summary.get('qa_status_counts') or {}, ensure_ascii=False))}</code></li>
</ul>
<h2>Question Groups</h2>
<table><thead><tr><th>group</th><th>blocks</th><th>assets</th><th>formulas</th></tr></thead><tbody>{rows}</tbody></table>
"""


def build(args: argparse.Namespace) -> dict[str, Any]:
    block_stream = args.block_stream
    if not block_stream.exists():
        raise FileNotFoundError(f"block stream not found: {block_stream}")
    blocks = [normalize_block(block) for block in load_blocks(block_stream)]
    block_by_id = {block["block_id"]: block for block in blocks}
    assets = build_asset_index(blocks, load_asset_manifest(args.asset_manifest))
    formulas = load_formula_manifest(args.formula_manifest)
    tables = build_tables(blocks)
    draft_items = load_draft_items(args.draft_items)
    boundary_packets = load_boundary_packets(args.boundary_packets)
    question_groups = build_question_groups(draft_items=draft_items, boundary_packets=boundary_packets, block_by_id=block_by_id)

    run_id = args.run_id or datetime.now().strftime("transcription_package_%Y%m%d_%H%M%S")
    doc_id = args.doc_id or "docx"
    out_dir = args.out_root / run_id / doc_id
    summary = {
        "schema_version": "docx_native_transcription_package_summary.v0.1",
        "status": "ok",
        "run_id": run_id,
        "doc_id": doc_id,
        "block_count": len(blocks),
        "asset_count": len(assets),
        "formula_count": len(formulas),
        "formula_ok_count": sum(1 for item in formulas if item.get("status") == "ok"),
        "table_count": len(tables),
        "question_group_count": len(question_groups),
        "qa_status_counts": dict(Counter(str(block.get("qa_status") or "unknown") for block in blocks)),
        "artifacts": {
            "transcription_package": rel(out_dir / "transcription_package.json"),
            "review_html": rel(out_dir / "review.html"),
        },
    }
    package = {
        "schema_version": "docx_native_transcription_package.v0.1",
        "builder_version": BUILDER_VERSION,
        "run_id": run_id,
        "doc_id": doc_id,
        "source_artifacts": {
            "block_stream": rel(block_stream),
            "asset_manifest": rel(args.asset_manifest) if args.asset_manifest else "",
            "formula_manifest": rel(args.formula_manifest) if args.formula_manifest else "",
            "draft_items": rel(args.draft_items) if args.draft_items else "",
            "boundary_packets": rel(args.boundary_packets) if args.boundary_packets else "",
        },
        "summary": summary,
        "blocks": blocks,
        "assets": assets,
        "tables": tables,
        "formulas": formulas,
        "question_groups": question_groups,
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "transcription_package.json", package)
    write_json(out_dir / "transcription_package_summary.json", summary)
    write_text(out_dir / "review.html", render_review(package))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only DOCX native transcription package from existing node artifacts.")
    parser.add_argument("--block-stream", type=Path, required=True)
    parser.add_argument("--asset-manifest", type=Path, default=None)
    parser.add_argument("--formula-manifest", type=Path, default=None)
    parser.add_argument("--draft-items", type=Path, default=None)
    parser.add_argument("--boundary-packets", type=Path, default=None)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
