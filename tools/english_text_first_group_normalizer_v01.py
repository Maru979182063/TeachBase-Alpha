from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any

from english_text_first_normalizer.common import (
    blocks_for_group,
    compact_group_input,
    load_block_index,
    read_json,
    rel_workspace,
    render_template,
    workspace_path,
    write_json,
    write_text,
)
from english_text_first_normalizer.contract import fallback_record, repair_protocol_shape, validate_record
from english_text_first_normalizer.model_api import call_model
from english_text_first_normalizer.render import render_review


def normalize_group(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    doc_id: str,
    group: dict[str, Any],
    blocks: list[dict[str, Any]],
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_doc,
) -> dict[str, Any]:
    group_id = group["document_group_id"]
    group_dir = out_doc / group_id
    input_payload = compact_group_input(doc_id, group, blocks)
    user_prompt = render_template(
        user_template,
        {
            "input_json": json.dumps(input_payload, ensure_ascii=False, indent=2),
            "doc_id": doc_id,
            "document_group_id": group_id,
            "prompt_version": node["prompt_version"],
        },
    )
    model_result = call_model(config, node, system_prompt, user_prompt, api_key)
    model_parsed = model_result["parsed"]
    parsed = model_parsed
    used_fallback = False
    used_protocol_repair = False
    model_validation = {"valid": False, "errors": [{"path": "$", "message": model_result["parse_error"]}], "warnings": []}

    if parsed is None:
        parsed = fallback_record(doc_id, group, node["prompt_version"], model_result["parse_error"], blocks)
        used_fallback = True
        validation = validate_record(parsed, doc_id=doc_id, group=group, prompt_version=node["prompt_version"])
    else:
        model_validation = validate_record(parsed, doc_id=doc_id, group=group, prompt_version=node["prompt_version"])
        repaired = repair_protocol_shape(parsed, group)
        used_protocol_repair = repaired != parsed
        parsed = repaired
        validation = validate_record(parsed, doc_id=doc_id, group=group, prompt_version=node["prompt_version"])
        if not validation["valid"]:
            parsed = fallback_record(doc_id, group, node["prompt_version"], "model output failed local validation after protocol repair", blocks)
            validation = validate_record(parsed, doc_id=doc_id, group=group, prompt_version=node["prompt_version"])
            used_fallback = True

    write_json(group_dir / "normalizer_input.json", input_payload)
    write_text(group_dir / "system_prompt.md", system_prompt)
    write_text(group_dir / "user_prompt.md", user_prompt)
    write_json(group_dir / "request_messages.full.local.json", model_result["request_body"])
    write_json(group_dir / "raw_response.json", model_result["raw_response"])
    write_text(group_dir / "raw_content.txt", model_result["raw_content"])
    if model_parsed is not None:
        write_json(group_dir / "model_parsed_output.json", model_parsed)
    write_json(group_dir / "model_validation_report.json", model_validation)
    write_json(group_dir / "normalized_group_record.json", parsed)
    write_json(group_dir / "validation_report.json", validation)

    return {
        "doc_id": doc_id,
        "document_group_id": group_id,
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "latency_seconds": model_result["latency_seconds"],
        "parsed": model_result["parsed"] is not None,
        "parse_error": model_result["parse_error"],
        "model_validation": model_validation,
        "validation": validation,
        "used_fallback": used_fallback,
        "used_protocol_repair": used_protocol_repair,
        "normalized_record": parsed,
        "artifact_paths": {
            "normalizer_input": rel_workspace(group_dir / "normalizer_input.json"),
            "raw_content": rel_workspace(group_dir / "raw_content.txt"),
            "model_parsed_output": rel_workspace(group_dir / "model_parsed_output.json") if model_parsed is not None else "",
            "model_validation_report": rel_workspace(group_dir / "model_validation_report.json"),
            "normalized_group_record": rel_workspace(group_dir / "normalized_group_record.json"),
            "validation_report": rel_workspace(group_dir / "validation_report.json"),
        },
        "usage": model_result["raw_response"].get("usage", {}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node3_group_normalizer"]
    api_key = os.environ.get(config.get("api_key_env", "ARK_API_KEY"))
    if not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')}")

    document_groups_path = workspace_path(args.document_groups_json)
    dedupe_payload = read_json(document_groups_path)
    doc_id = args.doc_id or dedupe_payload["doc_id"]
    node2_run = workspace_path(args.node2_run) if args.node2_run else workspace_path(dedupe_payload["source_node2_run"])
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    out_doc = out_root / doc_id

    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    block_index = load_block_index(node2_run, doc_id)

    selected_ids = set(args.group_ids or [])
    groups = dedupe_payload.get("document_groups", [])
    if selected_ids:
        groups = [group for group in groups if group.get("document_group_id") in selected_ids]
    if args.max_groups:
        groups = groups[: args.max_groups]

    records = []
    for group in groups:
        records.append(
            normalize_group(
                config=config,
                node=node,
                doc_id=doc_id,
                group=group,
                blocks=blocks_for_group(group, block_index),
                system_prompt=system_prompt,
                user_template=user_template,
                api_key=api_key,
                out_doc=out_doc,
            )
        )

    summary = {
        "schema": "english_text_first_group_normalizer.run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node3_group_normalizer",
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "document_groups_json": rel_workspace(document_groups_path),
        "node2_run": rel_workspace(node2_run),
        "out_dir": rel_workspace(out_root),
        "doc_id": doc_id,
        "groups_attempted": len(records),
        "groups_parsed": sum(1 for record in records if record["parsed"]),
        "groups_valid": sum(1 for record in records if record["validation"]["valid"]),
        "groups_fallback": sum(1 for record in records if record["used_fallback"]),
        "groups_protocol_repaired": sum(1 for record in records if record["used_protocol_repair"]),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        "review_html": rel_workspace(out_root / "review.html"),
    }
    write_json(out_root / "run_summary.json", summary)
    write_json(out_root / "used_config.json", config)
    write_text(out_root / "used_system_prompt.md", system_prompt)
    write_text(out_root / "used_user_prompt_template.md", user_template)
    write_text(out_root / "review.html", render_review(summary, records, block_index))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/english_text_first_v02.yaml")
    parser.add_argument("--document-groups-json", required=True)
    parser.add_argument("--node2-run", default="")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
