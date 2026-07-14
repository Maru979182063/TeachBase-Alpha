from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
QVS_SCHEMA = "question_visual_structure.v1.1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except Exception:
        return str(path_value).replace("\\", "/")


def is_relative_storage_key(value: str) -> bool:
    text = str(value or "").strip().replace("\\", "/")
    if not text or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", text):
        return False
    if re.match(r"^[A-Za-z]:/", text) or text.startswith("/") or text.startswith("//"):
        return False
    return all(part not in {"", ".", ".."} for part in text.split("/"))


def map_asset_role(field: str) -> str:
    field = str(field or "").strip()
    if field == "analysis":
        return "analysis"
    if field == "answer":
        return "analysis"
    if field == "option":
        return "option"
    return "stem"


def map_placement_scope(field: str) -> str:
    field = str(field or "").strip()
    if field == "analysis" or field == "answer":
        return "after_analysis"
    if field == "option":
        return "option_inline"
    if field == "stem":
        return "after_stem"
    return "evidence_only"


def normalize_field_scope(field: str) -> str:
    field = str(field or "").strip()
    return field if field in {"stem", "answer", "analysis", "option"} else "stem"


def normalize_path_token(value: str) -> str:
    return str(value or "").replace("\\", "/").lower()


def replace_image_links(markdown: str, insertions: list[dict[str, Any]]) -> str:
    text = str(markdown or "")
    for insertion in insertions:
        ref_id = str(insertion.get("image_ref_id") or "").strip()
        asset_id = str(insertion.get("asset_id") or "").strip()
        native_path = str(insertion.get("native_path") or "").strip()
        if not asset_id:
            continue
        display_ref = f"asset://{asset_id}"
        replacement = f"![{asset_id}]({display_ref})"
        if ref_id:
            text = re.sub(
                rf"!\[[^\]]*{re.escape(ref_id)}[^\]]*\]\([^)]+\)",
                replacement,
                text,
            )
        if native_path:
            text = text.replace(native_path, display_ref)
            text = text.replace(native_path.replace("\\", "/"), display_ref)
            text = text.replace(native_path.replace("\\", "\\\\"), display_ref)
    return text


def split_refined_markdown(markdown: str, fallback: dict[str, str]) -> dict[str, str]:
    text = str(markdown or "").strip()
    if not text:
        return fallback
    answer_match = re.search(r"【答案】", text)
    analysis_match = re.search(r"【分析】", text)
    if not answer_match:
        return {**fallback, "display_markdown": text}
    stem = text[: answer_match.start()].strip()
    if analysis_match and analysis_match.start() > answer_match.end():
        answer = text[answer_match.end() : analysis_match.start()].strip()
        analysis = text[analysis_match.end() :].strip()
    else:
        answer = text[answer_match.end() :].strip()
        analysis = fallback.get("analysis_md", "")
    return {
        "display_markdown": text,
        "stem_md": stem or fallback.get("stem_md", ""),
        "answer_md": answer or fallback.get("answer_md", ""),
        "analysis_md": analysis or fallback.get("analysis_md", ""),
    }


