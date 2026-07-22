from __future__ import annotations

import argparse
import concurrent.futures
import html
import importlib.util
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "docx_math_span_patch_actions_v0.2"


def load_refiner_module():
    path = ROOT / "tools" / "docx_math_question_refiner_v01.py"
    spec = importlib.util.spec_from_file_location("docx_math_question_refiner_v01", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REF = load_refiner_module()


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_json(path: Path) -> Any:
    return REF.read_json(path)


def write_json(path: Path, payload: Any) -> None:
    REF.write_json(path, payload)


def write_text(path: Path, text: str) -> None:
    REF.write_text(path, text)


def safe_name(value: str) -> str:
    return REF.safe_name(value)


def render_template(text: str, values: dict[str, Any]) -> str:
    return REF.render_template(text, values)


def load_drafts(input_root: Path, doc_ids: set[str], doc_id_contains: list[str], group_ids: set[str]) -> list[dict[str, Any]]:
    return REF.load_drafts(input_root, doc_ids, doc_id_contains, group_ids)


def q_fields(packet: dict[str, Any]) -> dict[str, str]:
    q = packet.get("standard_question") or {}
    return {
        "standard_question.stem_md": str(q.get("stem_md") or ""),
        "standard_question.answer_md": str(q.get("answer_md") or ""),
        "standard_question.explanation_md": str(q.get("explanation_md") or ""),
        "standard_question.teaching_note_md": str(q.get("teaching_note_md") or ""),
        "standard_question.context_md": str(q.get("context_md") or ""),
    }


def set_q_field(packet: dict[str, Any], field_path: str, value: str) -> bool:
    if not field_path.startswith("standard_question."):
        return False
    key = field_path.split(".", 1)[1]
    q = packet.get("standard_question") or {}
    if key not in q or not isinstance(q.get(key), str):
        return False
    q[key] = value
    return True


def risk_source_span(text: str, risk: dict[str, Any]) -> tuple[int, int, str]:
    start = risk.get("char_start")
    end = risk.get("char_end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        span = str(risk.get("source_span") or risk.get("span") or risk.get("match") or "")
        pos = text.find(span) if span else -1
        if pos >= 0:
            return pos, pos + len(span), span
        return 0, 0, ""

    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))

    left_dollar = text.rfind("$", 0, start + 1)
    right_dollar = text.find("$", end)
    if left_dollar >= 0 and right_dollar >= end and right_dollar - left_dollar <= 500:
        return left_dollar, right_dollar + 1, text[left_dollar : right_dollar + 1]

    window_start = max(0, start - 120)
    window_end = min(len(text), end + 120)
    return window_start, window_end, text[window_start:window_end]


def field_risk_tasks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for field_path, text in q_fields(packet).items():
        if not text.strip():
            continue
        field_name = field_path.split(".", 1)[1]
        risks = REF.formula_structural_risks(text, field_name=field_name, block_ids=[])
        for risk in risks:
            char_start, char_end, source_span = risk_source_span(text, risk)
            if not source_span:
                continue
            key = (field_path, char_start, char_end, source_span)
            item = merged.setdefault(
                key,
                {
                    "field_path": field_path,
                    "char_start": char_start,
                    "char_end": char_end,
                    "source_span": source_span,
                    "risk_codes": [],
                    "messages": [],
                    "suggested_actions": [],
                    "field_excerpt": text[max(0, char_start - 180) : min(len(text), char_end + 180)],
                },
            )
            if risk.get("risk_code") not in item["risk_codes"]:
                item["risk_codes"].append(risk.get("risk_code"))
            if risk.get("message") and risk.get("message") not in item["messages"]:
                item["messages"].append(risk.get("message"))
            if risk.get("suggested_action") and risk.get("suggested_action") not in item["suggested_actions"]:
                item["suggested_actions"].append(risk.get("suggested_action"))
    tasks = list(merged.values())
    tasks.sort(key=lambda item: (item["field_path"], item["char_start"], item["char_end"]))
    for index, task in enumerate(tasks, start=1):
        task["task_id"] = f"sp_{index:04d}"
    return tasks


