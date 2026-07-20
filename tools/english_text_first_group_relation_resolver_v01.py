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


def group_sort_key(group: dict[str, Any]) -> tuple[int, str]:
    group_id = str(group.get("document_group_id", ""))
    try:
        return (int(group_id.rsplit("_", 1)[1]), group_id)
    except (IndexError, ValueError):
        return (10**9, group_id)


def make_group_chunks(groups: list[dict[str, Any]], *, max_groups: int, overlap_groups: int) -> list[list[dict[str, Any]]]:
    ordered = sorted(groups, key=group_sort_key)
    if not ordered:
        return []
    if max_groups <= 0 or len(ordered) <= max_groups:
        return [ordered]
    overlap = max(0, min(overlap_groups, max_groups - 1))
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(ordered):
        end = min(len(ordered), start + max_groups)
        chunks.append(ordered[start:end])
        if end == len(ordered):
            break
        start = end - overlap
    return chunks


def chunk_label(groups: list[dict[str, Any]], index: int) -> str:
    first = groups[0]["document_group_id"] if groups else "empty"
    last = groups[-1]["document_group_id"] if groups else "empty"
    return f"chunk_{index:02d}_{first}_{last}"


def load_normalized_records(node3_run: Path, doc_id: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted((node3_run / doc_id).glob("dg_*/normalized_group_record.json")):
        records.append(read_json(path))
    return records


def load_group_records(document_groups_json: Path) -> list[dict[str, Any]]:
    return read_json(document_groups_json).get("document_groups", [])


def load_block_index(node2_run: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    block_index: dict[str, dict[str, Any]] = {}
    for window_path in sorted((node2_run / doc_id).glob("page_*/window_input.json")):
        window = read_json(window_path)
        for key in ("previous_tail_blocks", "current_page_blocks", "next_head_blocks"):
            for block in window.get(key, []):
                block_index[block["block_ref"]] = block
    return block_index


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
    return list(dict.fromkeys(refs))


def compact_input(doc_id: str, groups: list[dict[str, Any]], normalized: list[dict[str, Any]], block_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    norm_by_id = {record["document_group_id"]: record for record in normalized}
    ref_owner_counts = Counter(ref for group in groups for ref in all_group_refs(group))
    overlaps = defaultdict(list)
    for group in groups:
        for ref in all_group_refs(group):
            if ref_owner_counts[ref] > 1:
                overlaps[ref].append(group["document_group_id"])

    compact_groups = []
    for group in groups:
        group_id = group["document_group_id"]
        refs = all_group_refs(group)
        normalized_record = norm_by_id.get(group_id, {})
        compact_normalized = {
            "record_kind": normalized_record.get("record_kind", ""),
            "field_refs": normalized_record.get("field_refs", {}),
            "field_status": normalized_record.get("field_status", {}),
            "open_issue_codes": [
                issue.get("code", "")
                for issue in normalized_record.get("open_issues", [])
                if isinstance(issue, dict)
            ],
            "warning_codes": [
                warning.get("code", "")
                for warning in normalized_record.get("normalizer_warnings", [])
                if isinstance(warning, dict)
            ],
        }
        compact_groups.append(
            {
                "document_group_id": group_id,
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
                "normalized_record": compact_normalized,
                "block_samples": [
                    {
                        "block_ref": ref,
                        "page": block_index.get(ref, {}).get("page"),
                        "node1a_label": block_index.get(ref, {}).get("node1a_label"),
                        "content_role": block_index.get(ref, {}).get("content_role"),
                        "visual_form": block_index.get(ref, {}).get("visual_form"),
                        "text_preview": str(block_index.get(ref, {}).get("text", "")).replace("\n", " ")[:80],
                    }
                    for ref in refs[:10]
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
                "text_preview": str(block_index.get(ref, {}).get("text", "")).replace("\n", " ")[:80],
            }
            for ref, group_ids in sorted(overlaps.items())
        ],
    }


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
        timeout=300,
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


def validate_graph(graph: dict[str, Any], *, doc_id: str, group_ids: set[str], block_refs: set[str], prompt_version: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if graph.get("schema") != "group_projection_graph_v0.1":
        errors.append({"path": "$.schema", "message": "invalid schema"})
    if graph.get("doc_id") != doc_id:
        errors.append({"path": "$.doc_id", "message": "doc_id mismatch"})
    if graph.get("prompt_version") != prompt_version:
        errors.append({"path": "$.prompt_version", "message": "prompt_version mismatch"})
    seen_nodes = set()
    for index, node in enumerate(graph.get("nodes", [])):
        group_id = node.get("document_group_id")
        seen_nodes.add(group_id)
        if group_id not in group_ids:
            errors.append({"path": f"$.nodes[{index}].document_group_id", "message": "unknown group id"})
        projection_target = str(node.get("projection_target_hint", "")).lower()
        if node.get("project_directly_to_question") is True and projection_target in {
            "stimulus_description",
            "knowledge_node",
            "do_not_project_directly",
            "needs_continuation",
        }:
            errors.append(
                {
                    "path": f"$.nodes[{index}].project_directly_to_question",
                    "message": f"projection_target_hint {projection_target!r} cannot be direct question",
                }
            )
        for ref in node.get("evidence_refs", []):
            if ref not in block_refs:
                errors.append({"path": f"$.nodes[{index}].evidence_refs", "message": f"unknown block ref {ref}"})
    missing_nodes = sorted(group_ids - seen_nodes)
    if missing_nodes:
        errors.append({"path": "$.nodes", "message": "missing node entries", "group_ids": missing_nodes})
    predicates = {"contains", "uses_context", "is_child_of", "shares_stimulus", "continues_on", "other"}
    for index, relation in enumerate(graph.get("relations", [])):
        if relation.get("subject_group_id") not in group_ids:
            errors.append({"path": f"$.relations[{index}].subject_group_id", "message": "unknown group id"})
        if relation.get("object_group_id") not in group_ids:
            errors.append({"path": f"$.relations[{index}].object_group_id", "message": "unknown group id"})
        if relation.get("predicate") not in predicates:
            errors.append({"path": f"$.relations[{index}].predicate", "message": "invalid predicate"})
        for ref in relation.get("evidence_refs", []):
            if ref not in block_refs:
                errors.append({"path": f"$.relations[{index}].evidence_refs", "message": f"unknown block ref {ref}"})
    for index, item in enumerate(graph.get("overlap_resolutions", [])):
        if item.get("block_ref") not in block_refs:
            errors.append({"path": f"$.overlap_resolutions[{index}].block_ref", "message": "unknown block ref"})
        if item.get("primary_owner_group_id") not in group_ids:
            errors.append({"path": f"$.overlap_resolutions[{index}].primary_owner_group_id", "message": "unknown group id"})
        for group_id in item.get("secondary_group_ids", []):
            if group_id not in group_ids:
                errors.append({"path": f"$.overlap_resolutions[{index}].secondary_group_ids", "message": "unknown group id"})
    return {"valid": not errors, "errors": errors}


def merge_graphs(graphs: list[dict[str, Any]], *, doc_id: str, prompt_version: str, merge_meta: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    relations: dict[tuple[Any, ...], dict[str, Any]] = {}
    overlaps: dict[str, dict[str, Any]] = {}
    issues: dict[tuple[Any, ...], dict[str, Any]] = {}

    for graph in graphs:
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("document_group_id"):
                nodes.setdefault(node["document_group_id"], node)
        for relation in graph.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            key = (
                relation.get("subject_group_id"),
                relation.get("predicate"),
                relation.get("object_group_id"),
                tuple(relation.get("evidence_refs") or []),
            )
            relations.setdefault(key, relation)
        for item in graph.get("overlap_resolutions") or []:
            if isinstance(item, dict) and item.get("block_ref"):
                overlaps.setdefault(item["block_ref"], item)
        for issue in graph.get("open_issues") or []:
            if isinstance(issue, dict):
                key = (issue.get("code"), issue.get("message"), tuple(issue.get("source_refs") or []))
                issues.setdefault(key, issue)
            elif isinstance(issue, str):
                issues.setdefault(("open_text", issue, ()), {"code": "open_text", "message": issue, "source_refs": []})

    return {
        "schema": "group_projection_graph_v0.1",
        "doc_id": doc_id,
        "prompt_version": prompt_version,
        "nodes": [nodes[key] for key in sorted(nodes, key=lambda value: group_sort_key({"document_group_id": value}))],
        "relations": list(relations.values()),
        "overlap_resolutions": list(overlaps.values()),
        "open_issues": list(issues.values()),
        "merge_meta": merge_meta,
    }


def render_review(summary: dict[str, Any], graph: dict[str, Any]) -> str:
    rows = []
    for node in graph.get("nodes", []):
        rows.append(
            "<tr>"
            f"<td>{node.get('document_group_id','')}</td>"
            f"<td>{node.get('semantic_role','')}</td>"
            f"<td>{node.get('projection_target_hint','')}</td>"
            f"<td>{node.get('project_directly_to_question')}</td>"
            f"<td>{node.get('reason','')}</td>"
            "</tr>"
        )
    rel_rows = []
    for rel in graph.get("relations", []):
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
    for item in graph.get("overlap_resolutions", []):
        overlap_rows.append(
            "<tr>"
            f"<td>{item.get('block_ref','')}</td>"
            f"<td>{item.get('primary_owner_group_id','')}</td>"
            f"<td>{', '.join(item.get('secondary_group_ids', []))}</td>"
            f"<td>{item.get('secondary_usage','')}</td>"
            f"<td>{item.get('reason','')}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Group Relation Resolver Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;line-height:1.5}}
table{{border-collapse:collapse;width:100%;margin:16px 0}}
td,th{{border:1px solid #ddd;padding:8px;vertical-align:top}}
th{{background:#f4f4f4}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
</style>
<h1>Group Relation Resolver Review</h1>
<p>doc_id=<code>{summary['doc_id']}</code>, valid=<code>{summary['validation']['valid']}</code>, fallback=<code>false</code></p>
<h2>Nodes</h2>
<table><thead><tr><th>group</th><th>semantic_role（语义角色）</th><th>projection_target_hint（投影目标建议）</th><th>direct question?</th><th>reason</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Relations</h2>
<table><thead><tr><th>subject</th><th>predicate</th><th>object</th><th>confidence</th><th>reason</th></tr></thead><tbody>{''.join(rel_rows)}</tbody></table>
<h2>Overlap Resolutions</h2>
<table><thead><tr><th>block_ref</th><th>primary owner</th><th>secondary groups</th><th>secondary usage</th><th>reason</th></tr></thead><tbody>{''.join(overlap_rows)}</tbody></table>
"""


def call_relation_model_for_groups(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    api_key: str,
    doc_id: str,
    groups: list[dict[str, Any]],
    normalized: list[dict[str, Any]],
    block_index: dict[str, dict[str, Any]],
    out_root: Path,
    prompt_version: str,
) -> dict[str, Any]:
    input_payload = compact_input(doc_id, groups, normalized, block_index)

    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            "doc_id": doc_id,
            "prompt_version": prompt_version,
        },
    )
    model_result = call_model(config, node, system_prompt, user_prompt, api_key)
    graph = model_result["parsed"]
    if graph is None:
        graph = {
            "schema": "group_projection_graph_v0.1",
            "doc_id": doc_id,
            "prompt_version": prompt_version,
            "nodes": [],
            "relations": [],
            "overlap_resolutions": [],
            "open_issues": [{"code": "parse_failed", "message": model_result["parse_error"], "source_refs": []}],
        }

    group_ids = {group["document_group_id"] for group in groups}
    block_refs = {ref for group in groups for ref in all_group_refs(group)}
    validation = validate_graph(graph, doc_id=doc_id, group_ids=group_ids, block_refs=block_refs, prompt_version=prompt_version)

    write_json(out_root / "relation_input.json", input_payload)
    write_text(out_root / "used_system_prompt.md", system_prompt)
    write_text(out_root / "used_user_prompt.md", user_prompt)
    write_json(out_root / "request_messages.full.local.json", model_result["request_body"])
    write_json(out_root / "raw_response.json", model_result["raw_response"])
    write_text(out_root / "raw_content.txt", model_result["raw_content"])
    write_json(out_root / "group_projection_graph.json", graph)
    write_json(out_root / "validation_report.json", validation)
    return {
        "graph": graph,
        "validation": validation,
        "parsed": model_result["parsed"] is not None,
        "latency_seconds": model_result["latency_seconds"],
        "finish_reason": (model_result["raw_response"].get("choices") or [{}])[0].get("finish_reason", ""),
        "usage": model_result["raw_response"].get("usage") or {},
        "out_dir": out_root,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"].get("node3_group_relation_resolver") or config["nodes"]["node3b_group_relation_resolver"]
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"))
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")

    document_groups_json = workspace_path(args.document_groups_json)
    node2_run = workspace_path(args.node2_run)
    node3_run = workspace_path(args.node3_run)
    groups_payload = read_json(document_groups_json)
    doc_id = args.doc_id or groups_payload["doc_id"]
    groups = load_group_records(document_groups_json)
    normalized = load_normalized_records(node3_run, doc_id)
    block_index = load_block_index(node2_run, doc_id)

    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    max_groups = args.max_groups_per_chunk
    overlap_groups = args.overlap_groups
    use_chunking = args.chunked or (max_groups > 0 and len(groups) > max_groups)
    chunk_records: list[dict[str, Any]] = []

    if use_chunking:
        chunks = make_group_chunks(groups, max_groups=max_groups, overlap_groups=overlap_groups)
        valid_graphs: list[dict[str, Any]] = []
        for index, chunk_groups in enumerate(chunks, start=1):
            label = chunk_label(chunk_groups, index)
            chunk_out = out_root / "chunks" / label
            result = call_relation_model_for_groups(
                config=config,
                node=node,
                api_key=api_key,
                doc_id=doc_id,
                groups=chunk_groups,
                normalized=normalized,
                block_index=block_index,
                out_root=chunk_out,
                prompt_version=node["prompt_version"],
            )
            chunk_record = {
                "chunk_id": label,
                "group_ids": [group["document_group_id"] for group in chunk_groups],
                "parsed": result["parsed"],
                "validation": result["validation"],
                "finish_reason": result["finish_reason"],
                "usage": result["usage"],
                "latency_seconds": result["latency_seconds"],
                "out_dir": rel_workspace(chunk_out),
            }
            chunk_records.append(chunk_record)
            if result["validation"]["valid"]:
                valid_graphs.append(result["graph"])
        graph = merge_graphs(
            valid_graphs,
            doc_id=doc_id,
            prompt_version=node["prompt_version"],
            merge_meta={
                "strategy": "page_order_group_chunks_with_overlap_v0.1",
                "max_groups_per_chunk": max_groups,
                "overlap_groups": overlap_groups,
                "source_chunk_count": len(chunks),
                "valid_chunk_count": len(valid_graphs),
                "chunk_records": chunk_records,
            },
        )
        group_ids = {group["document_group_id"] for group in groups}
        block_refs = {ref for group in groups for ref in all_group_refs(group)}
        validation = validate_graph(graph, doc_id=doc_id, group_ids=group_ids, block_refs=block_refs, prompt_version=node["prompt_version"])
        write_json(out_root / "chunk_records.json", chunk_records)
        write_json(out_root / "group_projection_graph.json", graph)
        write_json(out_root / "validation_report.json", validation)
    else:
        result = call_relation_model_for_groups(
            config=config,
            node=node,
            api_key=api_key,
            doc_id=doc_id,
            groups=groups,
            normalized=normalized,
            block_index=block_index,
            out_root=out_root,
            prompt_version=node["prompt_version"],
        )
        graph = result["graph"]
        validation = result["validation"]
        chunk_records = [
            {
                "chunk_id": "single_call",
                "group_ids": [group["document_group_id"] for group in groups],
                "parsed": result["parsed"],
                "validation": result["validation"],
                "finish_reason": result["finish_reason"],
                "usage": result["usage"],
                "latency_seconds": result["latency_seconds"],
                "out_dir": rel_workspace(out_root),
            }
        ]
    summary = {
        "schema": "group_relation_resolver.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node3_group_relation_resolver",
        "doc_id": doc_id,
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "document_groups_json": rel_workspace(document_groups_json),
        "node2_run": rel_workspace(node2_run),
        "node3_run": rel_workspace(node3_run),
        "out_dir": rel_workspace(out_root),
        "chunked": use_chunking,
        "chunk_count": len(chunk_records),
        "valid_chunk_count": sum(1 for record in chunk_records if record["validation"]["valid"]),
        "parsed": all(record["parsed"] for record in chunk_records),
        "validation": validation,
        "review_html": rel_workspace(out_root / "review.html"),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(summary, graph))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--document-groups-json", required=True)
    parser.add_argument("--node2-run", required=True)
    parser.add_argument("--node3-run", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--chunked", action="store_true")
    parser.add_argument("--max-groups-per-chunk", type=int, default=18)
    parser.add_argument("--overlap-groups", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
