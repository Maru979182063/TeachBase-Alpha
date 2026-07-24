from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "english_group_field_relation_normalizer_v0.1_combined_20260717"
FIELD_REF_KEYS = [
    "stem_refs",
    "option_refs",
    "passage_refs",
    "answer_refs",
    "analysis_refs",
    "translation_refs",
    "context_refs",
    "instruction_refs",
    "example_refs",
    "visual_refs",
    "writing_surface_refs",
    "rubric_refs",
    "other_evidence_refs",
]
ORDINARY_STATUS = {"present", "missing", "not_applicable", "uncertain", "partial"}
VISUAL_STATUS = {"required", "not_required", "uncertain"}
PREDICATES = {"contains", "uses_context", "is_child_of", "shares_stimulus", "continues_on", "other"}


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def render_template(text: str, values: dict[str, Any]) -> str:
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys([v for v in values if isinstance(v, str) and v]))


def all_group_refs(group: dict[str, Any]) -> list[str]:
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
    return unique(refs)


def load_block_index(node2_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    block_index: dict[str, dict[str, Any]] = {}
    for window_path in sorted((node2_run / doc_id).glob("page_*/window_input.json")):
        window = read_json(window_path)
        for key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks"):
            for block in window.get(key, []):
                block_index[block["block_ref"]] = block
    return block_index


def compact_input(doc_id: str, groups: list[dict[str, Any]], block_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ref_owner_counts = Counter(ref for group in groups for ref in all_group_refs(group))
    overlaps = defaultdict(list)
    for group in groups:
        for ref in all_group_refs(group):
            if ref_owner_counts[ref] > 1:
                overlaps[ref].append(group["document_group_id"])
    compact_groups = []
    for group in groups:
        refs = all_group_refs(group)
        compact_groups.append(
            {
                "document_group_id": group["document_group_id"],
                "group_kind": group.get("group_kind", ""),
                "open_status": group.get("open_status", "unknown"),
                "source_pages": group.get("source_pages", []),
                "anchor_block_refs": group.get("anchor_block_refs", []),
                "member_block_refs": group.get("member_block_refs", []),
                "context_block_refs": group.get("context_block_refs", []),
                "solution_block_refs": group.get("solution_block_refs", []),
                "analysis_block_refs": group.get("analysis_block_refs", []),
                "translation_block_refs": group.get("translation_block_refs", []),
                "visual_block_refs": group.get("visual_block_refs", []),
                "carryover_block_refs": group.get("carryover_block_refs", []),
                "block_samples": [
                    {
                        "block_ref": ref,
                        "page": block_index.get(ref, {}).get("page"),
                        "node1a_label": block_index.get(ref, {}).get("node1a_label"),
                        "content_role": block_index.get(ref, {}).get("content_role"),
                        "visual_form": block_index.get(ref, {}).get("visual_form"),
                        "is_complete": block_index.get(ref, {}).get("is_complete"),
                        "text": str(block_index.get(ref, {}).get("text", ""))[:600],
                    }
                    for ref in refs
                ],
            }
        )
    return {
        "doc_id": doc_id,
        "groups": compact_groups,
        "overlapping_block_refs": [
            {
                "block_ref": ref,
                "group_ids": group_ids,
                "text": str(block_index.get(ref, {}).get("text", ""))[:600],
            }
            for ref, group_ids in sorted(overlaps.items())
        ],
    }


def call_model(config: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    model = config.get("default_model_endpoint_id", "doubao-seed-2-0-lite-260428")
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 12000,
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
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"http_{response.status_code}: {response.text[:1000]}")
    raw = response.json()
    content = str(raw["choices"][0]["message"]["content"])
    parsed, parse_error = extract_json(content)
    return {
        "model": model,
        "request_body": body,
        "raw_response": raw,
        "raw_content": content,
        "parsed": parsed,
        "parse_error": parse_error,
        "latency_seconds": round(time.time() - started, 3),
    }


def validate_bundle(bundle: dict[str, Any], *, doc_id: str, group_ids: set[str], block_refs_by_group: dict[str, set[str]], all_block_refs: set[str]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if bundle.get("schema") != "group_field_relation_bundle_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if bundle.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if bundle.get("prompt_version") != PROMPT_VERSION:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})

    seen_records = set()
    for i, record in enumerate(bundle.get("normalized_records", [])):
        group_id = record.get("document_group_id")
        seen_records.add(group_id)
        if record.get("schema") != "normalized_group_record_v0.1":
            errors.append({"path": f"$.normalized_records[{i}].schema", "message": "invalid record schema"})
        if group_id not in group_ids:
            errors.append({"path": f"$.normalized_records[{i}].document_group_id", "message": "unknown group id"})
        if record.get("prompt_version") != PROMPT_VERSION:
            errors.append({"path": f"$.normalized_records[{i}].prompt_version", "message": "prompt_version mismatch"})
        field_refs = record.get("field_refs", {})
        for key in FIELD_REF_KEYS:
            refs = field_refs.get(key)
            if not isinstance(refs, list):
                errors.append({"path": f"$.normalized_records[{i}].field_refs.{key}", "message": "must be array"})
                continue
            for ref in refs:
                if ref not in block_refs_by_group.get(group_id, set()):
                    errors.append({"path": f"$.normalized_records[{i}].field_refs.{key}", "message": f"ref {ref} not in group {group_id}"})
        status = record.get("field_status", {})
        for key in ["stem", "options", "passage", "answer", "analysis", "translation", "context"]:
            if status.get(key) not in ORDINARY_STATUS:
                errors.append({"path": f"$.normalized_records[{i}].field_status.{key}", "message": "invalid status"})
        for key in ["visual_asset", "writing_surface"]:
            if status.get(key) not in VISUAL_STATUS:
                errors.append({"path": f"$.normalized_records[{i}].field_status.{key}", "message": "invalid visual status"})
    missing_records = sorted(group_ids - seen_records)
    if missing_records:
        errors.append({"path": "$.normalized_records", "message": "missing records", "group_ids": missing_records})

    graph = bundle.get("projection_graph", {})
    if graph.get("schema") != "group_projection_graph_v0.1":
        errors.append({"path": "$.projection_graph.schema", "message": "invalid graph schema"})
    seen_nodes = set()
    for i, node in enumerate(graph.get("nodes", [])):
        group_id = node.get("document_group_id")
        seen_nodes.add(group_id)
        if group_id not in group_ids:
            errors.append({"path": f"$.projection_graph.nodes[{i}].document_group_id", "message": "unknown group id"})
    missing_nodes = sorted(group_ids - seen_nodes)
    if missing_nodes:
        errors.append({"path": "$.projection_graph.nodes", "message": "missing nodes", "group_ids": missing_nodes})
    for i, relation in enumerate(graph.get("relations", [])):
        if relation.get("subject_group_id") not in group_ids or relation.get("object_group_id") not in group_ids:
            errors.append({"path": f"$.projection_graph.relations[{i}]", "message": "unknown group id"})
        if relation.get("predicate") not in PREDICATES:
            errors.append({"path": f"$.projection_graph.relations[{i}].predicate", "message": "invalid predicate"})
    for i, item in enumerate(graph.get("overlap_resolutions", [])):
        if item.get("block_ref") not in all_block_refs:
            errors.append({"path": f"$.projection_graph.overlap_resolutions[{i}].block_ref", "message": "unknown block ref"})
        if item.get("primary_owner_group_id") not in group_ids:
            errors.append({"path": f"$.projection_graph.overlap_resolutions[{i}].primary_owner_group_id", "message": "unknown group id"})
    return {"valid": not errors, "errors": errors}


def render_review(summary: dict[str, Any], bundle: dict[str, Any]) -> str:
    rec_rows = []
    for record in bundle.get("normalized_records", []):
        status = record.get("field_status", {})
        refs = record.get("field_refs", {})
        rec_rows.append(
            "<tr>"
            f"<td>{record.get('document_group_id','')}</td>"
            f"<td>{record.get('record_kind','')}</td>"
            f"<td><code>stem={status.get('stem')}</code><br><code>answer={status.get('answer')}</code><br><code>context={status.get('context')}</code><br><code>visual={status.get('visual_asset')}</code></td>"
            f"<td><code>stem:{len(refs.get('stem_refs', []))}</code> <code>answer:{len(refs.get('answer_refs', []))}</code> <code>ctx:{len(refs.get('context_refs', []))}</code> <code>visual:{len(refs.get('visual_refs', []))}</code></td>"
            "</tr>"
        )
    node_rows = []
    for node in bundle.get("projection_graph", {}).get("nodes", []):
        node_rows.append(
            "<tr>"
            f"<td>{node.get('document_group_id','')}</td>"
            f"<td>{node.get('semantic_role','')}</td>"
            f"<td>{node.get('projection_target_hint','')}</td>"
            f"<td>{node.get('project_directly_to_question')}</td>"
            "</tr>"
        )
    rel_rows = []
    for rel in bundle.get("projection_graph", {}).get("relations", []):
        rel_rows.append(
            "<tr>"
            f"<td>{rel.get('subject_group_id','')}</td>"
            f"<td>{rel.get('predicate','')}</td>"
            f"<td>{rel.get('object_group_id','')}</td>"
            f"<td>{rel.get('confidence','')}</td>"
            f"<td>{rel.get('reason','')}</td>"
            "</tr>"
        )
    overlap_rows = []
    for item in bundle.get("projection_graph", {}).get("overlap_resolutions", []):
        overlap_rows.append(
            "<tr>"
            f"<td>{item.get('block_ref','')}</td>"
            f"<td>{item.get('primary_owner_group_id','')}</td>"
            f"<td>{', '.join(item.get('secondary_group_ids', []))}</td>"
            f"<td>{item.get('secondary_usage','')}</td>"
            "</tr>"
        )
    return f"""<!doctype html><meta charset="utf-8">
<title>Combined Node3 Field+Relation Review</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.5}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top}}th{{background:#f4f4f4}}code{{background:#eee;padding:1px 4px;border-radius:3px}}</style>
<h1>Combined Node3 Field+Relation Review</h1>
<p>valid=<code>{summary['validation']['valid']}</code>, parsed=<code>{summary['parsed']}</code>, model=<code>{summary['model']}</code></p>
<h2>Normalized Records</h2><table><thead><tr><th>group</th><th>record_kind</th><th>status</th><th>ref counts</th></tr></thead><tbody>{''.join(rec_rows)}</tbody></table>
<h2>Projection Nodes</h2><table><thead><tr><th>group</th><th>semantic_role</th><th>projection_target_hint</th><th>direct?</th></tr></thead><tbody>{''.join(node_rows)}</tbody></table>
<h2>Relations</h2><table><thead><tr><th>subject</th><th>predicate</th><th>object</th><th>confidence</th><th>reason</th></tr></thead><tbody>{''.join(rel_rows)}</tbody></table>
<h2>Overlap Resolutions</h2><table><thead><tr><th>block</th><th>primary owner</th><th>secondary</th><th>secondary usage</th></tr></thead><tbody>{''.join(overlap_rows)}</tbody></table>"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"))
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")
    groups_payload = read_json(workspace_path(args.document_groups_json))
    doc_id = args.doc_id or groups_payload["doc_id"]
    groups = groups_payload.get("document_groups", [])
    node2_run = workspace_path(args.node2_run)
    block_index = load_block_index(node2_run, doc_id)
    input_payload = compact_input(doc_id, groups, block_index)
    system_prompt = workspace_path(args.system_prompt).read_text(encoding="utf-8")
    user_template = workspace_path(args.user_prompt).read_text(encoding="utf-8")
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            "doc_id": doc_id,
            "prompt_version": PROMPT_VERSION,
        },
    )
    model_result = call_model(config, system_prompt, user_prompt, api_key)
    bundle = model_result["parsed"] or {
        "schema": "group_field_relation_bundle_v0.1",
        "doc_id": doc_id,
        "prompt_version": PROMPT_VERSION,
        "normalized_records": [],
        "projection_graph": {
            "schema": "group_projection_graph_v0.1",
            "doc_id": doc_id,
            "prompt_version": PROMPT_VERSION,
            "nodes": [],
            "relations": [],
            "overlap_resolutions": [],
            "open_issues": [{"code": "parse_failed", "message": model_result["parse_error"], "source_refs": []}],
        },
    }
    block_refs_by_group = {group["document_group_id"]: set(all_group_refs(group)) for group in groups}
    all_block_refs = {ref for refs in block_refs_by_group.values() for ref in refs}
    validation = validate_bundle(bundle, doc_id=doc_id, group_ids=set(block_refs_by_group), block_refs_by_group=block_refs_by_group, all_block_refs=all_block_refs)
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    write_json(out_root / "combined_input.json", input_payload)
    write_text(out_root / "used_system_prompt.md", system_prompt)
    write_text(out_root / "used_user_prompt.md", user_prompt)
    write_json(out_root / "request_messages.full.local.json", model_result["request_body"])
    write_json(out_root / "raw_response.json", model_result["raw_response"])
    write_text(out_root / "raw_content.txt", model_result["raw_content"])
    write_json(out_root / "group_field_relation_bundle.json", bundle)
    write_json(out_root / "validation_report.json", validation)
    summary = {
        "schema": "combined_node3_field_relation.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node3_group_field_relation_normalizer_experiment",
        "doc_id": doc_id,
        "model": model_result["model"],
        "prompt_version": PROMPT_VERSION,
        "parsed": model_result["parsed"] is not None,
        "validation": validation,
        "out_dir": rel_workspace(out_root),
        "review_html": rel_workspace(out_root / "review.html"),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "latency_seconds": model_result["latency_seconds"],
        "usage": model_result["raw_response"].get("usage", {}),
    }
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(summary, bundle))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--document-groups-json", required=True)
    parser.add_argument("--node2-run", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--system-prompt", default="prompts/english_group_field_relation_normalizer_system_v0.1.md")
    parser.add_argument("--user-prompt", default="prompts/english_group_field_relation_normalizer_user_v0.1.md")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