def build_patch_input(draft: dict[str, Any], packet: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "draft_id": draft.get("draft_id"),
        "doc_id": draft.get("doc_id"),
        "source_group_id": draft.get("source_group_id"),
        "policy": {
            "patches_only": True,
            "no_full_field_rewrite": True,
            "no_cross_field_move": True,
            "must_preserve_numbers_and_meaning": True,
            "render_markdown_is_code_generated": True,
            "location_is_program_owned": True,
            "model_must_not_return_find_text": True,
        },
        "risky_spans": tasks,
    }


def call_patch_model(config: dict[str, Any], node: dict[str, Any], system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    started = time.time()
    result = REF.call_model(config, node, system_prompt, user_prompt, api_key)
    result["latency_seconds"] = round(time.time() - started, 3)
    return result


def apply_patches(packet: dict[str, Any], parsed: dict[str, Any] | None, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if not isinstance(parsed, dict) or parsed.get("schema") != SCHEMA:
        return {"applied": applied, "rejected": [{"code": "invalid_patch_schema"}]}
    task_by_id = {str(task.get("task_id")): task for task in tasks}
    patches = []
    for patch in parsed.get("patches") or []:
        if not isinstance(patch, dict):
            rejected.append({"code": "patch_not_object", "patch": patch})
            continue
        task_id = str(patch.get("task_id") or "")
        task = task_by_id.get(task_id)
        if not task:
            rejected.append({"code": "unknown_task_id", "task_id": task_id})
            continue
        replacement = str(patch.get("replacement_text") or "")
        if not replacement:
            rejected.append({"code": "missing_replacement_text", "task_id": task_id})
            continue
        patches.append((task, patch, replacement))

    patches.sort(key=lambda item: int(item[0].get("char_start") or 0), reverse=True)
    for task, patch, replacement in patches:
        task_id = str(task.get("task_id") or "")
        field_path = str(task.get("field_path") or "")
        source_span = str(task.get("source_span") or "")
        char_start = task.get("char_start")
        char_end = task.get("char_end")
        if not isinstance(char_start, int) or not isinstance(char_end, int) or char_end < char_start:
            rejected.append({"code": "invalid_task_offsets", "task_id": task_id})
            continue
        current = q_fields(packet).get(field_path)
        if current is None:
            rejected.append({"code": "unknown_field_path", "task_id": task_id, "field_path": field_path})
            continue
        if current[char_start:char_end] != source_span:
            rejected.append(
                {
                    "code": "source_span_offset_mismatch",
                    "task_id": task_id,
                    "field_path": field_path,
                    "expected_chars": len(source_span),
                    "actual_excerpt": current[char_start:char_end],
                }
            )
            continue
        updated = current[:char_start] + replacement + current[char_end:]
        if not set_q_field(packet, field_path, updated):
            rejected.append({"code": "field_update_failed", "task_id": task_id, "field_path": field_path})
            continue
        applied.append(
            {
                "task_id": task_id,
                "field_path": field_path,
                "risk_codes": task.get("risk_codes") or [],
                "source_chars": len(source_span),
                "replacement_chars": len(replacement),
                "confidence": patch.get("confidence"),
                "notes": patch.get("notes"),
            }
        )
    return {"applied": applied, "rejected": rejected, "unresolved": parsed.get("unresolved") or []}


def refine_one(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    draft: dict[str, Any],
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
) -> dict[str, Any]:
    draft_id = str(draft["draft_id"])
    draft_dir = out_dir / safe_name(str(draft.get("doc_id") or "")) / "drafts" / draft_id
    packet = REF.source_preserve_refined(
        draft,
        node["prompt_version"],
        "REFINED_READY",
        "Span patch baseline starts from source-backed draft.",
    )
    tasks = field_risk_tasks(packet)
    write_json(draft_dir / "input_draft.json", draft)
    write_json(draft_dir / "baseline_source_preserve_packet.json", packet)
    write_json(draft_dir / "span_tasks.json", tasks)
    model_called = False
    patch_result: dict[str, Any] = {"applied": [], "rejected": [], "unresolved": []}
    usage: dict[str, Any] = {}
    parsed_ok = False
    if tasks:
        model_called = True
        patch_input = build_patch_input(draft, packet, tasks)
        user_prompt = render_template(
            user_template,
            {
                "input_json": json.dumps(patch_input, ensure_ascii=False, indent=2),
                "draft_id": draft_id,
                "source_group_id": draft.get("source_group_id", ""),
            },
        )
        model_result = call_patch_model(config, node, system_prompt, user_prompt, api_key)
        parsed_ok = model_result["parsed"] is not None
        usage = model_result["raw_response"].get("usage", {})
        write_json(draft_dir / "span_model_input.json", patch_input)
        write_text(draft_dir / "used_system_prompt.md", system_prompt)
        write_text(draft_dir / "used_user_prompt.md", user_prompt)
        write_json(draft_dir / "request_messages.full.local.json", model_result["request_body"])
        write_json(draft_dir / "raw_response.json", model_result["raw_response"])
        write_text(draft_dir / "raw_content.txt", model_result["raw_content"])
        write_json(draft_dir / "parsed_patch_actions.json", model_result["parsed"] or {"parse_error": model_result["parse_error"]})
        patch_result = apply_patches(packet, model_result["parsed"], tasks)
    q = packet["standard_question"]
    q["render_markdown"] = REF.canonical_render_markdown(q)
    packet.setdefault("normalization_actions", []).append(
        {
            "action": "span_patch_refiner",
            "scope": "node4b_span_patch_refiner",
            "model_called": model_called,
            "applied_patch_count": len(patch_result.get("applied") or []),
            "rejected_patch_count": len(patch_result.get("rejected") or []),
        }
    )
    REF.apply_latex_json_escape_gate(packet)
    REF.apply_solution_policy_gate(packet)
    packet["status_breakdown"] = REF.compute_status(packet)
    validation = REF.validate_refined(packet, draft, node["prompt_version"])
    if not validation["valid"]:
        packet["refine_status"] = "REFINED_NEEDS_REVIEW"
        packet["status_breakdown"] = REF.compute_status(packet)
    write_json(draft_dir / "patch_application_report.json", patch_result)
    write_json(draft_dir / "refined_question_packet.json", packet)
    write_json(draft_dir / "validation_report.json", validation)
    return {
        "draft_id": draft_id,
        "source_group_id": draft.get("source_group_id"),
        "model_called": model_called,
        "parsed": parsed_ok,
        "task_count": len(tasks),
        "applied_patch_count": len(patch_result.get("applied") or []),
        "rejected_patch_count": len(patch_result.get("rejected") or []),
        "refine_status": packet.get("refine_status"),
        "projection_status": packet.get("status_breakdown", {}).get("projection_status", ""),
        "validation": validation,
        "artifact_path": rel(draft_dir / "refined_question_packet.json"),
        "usage": usage,
    }


def render_review(packets: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    cards = []
    for packet in packets:
        q = packet.get("standard_question") or {}
        cards.append(
            f"""
<article class="card">
<h2>{html.escape(str(packet.get('source_draft_id')))} <small>{html.escape(str(packet.get('refine_status')))} / {html.escape(str(packet.get('question_type')))}</small></h2>
<p>group=<code>{html.escape(str(packet.get('source_group_id')))}</code></p>
<h3>render_markdown</h3><pre>{html.escape(str(q.get('render_markdown') or ''))}</pre>
<details><summary>packet</summary><pre>{html.escape(json.dumps(packet, ensure_ascii=False, indent=2))}</pre></details>
</article>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Math Span Patch Refiner Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#f3f6fa;color:#111827;line-height:1.5}}
.card{{background:white;border:1px solid #d8dee9;border-radius:8px;padding:16px;margin:18px 0}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px;overflow:auto}}
code{{background:#eef2f7;padding:2px 5px;border-radius:4px}}
</style>
<h1>DOCX Math Span Patch Refiner Review</h1>
<p>run=<code>{html.escape(summary['run_id'])}</code> drafts=<code>{summary['draft_count']}</code> model_called=<code>{summary['model_called_count']}</code> applied=<code>{summary['applied_patch_count']}</code></p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = read_json(workspace_path(args.config))
    node = config["nodes"]["node4b_span_patch_refiner"]
    input_root = workspace_path(args.input_draft_root)
    out_root = workspace_path(config["owned_output_root"]) / args.run_id
    drafts = load_drafts(input_root, set(args.doc_ids or []), args.doc_id_contains or [], set(args.group_ids or []))
    if args.max_drafts:
        drafts = drafts[: args.max_drafts]
    system_prompt = workspace_path(node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = workspace_path(node["user_prompt_path"]).read_text(encoding="utf-8")
    api_key = args.api_key or os.environ.get(str(config.get("api_key_env") or "ARK_API_KEY"), "")
    if not args.prepare_only and not api_key:
        raise SystemExit(f"missing API key env {config.get('api_key_env', 'ARK_API_KEY')} or --api-key")

    if args.prepare_only:
        records = []
        for draft in drafts:
            packet = REF.source_preserve_refined(draft, node["prompt_version"], "REFINED_READY", "Span patch prepare baseline.")
            tasks = field_risk_tasks(packet)
            draft_dir = out_root / safe_name(str(draft.get("doc_id") or "")) / "drafts" / str(draft["draft_id"])
            write_json(draft_dir / "input_draft.json", draft)
            write_json(draft_dir / "baseline_source_preserve_packet.json", packet)
            write_json(draft_dir / "span_tasks.json", tasks)
            records.append({"draft_id": draft.get("draft_id"), "source_group_id": draft.get("source_group_id"), "task_count": len(tasks), "model_called": False})
        summary = {
            "schema": "docx_math_span_patch_refiner.prepare_summary",
            "run_id": args.run_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "node": "node4b_span_patch_refiner",
            "model": node["model"],
            "prompt_version": node["prompt_version"],
            "input_draft_root": rel(input_root),
            "out_dir": rel(out_root),
            "prepare_only": True,
            "draft_count": len(records),
            "records": records,
        }
        write_json(out_root / "prepare_summary.json", summary)
        return summary

    records: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                refine_one,
                config=config,
                node=node,
                draft=draft,
                system_prompt=system_prompt,
                user_template=user_template,
                api_key=api_key,
                out_dir=out_root,
            ): draft
            for draft in drafts
        }
        for future in concurrent.futures.as_completed(future_map):
            records.append(future.result())
    records.sort(key=lambda item: item["draft_id"])
    packets = [read_json(workspace_path(record["artifact_path"])) for record in records]
    summary = {
        "schema": "docx_math_span_patch_refiner.run_summary",
        "run_id": args.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node4b_span_patch_refiner",
        "model": node["model"],
        "prompt_version": node["prompt_version"],
        "input_draft_root": rel(input_root),
        "out_dir": rel(out_root),
        "records": records,
        "draft_count": len(records),
        "model_called_count": sum(1 for item in records if item.get("model_called")),
        "refined_ready_count": sum(1 for item in packets if item.get("refine_status") == "REFINED_READY"),
        "needs_review_count": sum(1 for item in packets if item.get("refine_status") == "REFINED_NEEDS_REVIEW"),
        "applied_patch_count": sum(int(item.get("applied_patch_count") or 0) for item in records),
        "rejected_patch_count": sum(int(item.get("rejected_patch_count") or 0) for item in records),
        "total_tokens": sum(int((item.get("usage") or {}).get("total_tokens") or 0) for item in records),
        "refined_packets_json": rel(out_root / "refined_question_packets.json"),
        "review_html": rel(out_root / "review.html"),
    }
    write_json(out_root / "refined_question_packets.json", {"schema": "docx_math_span_patch_packets_batch_v0.1", "packets": packets, "summary": summary})
    write_json(out_root / "run_summary.json", summary)
    write_text(out_root / "review.html", render_review(packets, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/docx_math_span_patch_refiner_v01.yaml")
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-ids", nargs="*", default=[])
    parser.add_argument("--doc-id-contains", nargs="*", default=[])
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--max-drafts", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