def build_insertion_maps(asset_manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    assets_by_id = {
        str(item.get("asset_id") or "").strip(): item
        for item in asset_manifest.get("assets", [])
        if isinstance(item, dict) and str(item.get("asset_id") or "").strip()
    }
    insertion_by_ref = {
        str(item.get("image_ref_id") or "").strip(): item
        for item in asset_manifest.get("image_insertions", [])
        if isinstance(item, dict) and str(item.get("image_ref_id") or "").strip()
    }
    return assets_by_id, insertion_by_ref


def build_visual_asset(insertion: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(insertion.get("asset_id") or asset.get("asset_id") or "").strip()
    storage_key = safe_rel(insertion.get("native_path") or asset.get("native_path") or "")
    field = normalize_field_scope(insertion.get("field") or "")
    return {
        "asset_id": asset_id,
        "asset_role": map_asset_role(field),
        "option_key": None,
        "placement_scope": map_placement_scope(field),
        "attach_status": "attached",
        "file_status": "materialized",
        "display_ref": f"asset://{asset_id}",
        "storage_key": storage_key,
        "bbox_space": "docx_native_paragraph_anchor",
        "bbox_json": {
            "paragraph_index": insertion.get("paragraph_index"),
            "mode": insertion.get("mode") or "inline",
        },
        "source_image_role": "docx_native_media",
        "source_image_asset_id": asset_id,
        "source_image_storage_key": storage_key,
        "confidence": 1.0,
        "runtime_run_id": "",
        "review_flags": [],
        "docx_anchor": {
            "image_ref_id": insertion.get("image_ref_id"),
            "paragraph_index": insertion.get("paragraph_index"),
            "mode": insertion.get("mode"),
            "rId": insertion.get("rId"),
            "zip_path": insertion.get("zip_path"),
        },
        "width_px": asset.get("width_px") or insertion.get("width_px"),
        "height_px": asset.get("height_px") or insertion.get("height_px"),
        "sha256": asset.get("sha256"),
        "format": asset.get("format"),
    }


def build_condition_group_index(question: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    model_refine = question.get("model_refine") if isinstance(question.get("model_refine"), dict) else {}
    for item in model_refine.get("condition_groups", []) or []:
        if not isinstance(item, dict):
            continue
        formula_id = str(item.get("formula_id") or "").strip()
        if formula_id:
            indexed[formula_id] = item
    for block in question.get("blocks", []) or []:
        if not isinstance(block, dict) or block.get("type") != "condition_group":
            continue
        formula_ids = [str(item or "").strip() for item in block.get("formula_ids", []) if str(item or "").strip()]
        for formula_id in formula_ids:
            indexed.setdefault(
                formula_id,
                {
                    "formula_id": formula_id,
                    "items": block.get("items", []),
                    "markdown": block.get("markdown", ""),
                },
            )
    return indexed


def build_content_blocks(
    question: dict[str, Any],
    insertion_by_ref: dict[str, dict[str, Any]],
    insertions_for_question: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks = []
    condition_groups = build_condition_group_index(question)
    order = 1
    for block in question.get("blocks", []) or []:
        if not isinstance(block, dict):
            continue
        field = normalize_field_scope(block.get("field") or "")
        block_id = f"{question['question_id']}_blk_{order:03d}"
        base = {
            "block_id": block_id,
            "block_order": order,
            "scope": field,
            "paragraph_index": block.get("paragraph_index"),
        }
        block_type = str(block.get("type") or "").strip()
        if block_type == "image":
            ref_id = str(block.get("image_ref_id") or "").strip()
            insertion = insertion_by_ref.get(ref_id, {})
            asset_id = str(block.get("asset_id") or insertion.get("asset_id") or "").strip()
            if asset_id:
                blocks.append(
                    {
                        **base,
                        "block_type": "image",
                        "asset_id": asset_id,
                        "display_ref": f"asset://{asset_id}",
                        "image_ref_id": ref_id,
                    }
                )
                order += 1
            continue
        if block_type == "condition_group":
            formula_ids = [str(item or "").strip() for item in block.get("formula_ids", []) if str(item or "").strip()]
            formula_id = formula_ids[0] if formula_ids else ""
            structured = condition_groups.get(formula_id, {})
            markdown = structured.get("markdown") or block.get("markdown") or ""
            items = structured.get("items") or block.get("items") or []
            blocks.append(
                {
                    **base,
                    "block_type": "condition_group",
                    "semantic_type": "condition_group",
                    "text_md": replace_image_links(markdown, insertions_for_question),
                    "formula_ids": formula_ids,
                    "condition_group": {
                        "formula_id": formula_id,
                        "items": items,
                        "markdown": replace_image_links(markdown, insertions_for_question),
                    },
                    "source": "omml",
                }
            )
            order += 1
            continue
        markdown = str(block.get("markdown") or block.get("text") or "").strip()
        if markdown:
            blocks.append(
                {
                    **base,
                    "block_type": "markdown",
                    "text_md": replace_image_links(markdown, insertions_for_question),
                    "formula_ids": block.get("formula_ids", []),
                }
            )
            order += 1
    return blocks


def build_aligned_manifest(
    ingest_dir: Path,
    packets: dict[str, Any],
    asset_manifest: dict[str, Any],
    release_decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assets_by_id, insertion_by_ref = build_insertion_maps(asset_manifest)
    decisions = {
        str(item.get("question_id") or "").strip(): item
        for item in release_decision.get("decisions", [])
        if isinstance(item, dict)
    }
    questions = []
    report_rows = []
    all_condition_groups = 0
    all_visual_assets = 0
    source_docx_name = Path(str(packets.get("source_docx") or "")).name
    for question in packets.get("questions", []) or []:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("question_id") or "").strip()
        if not qid:
            continue
        insertions_for_question = [
            insertion_by_ref[ref_id]
            for ref_id in question.get("image_ref_ids", []) or []
            if ref_id in insertion_by_ref
        ]
        visual_assets = []
        image_anchors = []
        for insertion in insertions_for_question:
            asset_id = str(insertion.get("asset_id") or "").strip()
            asset = assets_by_id.get(asset_id, {})
            visual_asset = build_visual_asset(insertion, asset)
            visual_assets.append(visual_asset)
            image_anchors.append(
                {
                    "image_ref_id": insertion.get("image_ref_id"),
                    "asset_id": asset_id,
                    "paragraph_index": insertion.get("paragraph_index"),
                    "field": normalize_field_scope(insertion.get("field") or ""),
                    "mode": insertion.get("mode"),
                    "storage_key": visual_asset["storage_key"],
                    "width_px": visual_asset.get("width_px"),
                    "height_px": visual_asset.get("height_px"),
                }
            )
        refined_markdown = ""
        model_refine = question.get("model_refine") if isinstance(question.get("model_refine"), dict) else {}
        if model_refine:
            refined_markdown = str(model_refine.get("model_refined_markdown") or "").strip()
        display_markdown = refined_markdown or str(question.get("display_markdown_model_refined") or question.get("display_markdown") or "")
        display_markdown = replace_image_links(display_markdown, insertions_for_question)
        fallback_sections = {
            "display_markdown": display_markdown,
            "stem_md": replace_image_links(question.get("stem_text_md", ""), insertions_for_question),
            "answer_md": replace_image_links(question.get("answer_text_md", ""), insertions_for_question),
            "analysis_md": replace_image_links(question.get("analysis_text_md", ""), insertions_for_question),
        }
        sections = split_refined_markdown(display_markdown, fallback_sections)
        content_blocks = build_content_blocks(question, insertion_by_ref, insertions_for_question)
        condition_groups = [
            block["condition_group"]
            for block in content_blocks
            if block.get("block_type") == "condition_group" and isinstance(block.get("condition_group"), dict)
        ]
        decision = decisions.get(qid, {})
        review_flags = [
            str(item)
            for item in (question.get("review_flags", []) or []) + (model_refine.get("review_flags", []) or [])
            if str(item).strip()
        ]
        qvs = {
            "schema_version": QVS_SCHEMA,
            "generated_by": "docx_native_backend_align_v01",
            "runtime_run_id": ingest_dir.name,
            "question_uid": qid,
            "stem_md": sections["stem_md"],
            "answer_md": sections["answer_md"],
            "analysis_md": sections["analysis_md"],
            "legacy_stem_md": sections["display_markdown"],
            "gating": {
                "release_status": decision.get("status", "unknown"),
                "decision_reasons": decision.get("reasons", []),
                "model_refine_status": model_refine.get("status") or "not_run",
                "needs_review": bool(review_flags) or decision.get("status") == "review",
            },
            "options": [],
            "content_blocks": content_blocks,
            "visual_assets": visual_assets,
            "review_flags": sorted(set(review_flags)),
        }
        source_refs = {
            "schema_versions": {
                "question_visual_structure": QVS_SCHEMA,
                "docx_native_backend_alignment": "docx_native_backend_alignment.v0.1",
            },
            "page_no": 1,
            "bbox": {"x": 0, "y": 0, "width": 100, "height": 100},
            "question_visual_structure": qvs,
            "docx_native": {
                "source_docx_name": source_docx_name,
                "ingest_dir": safe_rel(ingest_dir),
                "question_id": qid,
                "start_paragraph_index": question.get("start_paragraph_index"),
                "end_paragraph_index": question.get("end_paragraph_index"),
                "formula_ids": question.get("formula_ids", []),
                "image_anchors": image_anchors,
                "condition_groups": condition_groups,
                "model_refine": {
                    "status": model_refine.get("status") or "not_run",
                    "condition_group_count": len(condition_groups),
                },
            },
        }
        questions.append(
            {
                "question_uid": qid,
                "question_id": qid,
                "local_task_id": qid,
                "source_node_local_id": "root",
                "question_type": "math_docx_native_question",
                "display_markdown": sections["display_markdown"],
                "stem_text_md": sections["stem_md"],
                "answer_text_md": sections["answer_md"],
                "analysis_text_md": sections["analysis_md"],
                "checkpoint_codes": [],
                "subject_tags": ["docx_native", "math_junior"],
                "difficulty_level": 3,
                "difficulty_confidence": 0.5,
                "question_visual_structure": qvs,
                "source_refs_json": source_refs,
                "merged_source_refs_json": source_refs,
                "review_flags": sorted(set(review_flags)),
            }
        )
        all_condition_groups += len(condition_groups)
        all_visual_assets += len(visual_assets)
        report_rows.append(
            {
                "question_id": qid,
                "visual_asset_count": len(visual_assets),
                "condition_group_count": len(condition_groups),
                "release_status": decision.get("status", "unknown"),
                "model_refine_status": model_refine.get("status") or "not_run",
                "review_flag_count": len(set(review_flags)),
            }
        )
    manifest = {
        "schema_version": "docx_native_backend_aligned_manifest.v0.1",
        "payload_type": "question_asset_manifest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_docx_name": source_docx_name,
        "runtime_contract": {
            "adapter": "tools/runtime_visual_split_adapter.mjs",
            "question_visual_structure_schema": QVS_SCHEMA,
            "track_code": "math_junior",
            "no_runtime_import": True,
            "no_database_write": True,
        },
        "questions": questions,
    }
    report = {
        "schema_version": "docx_native_backend_alignment_report.v0.1",
        "status": "ok",
        "generated_at": manifest["generated_at"],
        "input_ingest_dir": str(ingest_dir),
        "question_count": len(questions),
        "visual_asset_count": all_visual_assets,
        "condition_group_count": all_condition_groups,
        "release_status_counts": dict(Counter(row["release_status"] for row in report_rows)),
        "model_refine_status_counts": dict(Counter(row["model_refine_status"] for row in report_rows)),
        "runtime_imported": False,
        "database_written": False,
        "rows": report_rows,
    }
    return manifest, report


def write_report_md(path: Path, report: dict[str, Any], manifest_path: Path) -> None:
    lines = [
        "# DOCX Native Backend Alignment v0.1",
        "",
        "## Real Status",
        "",
        "- This is a backend-aligned preview manifest only.",
        "- Runtime import: not run.",
        "- Database write: not run.",
        "",
        "## Artifacts",
        "",
        f"- Manifest: `{safe_rel(manifest_path)}`",
        f"- Report JSON: `{safe_rel(path.with_suffix('.json'))}`",
        "",
        "## Counts",
        "",
        f"- Questions: {report['question_count']}",
        f"- Visual assets: {report['visual_asset_count']}",
        f"- Condition groups: {report['condition_group_count']}",
        f"- Release statuses: `{json.dumps(report['release_status_counts'], ensure_ascii=False)}`",
        f"- Model refine statuses: `{json.dumps(report['model_refine_status_counts'], ensure_ascii=False)}`",
        "",
        "## Backend Field Alignment",
        "",
        "- Task fields: `local_task_id`, `source_node_local_id`, `question_type`, `stem`, `answer`, `explanation` are available through the existing adapter.",
        "- Persisted structure: `source_refs_json.question_visual_structure` uses `question_visual_structure.v1.1`.",
        "- Visual assets use `asset_id`, `display_ref`, relative `storage_key`, `attach_status=attached`, `file_status=materialized`.",
        "- DOCX anchors are preserved under `source_refs_json.docx_native.image_anchors`.",
        "- Structured condition groups are preserved under both QVS `content_blocks` and `source_refs_json.docx_native.condition_groups`.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    ingest_dir = Path(args.ingest_dir)
    if not ingest_dir.is_absolute():
        ingest_dir = WORKSPACE_ROOT / ingest_dir
    packets_path = Path(args.packets) if args.packets else ingest_dir / "question_packets_backend_preview.json"
    if not packets_path.is_absolute():
        packets_path = WORKSPACE_ROOT / packets_path
    out_dir = Path(args.out_dir) if args.out_dir else ingest_dir / "backend_aligned_v01"
    if not out_dir.is_absolute():
        out_dir = WORKSPACE_ROOT / out_dir
    asset_manifest_path = ingest_dir / "asset_manifest_backend_preview.json"
    release_decision_path = ingest_dir / "release_decision_preview.json"
    packets = read_json(packets_path)
    summary_path = ingest_dir / "summary.json"
    if not packets.get("source_docx") and summary_path.exists():
        packets["source_docx"] = read_json(summary_path).get("source_docx", "")
    asset_manifest = read_json(asset_manifest_path)
    release_decision = read_json(release_decision_path) if release_decision_path.exists() else {}
    manifest, report = build_aligned_manifest(ingest_dir, packets, asset_manifest, release_decision)
    manifest_path = out_dir / "docx_native_backend_aligned_question_asset_manifest.json"
    report_path = out_dir / "docx_native_backend_alignment_report.json"
    report_md_path = out_dir / "docx_native_backend_alignment_report.md"
    write_json(manifest_path, manifest)
    report["artifact_paths"] = {
        "manifest": str(manifest_path),
        "report_json": str(report_path),
        "report_md": str(report_md_path),
        "packets_input": str(packets_path),
    }
    write_json(report_path, report)
    write_report_md(report_md_path, report, manifest_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest-dir", required=True, type=Path)
    parser.add_argument("--packets", type=Path)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
