from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from english_text_first_normalizer.common import (
    FIELD_REF_KEYS,
    read_json,
    rel_workspace,
    unique_refs,
    workspace_path,
    write_json,
    write_text,
)


RECONCILER_VERSION = "english_group_ownership_reconciler_v0.1_overlap_projection_view_20260723"

OWNED_FIELD_KEYS = {
    "instruction_refs",
    "stem_refs",
    "option_refs",
    "answer_refs",
    "analysis_refs",
    "translation_refs",
    "example_refs",
    "writing_surface_refs",
    "rubric_refs",
}

REFERENCE_FIELD_KEYS = {
    "passage_refs",
    "context_refs",
    "visual_refs",
    "other_evidence_refs",
}


def load_normalized_records(node3_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((node3_run / doc_id).glob("dg_*/normalized_group_record.json")):
        record = read_json(path)
        records[record["document_group_id"]] = record
    return records


def status_for_refs(field_name: str, refs: list[str], previous: str) -> str:
    if field_name in {"options", "passage"} and previous == "not_applicable":
        return "not_applicable"
    if refs:
        return "present" if previous != "partial" else "partial"
    if previous in {"not_applicable", "missing"}:
        return previous
    return "missing"


def apply_overlap_ownership(
    record: dict[str, Any],
    overlap_items: list[dict[str, Any]],
    *,
    graph_nodes: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    group_id = record["document_group_id"]
    adjusted = json.loads(json.dumps(record, ensure_ascii=False))
    adjusted["prompt_version"] = RECONCILER_VERSION
    field_refs = adjusted.setdefault("field_refs", {})
    changes: list[dict[str, Any]] = []

    for item in overlap_items:
        block_ref = item.get("block_ref")
        primary = item.get("primary_owner_group_id")
        if not block_ref or group_id == primary:
            continue
        current_direct = graph_nodes.get(group_id, {}).get("project_directly_to_question") is True
        primary_direct = graph_nodes.get(primary, {}).get("project_directly_to_question") is True
        if current_direct and not primary_direct:
            continue

        removed_from: list[str] = []
        for key in OWNED_FIELD_KEYS:
            if current_direct and key == "writing_surface_refs":
                continue
            refs = field_refs.get(key) or []
            if block_ref in refs:
                field_refs[key] = [ref for ref in refs if ref != block_ref]
                removed_from.append(key)

        if removed_from:
            if block_ref not in field_refs.get("context_refs", []):
                field_refs["context_refs"] = unique_refs((field_refs.get("context_refs") or []) + [block_ref])
            changes.append(
                {
                    "block_ref": block_ref,
                    "primary_owner_group_id": primary,
                    "secondary_usage": item.get("secondary_usage", ""),
                    "removed_from_owned_fields": removed_from,
                    "kept_as": "context_refs",
                    "reason": item.get("reason", ""),
                }
            )

    status = adjusted.setdefault("field_status", {})
    status["stem"] = status_for_refs("stem", field_refs.get("stem_refs") or [], status.get("stem", "missing"))
    status["options"] = status_for_refs("options", field_refs.get("option_refs") or [], status.get("options", "missing"))
    status["passage"] = status_for_refs("passage", field_refs.get("passage_refs") or [], status.get("passage", "missing"))
    status["answer"] = status_for_refs("answer", field_refs.get("answer_refs") or [], status.get("answer", "missing"))
    status["analysis"] = status_for_refs("analysis", field_refs.get("analysis_refs") or [], status.get("analysis", "missing"))
    status["translation"] = status_for_refs("translation", field_refs.get("translation_refs") or [], status.get("translation", "missing"))
    status["context"] = "present" if field_refs.get("context_refs") else status.get("context", "missing")

    if changes:
        adjusted.setdefault("normalizer_warnings", []).append(
            {
                "code": "ownership_adjusted_projection_fields",
                "message": "Owned field refs were removed from this secondary group according to Node3b overlap ownership; source refs are still preserved.",
                "source_block_refs": [change["block_ref"] for change in changes],
                "adjustments": changes,
            }
        )
    adjusted["ownership_reconciler"] = {
        "version": RECONCILER_VERSION,
        "source_prompt_version": record.get("prompt_version", ""),
        "adjustment_count": len(changes),
    }
    return adjusted, changes


def validate(records: dict[str, dict[str, Any]], graph: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    graph_group_ids = {node.get("document_group_id") for node in graph.get("nodes", [])}
    for group_id, record in records.items():
        if record.get("schema") != "normalized_group_record_v0.1":
            errors.append({"path": f"{group_id}.schema", "message": "invalid normalized record schema"})
        refs = record.get("field_refs") or {}
        for key in FIELD_REF_KEYS:
            if not isinstance(refs.get(key), list):
                errors.append({"path": f"{group_id}.field_refs.{key}", "message": "missing ref array"})
        if graph_group_ids and group_id not in graph_group_ids:
            errors.append({"path": f"{group_id}", "message": "group missing from projection graph"})
    return {"valid": not errors, "errors": errors}


def render_review(summary: dict[str, Any], changes_by_group: dict[str, list[dict[str, Any]]], records: dict[str, dict[str, Any]]) -> str:
    rows = []
    for group_id in sorted(records):
        record = records[group_id]
        refs = record.get("field_refs") or {}
        changes = changes_by_group.get(group_id, [])
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(group_id)}</code></td>"
            f"<td>{html.escape(record.get('record_kind',''))}</td>"
            f"<td>stem={len(refs.get('stem_refs') or [])}<br>answer={len(refs.get('answer_refs') or [])}<br>analysis={len(refs.get('analysis_refs') or [])}<br>translation={len(refs.get('translation_refs') or [])}<br>context={len(refs.get('context_refs') or [])}</td>"
            f"<td>{len(changes)}</td>"
            f"<td><pre>{html.escape(json.dumps(changes, ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Node3c Ownership Reconciler</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.5}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #d8dce2;padding:8px;vertical-align:top}}
th{{background:#f4f6f8}}
pre{{white-space:pre-wrap;margin:0;font-size:12px}}
code{{background:#eef0f3;padding:1px 4px;border-radius:4px}}
</style>
<h1>Node3c Ownership Reconciler</h1>
<p>doc_id=<code>{html.escape(summary["doc_id"])}</code>, adjusted_groups=<code>{summary["adjusted_group_count"]}</code>, adjusted_refs=<code>{summary["adjusted_ref_count"]}</code>, valid=<code>{summary["validation"]["valid"]}</code></p>
<table>
<thead><tr><th>group</th><th>record_kind</th><th>field ref counts after reconcile</th><th>changes</th><th>change detail</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    doc_id = args.doc_id
    node3_run = workspace_path(args.node3_run)
    graph_path = workspace_path(args.group_projection_graph)
    graph = read_json(graph_path)
    graph_nodes = {
        node.get("document_group_id"): node
        for node in graph.get("nodes", [])
        if node.get("document_group_id")
    }
    if not doc_id:
        doc_id = graph.get("doc_id", "")
    records = load_normalized_records(node3_run, doc_id)

    overlap_by_secondary: dict[str, list[dict[str, Any]]] = defaultdict(list)
    refs_with_primary = {
        item.get("block_ref"): item
        for item in graph.get("overlap_resolutions", [])
        if item.get("block_ref") and item.get("primary_owner_group_id")
    }
    for item in graph.get("overlap_resolutions", []):
        for group_id in item.get("secondary_group_ids") or []:
            overlap_by_secondary[group_id].append(item)

    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    out_doc = out_root / doc_id
    adjusted_records: dict[str, dict[str, Any]] = {}
    changes_by_group: dict[str, list[dict[str, Any]]] = {}
    for group_id, record in records.items():
        candidate_items = list(overlap_by_secondary.get(group_id, []))
        refs = record.get("field_refs") or {}
        for key in OWNED_FIELD_KEYS:
            for ref in refs.get(key) or []:
                item = refs_with_primary.get(ref)
                if item and item not in candidate_items and item.get("primary_owner_group_id") != group_id:
                    candidate_items.append(item)
        adjusted, changes = apply_overlap_ownership(record, candidate_items, graph_nodes=graph_nodes)
        adjusted_records[group_id] = adjusted
        changes_by_group[group_id] = changes
        group_dir = out_doc / group_id
        write_json(group_dir / "normalized_group_record.json", adjusted)
        write_json(group_dir / "ownership_adjustments.json", changes)
        write_json(group_dir / "source_normalized_group_record.json", record)

    validation = validate(adjusted_records, graph)
    summary = {
        "schema": "english_group_ownership_reconciler.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node3c_group_ownership_reconciler",
        "doc_id": doc_id,
        "reconciler_version": RECONCILER_VERSION,
        "source_node3_run": rel_workspace(node3_run),
        "group_projection_graph": rel_workspace(graph_path),
        "out_dir": rel_workspace(out_root),
        "adjusted_group_count": sum(1 for changes in changes_by_group.values() if changes),
        "adjusted_ref_count": sum(len(changes) for changes in changes_by_group.values()),
        "validation": validation,
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "model_call_enabled": False,
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "run_summary.json", summary)
    write_json(out_root / "ownership_adjustments_by_group.json", changes_by_group)
    write_json(out_root / "validation_report.json", validation)
    write_text(out_root / "review.html", render_review(summary, changes_by_group, adjusted_records))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--node3-run", required=True)
    parser.add_argument("--group-projection-graph", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
