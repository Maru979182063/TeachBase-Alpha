from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUILDER_VERSION = "docx_math_source_backed_draft_builder_v0.1_parts_only_20260717"
SCHEMA = "docx_math_source_backed_draft_items_v0.1"

FIELD_PART_MAP = {
    "stem": {"stem"},
    "subquestions": {"subquestions", "subquestion"},
    "options": {"options", "option"},
    "answer": {"answer", "answers"},
    "explanation": {"explanation", "analysis", "solution", "proof"},
    "teaching_note": {"teaching_note", "knowledge", "method", "hint"},
    "context": {"context", "section_context", "shared_context"},
    "assets": {"assets", "visual", "diagram", "table"},
}

FIELD_ORDER = [
    "stem",
    "subquestions",
    "options",
    "answer",
    "explanation",
    "teaching_note",
    "context",
    "assets",
    "other_evidence",
]


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


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def load_block_index(block_stream_path: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(block_stream_path)
    return {block["block_id"]: block for block in payload.get("blocks", [])}


def load_groups(groups_path: Path | None) -> dict[str, dict[str, Any]]:
    if not groups_path or not groups_path.exists():
        return {}
    payload = read_json(groups_path)
    return {group["group_id"]: group for group in payload.get("groups", [])}


def asset_refs_for_blocks(block_ids: list[str], block_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block_id in block_ids:
        block = block_index.get(block_id) or {}
        for image in block.get("image_refs") or []:
            asset_id = str(image.get("asset_id") or "")
            storage_key = str(image.get("storage_key") or "")
            key = (asset_id, storage_key)
            if key in seen:
                continue
            seen.add(key)
            assets.append(
                {
                    "asset_id": asset_id,
                    "storage_key": storage_key,
                    "format": str(image.get("format") or ""),
                    "width_px": image.get("width_px"),
                    "height_px": image.get("height_px"),
                    "bytes": image.get("bytes"),
                    "sha256": str(image.get("sha256") or ""),
                    "mode": str(image.get("mode") or ""),
                    "source_block_id": block_id,
                }
            )
    return assets


def refs_to_field(block_ids: list[str], block_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    clean_ids = unique(block_ids)
    missing = [block_id for block_id in clean_ids if block_id not in block_index]
    block_markdowns: list[dict[str, str]] = []
    texts: list[str] = []
    markdowns: list[str] = []
    formula_count = 0
    formula_structural_risks: list[dict[str, Any]] = []
    for block_id in clean_ids:
        block = block_index.get(block_id)
        if not block:
            continue
        text = str(block.get("text") or "").strip()
        markdown = str(block.get("display_markdown") or text).strip()
        if text:
            texts.append(text)
        if markdown:
            markdowns.append(markdown)
            block_markdowns.append({"block_id": block_id, "markdown": markdown})
        formula_count += int(block.get("formula_count") or 0)
        for risk in block.get("formula_structural_risks") or []:
            if isinstance(risk, dict):
                formula_structural_risks.append({"block_id": block_id, **risk})
    return {
        "block_ids": clean_ids,
        "text": "\n\n".join(texts),
        "markdown": "\n\n".join(markdowns),
        "block_markdowns": block_markdowns,
        "missing_block_ids": missing,
        "formula_count": formula_count,
        "formula_structural_risks": formula_structural_risks,
        "asset_refs": asset_refs_for_blocks(clean_ids, block_index),
    }


def part_field(part_type: str) -> str:
    normalized = str(part_type or "").strip().lower()
    for field, aliases in FIELD_PART_MAP.items():
        if normalized in aliases:
            return field
    return "other_evidence"


def fields_from_item(
    item: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
    *,
    context_block_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    field_ids: dict[str, list[str]] = {field: [] for field in FIELD_ORDER}
    for part in item.get("parts") or []:
        field = part_field(str(part.get("part_type") or ""))
        field_ids[field].extend(part.get("block_ids") or [])
    field_ids["context"].extend(context_block_ids or [])
    field_ids["other_evidence"].extend(item.get("unassigned_block_ids") or [])
    return {field: refs_to_field(field_ids[field], block_index) for field in FIELD_ORDER}


def infer_record_kind(fields: dict[str, dict[str, Any]], solution_policy: str) -> str:
    has_options = bool(fields["options"]["block_ids"])
    has_subquestions = bool(fields["subquestions"]["block_ids"])
    has_answer = bool(fields["answer"]["block_ids"])
    has_explanation = bool(fields["explanation"]["block_ids"])
    if solution_policy == "absent_expected" and has_subquestions:
        return "math_practice_draft_without_solution_with_subquestions"
    if solution_policy == "absent_expected":
        return "math_practice_draft_without_solution"
    if has_options:
        return "math_multiple_choice_with_solution" if has_answer or has_explanation else "math_multiple_choice"
    if has_subquestions:
        return "math_composite_question_with_solution" if has_answer or has_explanation else "math_composite_question"
    return "math_question_with_solution" if has_answer or has_explanation else "math_question_draft"


def draft_warnings(
    *,
    item: dict[str, Any],
    full_item: dict[str, Any] | None,
    fields: dict[str, dict[str, Any]],
    source_group_block_ids: list[str],
    group: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for warning in item.get("warnings") or []:
        warnings.append(dict(warning))
    for issue in (full_item or {}).get("issues") or []:
        warnings.append(
            {
                "code": str(issue.get("type") or issue.get("code") or "upstream_issue"),
                "message": "Upstream question part normalizer reported this issue.",
                "severity": str(issue.get("severity") or "warning"),
                "refs": issue.get("source_block_refs") or issue.get("block_ids") or [],
                "source": "question_part_normalizer",
            }
        )
    missing_refs = unique(
        ref
        for field in fields.values()
        for ref in field.get("missing_block_ids", [])
    )
    if missing_refs:
        warnings.append(
            {
                "code": "missing_block_refs",
                "message": "Some referenced blocks are missing from immutable_block_stream.",
                "refs": missing_refs,
            }
        )
    if not fields["stem"]["block_ids"] and not fields["subquestions"]["block_ids"]:
        warnings.append(
            {
                "code": "missing_stem_or_subquestions",
                "message": "Draft has neither stem nor subquestions.",
                "refs": [],
            }
        )
    if source_group_block_ids and group is None:
        warnings.append(
            {
                "code": "membership_group_missing",
                "message": "Source membership group was not found; source refs are reconstructed from normalized parts.",
                "refs": [str(item.get("question_group_id") or "")],
            }
        )
    return warnings


def build_item(
    *,
    doc_id: str,
    item: dict[str, Any],
    full_item: dict[str, Any] | None,
    group: dict[str, Any] | None,
    block_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    group_id = str(item.get("question_group_id") or "")
    context_block_ids = [
        str(ctx.get("block_id"))
        for ctx in (full_item or {}).get("section_context") or []
        if ctx.get("block_id")
    ]
    fields = fields_from_item(item, block_index, context_block_ids=context_block_ids)
    source_group_block_ids = list((group or {}).get("block_ids") or [])
    source_refs = unique(
        source_group_block_ids
        + [block_id for field in fields.values() for block_id in field["block_ids"]]
    )
    question_asset_block_ids = unique(
        block_id
        for field_name, field in fields.items()
        if field_name != "context"
        for block_id in field["block_ids"]
    )
    asset_refs = asset_refs_for_blocks(question_asset_block_ids, block_index)
    formula_count = sum(int((block_index.get(ref) or {}).get("formula_count") or 0) for ref in source_refs)
    warnings = draft_warnings(item=item, full_item=full_item, fields=fields, source_group_block_ids=source_group_block_ids, group=group)
    solution_policy = str(item.get("solution_policy") or "unknown")
    return {
        "draft_id": f"docx_math_draft_{group_id}",
        "doc_id": doc_id,
        "source_group_id": group_id,
        "builder_status": "draft_with_warnings" if warnings else "draft_ready",
        "solution_policy": solution_policy,
        "record_kind": infer_record_kind(fields, solution_policy),
        "fields": fields,
        "source_refs": source_refs,
        "source_group_block_ids": source_group_block_ids,
        "formula_count": formula_count,
        "asset_refs": asset_refs,
        "warnings": warnings,
        "open_issues": (item.get("open_issues") or []) + ((full_item or {}).get("issues") or []),
    }


def render_markdown(doc_payload: dict[str, Any]) -> str:
    lines = [
        f"# {doc_payload['doc_id']}",
        "",
        f"- schema: `{doc_payload['schema']}`",
        f"- builder_version: `{doc_payload['builder_version']}`",
        f"- draft_count: `{doc_payload['summary']['draft_count']}`",
        f"- warning_count: `{doc_payload['summary']['warning_count']}`",
        "",
    ]
    for draft in doc_payload.get("draft_items", []):
        lines.extend(
            [
                f"## {draft['draft_id']} / {draft['source_group_id']}",
                "",
                f"- status: `{draft['builder_status']}`",
                f"- kind: `{draft['record_kind']}`",
                f"- solution_policy: `{draft['solution_policy']}`",
                f"- formulas: `{draft['formula_count']}` assets: `{len(draft['asset_refs'])}`",
                "",
            ]
        )
        for field_name in ["stem", "subquestions", "options", "answer", "explanation", "teaching_note", "context", "other_evidence"]:
            field = draft["fields"][field_name]
            if not field["block_ids"] and not field["markdown"]:
                continue
            lines.extend([f"### {field_name}", ""])
            lines.append(field["markdown"] or "")
            lines.append("")
        if draft["asset_refs"]:
            lines.extend(["### assets", ""])
            for asset in draft["asset_refs"]:
                lines.append(f"- `{asset['asset_id']}` `{asset['storage_key']}` {asset.get('width_px')}x{asset.get('height_px')}")
            lines.append("")
        if draft["warnings"]:
            lines.extend(["### warnings", ""])
            for warning in draft["warnings"]:
                lines.append(f"- `{warning.get('code')}` {warning.get('message')}")
            lines.append("")
    return "\n".join(lines)


def render_html(doc_payload: dict[str, Any]) -> str:
    body = [
        "<!doctype html><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;line-height:1.65;background:#eef2f7;margin:0;padding:24px;color:#111827}.doc{max-width:1100px;margin:auto}.item{background:white;border:1px solid #d8dee9;border-radius:8px;margin:16px 0;padding:18px}.meta{color:#52627a;font-size:14px}.field{border-left:3px solid #d0d7e2;padding-left:12px;margin:12px 0;white-space:pre-wrap}.warn{background:#fff7cc;color:#8a4b00;padding:4px 7px;border-radius:4px}code{background:#edf2f7;padding:2px 5px;border-radius:4px}</style>",
        "<div class='doc'>",
        f"<h1>{html.escape(doc_payload['doc_id'])}</h1>",
        f"<p class='meta'>drafts={doc_payload['summary']['draft_count']} warnings={doc_payload['summary']['warning_count']} assets={doc_payload['summary']['asset_ref_count']}</p>",
    ]
    for draft in doc_payload.get("draft_items", []):
        body.append("<section class='item'>")
        body.append(f"<h2>{html.escape(draft['draft_id'])}</h2>")
        body.append(
            "<p class='meta'>"
            f"group=<code>{html.escape(draft['source_group_id'])}</code> "
            f"status=<code>{html.escape(draft['builder_status'])}</code> "
            f"kind=<code>{html.escape(draft['record_kind'])}</code> "
            f"formulas={draft['formula_count']} assets={len(draft['asset_refs'])}"
            "</p>"
        )
        for field_name in ["stem", "subquestions", "options", "answer", "explanation", "teaching_note", "context", "other_evidence"]:
            field = draft["fields"][field_name]
            if not field["block_ids"] and not field["markdown"]:
                continue
            body.append(f"<h3>{html.escape(field_name)}</h3>")
            body.append(f"<div class='field'>{html.escape(field['markdown'])}</div>")
        if draft["asset_refs"]:
            body.append("<h3>assets</h3><ul>")
            for asset in draft["asset_refs"]:
                body.append(
                    "<li>"
                    f"<code>{html.escape(asset['asset_id'])}</code> "
                    f"{html.escape(asset['storage_key'])} "
                    f"{html.escape(str(asset.get('width_px')))}x{html.escape(str(asset.get('height_px')))}"
                    "</li>"
                )
            body.append("</ul>")
        if draft["warnings"]:
            body.append("<h3>warnings</h3>")
            for warning in draft["warnings"]:
                body.append(f"<p><span class='warn'>{html.escape(str(warning.get('code')))}</span> {html.escape(str(warning.get('message')))}</p>")
        body.append("</section>")
    body.append("</div>")
    return "\n".join(body)


def build_doc(
    *,
    part_path: Path,
    block_stream_path: Path,
    groups_path: Path | None,
    out_root: Path,
) -> dict[str, Any]:
    part_payload = read_json(part_path)
    items = part_payload.get("items") or []
    full_path = part_path.with_name("normalization_results_full.json")
    full_payload = read_json(full_path) if full_path.exists() else {"items": []}
    full_by_group_id = {
        str(item.get("question_group_id") or ""): item
        for item in full_payload.get("items", [])
    }
    doc_id = str(items[0].get("doc_id") if items else part_path.parents[1].name)
    block_index = load_block_index(block_stream_path)
    groups = load_groups(groups_path)
    draft_items = [
        build_item(
            doc_id=doc_id,
            item=item,
            full_item=full_by_group_id.get(str(item.get("question_group_id") or "")),
            group=groups.get(str(item.get("question_group_id") or "")),
            block_index=block_index,
        )
        for item in items
    ]
    recovered_internal_block_count = sum(
        len((full_by_group_id.get(str(item.get("question_group_id") or "")) or {}).get("recovered_internal_block_ids") or [])
        for item in items
    )
    warning_count = sum(len(item["warnings"]) for item in draft_items)
    payload = {
        "schema": SCHEMA,
        "doc_id": doc_id,
        "builder_version": BUILDER_VERSION,
        "source_artifacts": {
            "question_part_normalizations": rel(part_path),
            "immutable_block_stream": rel(block_stream_path),
            "membership_groups": rel(groups_path) if groups_path else "",
        },
        "draft_items": draft_items,
        "summary": {
            "draft_count": len(draft_items),
            "draft_ready_count": sum(1 for item in draft_items if item["builder_status"] == "draft_ready"),
            "draft_with_warnings_count": sum(1 for item in draft_items if item["builder_status"] == "draft_with_warnings"),
            "warning_count": warning_count,
            "upstream_issue_count": sum(len((full_by_group_id.get(str(item.get("question_group_id") or "")) or {}).get("issues") or []) for item in items),
            "recovered_internal_block_count": recovered_internal_block_count,
            "missing_block_ref_count": sum(
                len(field["missing_block_ids"])
                for item in draft_items
                for field in item["fields"].values()
            ),
            "formula_count": sum(item["formula_count"] for item in draft_items),
            "asset_ref_count": sum(len(item["asset_refs"]) for item in draft_items),
            "no_runtime_import": True,
            "no_database_write": True,
        },
    }
    doc_out = out_root / doc_id / "source_backed_draft"
    write_json(doc_out / "docx_math_source_backed_draft_items.json", payload)
    write_text(doc_out / "docx_math_source_backed_draft_items.md", render_markdown(payload))
    write_text(doc_out / "index.html", render_html(payload))
    return payload


def find_doc_path(root: Path, doc_id: str, suffix: str) -> Path | None:
    candidate = root / doc_id / suffix
    if candidate.exists():
        return candidate
    matches = list(root.glob(f"*/{suffix}"))
    for match in matches:
        if match.parents[len(Path(suffix).parts) - 1].name == doc_id:
            return match
    return None


def discover_part_paths(part_roots: list[Path], exclude_doc_ids: set[str]) -> list[Path]:
    paths: list[Path] = []
    for root in part_roots:
        for path in sorted(root.glob("*/question_part_normalization/question_part_normalizations.json")):
            doc_id = path.parents[1].name
            if doc_id in exclude_doc_ids:
                continue
            paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part-root", action="append", required=True)
    parser.add_argument("--block-stream-root", required=True)
    parser.add_argument("--membership-root", action="append", default=[])
    parser.add_argument("--exclude-doc-id", action="append", default=[])
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args()

    part_roots = [Path(value) for value in args.part_root]
    block_stream_root = Path(args.block_stream_root)
    membership_roots = [Path(value) for value in args.membership_root]
    out_root = Path(args.out_root)
    excluded = set(args.exclude_doc_id)

    started_at = datetime.now().isoformat(timespec="seconds")
    doc_payloads: list[dict[str, Any]] = []
    for part_path in discover_part_paths(part_roots, excluded):
        doc_id = part_path.parents[1].name
        block_stream = block_stream_root / doc_id / "immutable_block_stream.json"
        if not block_stream.exists():
            raise FileNotFoundError(f"Missing immutable_block_stream for {doc_id}: {block_stream}")
        groups_path = None
        for membership_root in membership_roots:
            candidate = membership_root / doc_id / "full_doc_membership" / "membership_groups.json"
            if candidate.exists():
                groups_path = candidate
                break
        doc_payloads.append(
            build_doc(
                part_path=part_path,
                block_stream_path=block_stream,
                groups_path=groups_path,
                out_root=out_root,
            )
        )

    index = {
        "schema": "docx_math_source_backed_draft_builder_run_v0.1",
        "builder_version": BUILDER_VERSION,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "doc_count": len(doc_payloads),
        "docs": [
            {
                "doc_id": payload["doc_id"],
                "draft_count": payload["summary"]["draft_count"],
                "warning_count": payload["summary"]["warning_count"],
                "asset_ref_count": payload["summary"]["asset_ref_count"],
                "artifact": rel(out_root / payload["doc_id"] / "source_backed_draft" / "docx_math_source_backed_draft_items.json"),
                "preview_html": rel(out_root / payload["doc_id"] / "source_backed_draft" / "index.html"),
            }
            for payload in doc_payloads
        ],
        "no_runtime_import": True,
        "no_database_write": True,
    }
    write_json(out_root / "run_summary.json", index)
    write_text(
        out_root / "index.html",
        "<!doctype html><meta charset='utf-8'><h1>DOCX math source-backed drafts</h1><ul>"
        + "".join(
            f"<li><a href='{html.escape(doc['doc_id'])}/source_backed_draft/index.html'>{html.escape(doc['doc_id'])}</a> "
            f"drafts={doc['draft_count']} warnings={doc['warning_count']} assets={doc['asset_ref_count']}</li>"
            for doc in index["docs"]
        )
        + "</ul>",
    )
    print(json.dumps(index, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
