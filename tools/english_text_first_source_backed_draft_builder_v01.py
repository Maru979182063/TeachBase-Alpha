from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import (
    load_block_index,
    read_json,
    rel_workspace,
    unique_refs,
    workspace_path,
    write_json,
    write_text,
)


BUILDER_VERSION = "english_source_backed_draft_builder_v0.1_ref_expansion_20260717"

FIELD_KEY_MAP = {
    "instruction": "instruction_refs",
    "stem": "stem_refs",
    "options": "option_refs",
    "passage": "passage_refs",
    "answer": "answer_refs",
    "analysis": "analysis_refs",
    "translation": "translation_refs",
    "context": "context_refs",
    "examples": "example_refs",
    "visual": "visual_refs",
    "writing_surface": "writing_surface_refs",
    "rubric": "rubric_refs",
    "other_evidence": "other_evidence_refs",
}


def load_normalized_records(node3_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((node3_run / doc_id).glob("dg_*/normalized_group_record.json")):
        record = read_json(path)
        records[record["document_group_id"]] = record
    return records


def load_document_groups(document_groups_json: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(document_groups_json)
    return {group["document_group_id"]: group for group in payload.get("document_groups", [])}


def refs_to_text(refs: list[str], block_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    clean_refs = unique_refs(refs or [])
    missing_refs = [ref for ref in clean_refs if ref not in block_index]
    parts: list[str] = []
    for ref in clean_refs:
        block = block_index.get(ref)
        if not block:
            continue
        text = str(block.get("text", "")).strip()
        if text:
            parts.append(text)
    return {"refs": clean_refs, "text": "\n\n".join(parts), "missing_refs": missing_refs}


def group_source_refs(group: dict[str, Any], record: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in [
        "anchor_block_refs",
        "member_block_refs",
        "context_block_refs",
        "solution_block_refs",
        "analysis_block_refs",
        "translation_block_refs",
        "visual_block_refs",
        "carryover_block_refs",
    ]:
        refs.extend(group.get(key) or [])
    for key in FIELD_KEY_MAP.values():
        refs.extend((record.get("field_refs") or {}).get(key) or [])
    return unique_refs(refs)


def pages_for_refs(refs: list[str], block_index: dict[str, dict[str, Any]]) -> list[int]:
    pages = []
    for ref in refs:
        page = block_index.get(ref, {}).get("page")
        if isinstance(page, int):
            pages.append(page)
    return sorted(set(pages))


def page_image_refs(config: dict[str, Any], doc_id: str, pages: list[int]) -> list[dict[str, Any]]:
    page_dir_value = (config.get("documents", {}).get(doc_id) or {}).get("page_images_dir", "")
    if not page_dir_value:
        return []
    page_dir = workspace_path(page_dir_value)
    refs = []
    for page in pages:
        path = page_dir / f"page_{page:03d}.png"
        refs.append({"page": page, "path": rel_workspace(path), "exists": path.exists()})
    return refs


def graph_node_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["document_group_id"]: node for node in graph.get("nodes", [])}


def relation_views(graph: dict[str, Any], group_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    outgoing = []
    incoming = []
    for relation in graph.get("relations", []):
        if relation.get("subject_group_id") == group_id:
            outgoing.append(relation)
        if relation.get("object_group_id") == group_id:
            incoming.append(relation)
    return outgoing, incoming


def overlap_views(graph: dict[str, Any], group_id: str) -> list[dict[str, Any]]:
    items = []
    for item in graph.get("overlap_resolutions", []):
        if item.get("primary_owner_group_id") == group_id or group_id in (item.get("secondary_group_ids") or []):
            items.append(item)
    return items


def missing_fields(record: dict[str, Any]) -> list[str]:
    result = []
    status = record.get("field_status") or {}
    field_refs = record.get("field_refs") or {}
    for key, value in status.items():
        if value in {"missing", "partial", "uncertain"}:
            result.append(f"{key}:{value}")
        if key == "visual_asset" and value == "required" and not field_refs.get("visual_refs"):
            result.append("visual_asset:required_missing_refs")
        if key == "writing_surface" and value == "required" and not field_refs.get("writing_surface_refs"):
            result.append("writing_surface:required_missing_refs")
    return result


def draft_warnings(
    *,
    record: dict[str, Any],
    source_refs: list[str],
    block_index: dict[str, dict[str, Any]],
    page_images: list[dict[str, Any]],
    overlaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    missing = [ref for ref in source_refs if ref not in block_index]
    if missing:
        warnings.append({"code": "missing_block_ref", "message": "Some source refs were not found in the Node2 block index.", "refs": missing})
    missing_images = [str(item["page"]) for item in page_images if not item["exists"]]
    if missing_images:
        warnings.append({"code": "missing_page_image", "message": "One or more fallback source page images are missing.", "refs": missing_images})
    if overlaps:
        warnings.append(
            {
                "code": "overlap_resolution_present",
                "message": "This draft has overlapping source blocks; follow primary owner/secondary usage before Runtime projection.",
                "refs": [item.get("block_ref", "") for item in overlaps],
            }
        )
    for issue in record.get("open_issues") or []:
        warnings.append(
            {
                "code": str(issue.get("code", "open_issue")),
                "message": str(issue.get("message", "")),
                "refs": issue.get("source_block_refs") or [],
            }
        )
    return warnings


def build_draft_item(
    *,
    config: dict[str, Any],
    doc_id: str,
    group_id: str,
    group: dict[str, Any],
    record: dict[str, Any],
    graph_node: dict[str, Any],
    graph: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    field_refs = record.get("field_refs") or {}
    fields = {
        field_name: refs_to_text(field_refs.get(ref_key) or [], block_index)
        for field_name, ref_key in FIELD_KEY_MAP.items()
    }
    source_refs = group_source_refs(group, record)
    pages = pages_for_refs(source_refs, block_index)
    page_images = page_image_refs(config, doc_id, pages)
    outgoing, incoming = relation_views(graph, group_id)
    overlaps = overlap_views(graph, group_id)
    warnings = draft_warnings(
        record=record,
        source_refs=source_refs,
        block_index=block_index,
        page_images=page_images,
        overlaps=overlaps,
    )
    return {
        "draft_id": f"draft_{group_id}",
        "doc_id": doc_id,
        "source_group_id": group_id,
        "record_kind": str(record.get("record_kind", group.get("group_kind", ""))),
        "semantic_role": str(graph_node.get("semantic_role", "")),
        "projection_target_hint": str(graph_node.get("projection_target_hint", "unresolved")),
        "project_directly_to_question": bool(graph_node.get("project_directly_to_question", False)),
        "fields": fields,
        "relations": {
            "outgoing": outgoing,
            "incoming": incoming,
            "overlap_resolutions": overlaps,
        },
        "source_refs": source_refs,
        "source_pages": pages,
        "page_image_refs": page_images,
        "missing_fields": missing_fields(record),
        "warnings": warnings,
        "open_issues": record.get("open_issues") or [],
    }


def validate_drafts(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, draft in enumerate(payload.get("draft_items", [])):
        draft_id = draft.get("draft_id")
        if not draft_id:
            errors.append({"path": f"$.draft_items[{index}].draft_id", "message": "missing draft_id"})
        if draft_id in seen_ids:
            errors.append({"path": f"$.draft_items[{index}].draft_id", "message": "duplicate draft_id"})
        seen_ids.add(draft_id)
        for field_name in FIELD_KEY_MAP:
            field = (draft.get("fields") or {}).get(field_name)
            if not isinstance(field, dict):
                errors.append({"path": f"$.draft_items[{index}].fields.{field_name}", "message": "missing field object"})
                continue
            for key in ("refs", "text", "missing_refs"):
                if key not in field:
                    errors.append({"path": f"$.draft_items[{index}].fields.{field_name}.{key}", "message": "missing key"})
    return {"valid": not errors, "errors": errors}


def render_field(title: str, field: dict[str, Any]) -> str:
    refs = ", ".join(field.get("refs") or [])
    text = html.escape(field.get("text") or "")
    if not text and not refs:
        text = "<span class='muted'>空</span>"
    return f"""
<section class="field">
  <h4>{html.escape(title)} <small>{html.escape(refs)}</small></h4>
  <pre>{text}</pre>
</section>
"""


def render_review(payload: dict[str, Any], validation: dict[str, Any]) -> str:
    cards = []
    for draft in payload.get("draft_items", []):
        fields_html = "".join(
            render_field(title, draft["fields"][key])
            for title, key in [
                ("instruction（指令）", "instruction"),
                ("passage（文章/材料）", "passage"),
                ("stem（题干）", "stem"),
                ("options（选项）", "options"),
                ("examples（例句/例子）", "examples"),
                ("answer（答案）", "answer"),
                ("analysis（解析）", "analysis"),
                ("translation（翻译）", "translation"),
                ("context（组内上下文）", "context"),
                ("visual（视觉/表格/图示 refs）", "visual"),
                ("writing_surface（作答区/作文纸）", "writing_surface"),
                ("rubric（评分标准）", "rubric"),
            ]
        )
        outgoing = html.escape(json.dumps(draft["relations"]["outgoing"], ensure_ascii=False, indent=2))
        incoming = html.escape(json.dumps(draft["relations"]["incoming"], ensure_ascii=False, indent=2))
        overlaps = html.escape(json.dumps(draft["relations"]["overlap_resolutions"], ensure_ascii=False, indent=2))
        warnings = html.escape(json.dumps(draft["warnings"], ensure_ascii=False, indent=2))
        page_images = "".join(
            f"<a href='{html.escape(workspace_path(item['path']).resolve().as_uri())}'>p{item['page']}</a> "
            for item in draft.get("page_image_refs", [])
        )
        cards.append(
            f"""
<article class="card">
  <h2>{html.escape(draft['draft_id'])} <small>{html.escape(draft['projection_target_hint'])} / direct={draft['project_directly_to_question']}</small></h2>
  <p><b>source_group_id（来源组）</b>: <code>{html.escape(draft['source_group_id'])}</code></p>
  <p><b>record_kind（归一类型）</b>: {html.escape(draft['record_kind'])}</p>
  <p><b>semantic_role（组间语义角色）</b>: {html.escape(draft['semantic_role'])}</p>
  <p><b>source_pages（来源页）</b>: {', '.join(map(str, draft['source_pages']))} &nbsp; <b>page_image_refs（原页图）</b>: {page_images}</p>
  <p><b>missing_fields（缺失/不确定字段）</b>: {html.escape(', '.join(draft['missing_fields']) or 'none')}</p>
  {fields_html}
  <details><summary>relations（组间关系）</summary><h4>outgoing（当前组指向别人）</h4><pre>{outgoing}</pre><h4>incoming（别人指向当前组）</h4><pre>{incoming}</pre></details>
  <details><summary>overlap_resolutions（重叠归属）</summary><pre>{overlaps}</pre></details>
  <details><summary>warnings（警告）</summary><pre>{warnings}</pre></details>
</article>
"""
        )
    summary = payload["summary"]
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Source Backed Draft Builder Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f6f7f9;color:#202124;line-height:1.45}}
.card{{background:white;border:1px solid #d8dce2;border-radius:8px;padding:16px;margin:18px 0}}
h1,h2,h3,h4{{margin:0.35em 0}}
small{{color:#5f6368;font-weight:400}}
code{{background:#eef0f3;padding:1px 4px;border-radius:4px}}
pre{{white-space:pre-wrap;background:#f8f9fb;border:1px solid #e2e5ea;border-radius:6px;padding:10px;overflow:auto}}
.field{{border-top:1px solid #eef0f3;padding-top:8px;margin-top:8px}}
.muted{{color:#8a8f98}}
</style>
<h1>Node4 SourceBackedDraftBuilder Review</h1>
<p>doc_id=<code>{html.escape(payload['doc_id'])}</code>, validation=<code>{validation['valid']}</code>, drafts=<code>{summary['draft_count']}</code>, direct=<code>{summary['direct_question_count']}</code>, non_direct=<code>{summary['non_direct_count']}</code>, warnings=<code>{summary['warning_count']}</code></p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    document_groups_json = workspace_path(args.document_groups_json)
    groups_payload = read_json(document_groups_json)
    doc_id = args.doc_id or groups_payload["doc_id"]
    node2_run = workspace_path(args.node2_run)
    node3_run = workspace_path(args.node3_run)
    graph_path = workspace_path(args.group_projection_graph)
    out_root = workspace_path(config["owned_output_root"]) / args.run_id

    groups = load_document_groups(document_groups_json)
    records = load_normalized_records(node3_run, doc_id)
    graph = read_json(graph_path)
    graph_nodes = graph_node_by_id(graph)
    block_index = load_block_index(node2_run, doc_id)

    selected_ids = set(args.group_ids or [])
    group_ids = sorted(selected_ids or set(groups) | set(records) | set(graph_nodes))
    draft_items = []
    for group_id in group_ids:
        if group_id not in groups or group_id not in records:
            continue
        draft_items.append(
            build_draft_item(
                config=config,
                doc_id=doc_id,
                group_id=group_id,
                group=groups[group_id],
                record=records[group_id],
                graph_node=graph_nodes.get(group_id, {}),
                graph=graph,
                block_index=block_index,
            )
        )

    missing_block_ref_count = sum(
        len(field["missing_refs"])
        for draft in draft_items
        for field in draft["fields"].values()
    )
    warning_count = sum(len(draft["warnings"]) for draft in draft_items)
    payload = {
        "schema": "source_backed_draft_items_v0.1",
        "doc_id": doc_id,
        "builder_version": BUILDER_VERSION,
        "draft_items": draft_items,
        "summary": {
            "draft_count": len(draft_items),
            "direct_question_count": sum(1 for draft in draft_items if draft["project_directly_to_question"]),
            "non_direct_count": sum(1 for draft in draft_items if not draft["project_directly_to_question"]),
            "missing_block_ref_count": missing_block_ref_count,
            "warning_count": warning_count,
        },
    }
    validation = validate_drafts(payload)
    summary = {
        "schema": "source_backed_draft_builder.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node4_source_backed_draft_builder",
        "doc_id": doc_id,
        "builder_version": BUILDER_VERSION,
        "document_groups_json": rel_workspace(document_groups_json),
        "node2_run": rel_workspace(node2_run),
        "node3_run": rel_workspace(node3_run),
        "group_projection_graph": rel_workspace(graph_path),
        "out_dir": rel_workspace(out_root),
        "validation": validation,
        "draft_summary": payload["summary"],
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "model_call_enabled": False,
        "draft_items_json": rel_workspace(out_root / "draft_items.json"),
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "draft_items.json", payload)
    write_json(out_root / "validation_report.json", validation)
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(payload, validation))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--document-groups-json", required=True)
    parser.add_argument("--node2-run", required=True)
    parser.add_argument("--node3-run", required=True)
    parser.add_argument("--group-projection-graph", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
