from __future__ import annotations

import argparse
import concurrent.futures
import html
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "outputs" / "docx_math_refine_gate_repair_orchestrator_v0_1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REF = load_module("docx_math_question_refiner_v01", ROOT / "tools" / "docx_math_question_refiner_v01.py")
SPAN = load_module("docx_math_span_patch_refiner_v01", ROOT / "tools" / "docx_math_span_patch_refiner_v01.py")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def run_child(cmd: list[str], log_path: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    write_json(
        log_path,
        {
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    if result.returncode != 0:
        raise RuntimeError(f"child command failed; see {log_path}")
    if result.stdout is None:
        raise RuntimeError(f"child command produced no stdout; see {log_path}")
    return json.loads(result.stdout)


def packet_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("refined_packets") or payload.get("packets") or [])


def load_packets(refiner_run_id: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "outputs" / "docx_math_question_refiner_v0_1" / refiner_run_id / "refined_question_packets.json"
    payload = read_json(path)
    return {str(packet.get("source_group_id")): packet for packet in packet_list(payload)}


def draft_by_group(input_draft_root: Path, doc_ids: set[str], doc_id_contains: list[str], group_ids: set[str]) -> dict[str, dict[str, Any]]:
    drafts = REF.load_drafts(input_draft_root, doc_ids, doc_id_contains, group_ids)
    return {str(draft.get("source_group_id")): draft for draft in drafts}


def validation_prompt_version(packet: dict[str, Any], default_prompt_version: str) -> str:
    return str(packet.get("prompt_version") or default_prompt_version)


def repair_one(
    *,
    config: dict[str, Any],
    node: dict[str, Any],
    draft: dict[str, Any],
    packet: dict[str, Any],
    system_prompt: str,
    user_template: str,
    api_key: str,
    out_dir: Path,
    max_repair_rounds: int,
) -> dict[str, Any]:
    group_id = str(draft.get("source_group_id") or packet.get("source_group_id") or "")
    draft_id = str(draft.get("draft_id") or packet.get("source_draft_id") or "")
    item_dir = out_dir / "items" / group_id
    write_json(item_dir / "input_draft.json", draft)
    write_json(item_dir / "input_refined_packet.json", packet)

    repaired = json.loads(json.dumps(packet, ensure_ascii=False))
    pre_validation_source_restores = REF.restore_source_field_assets(repaired, draft)
    q = repaired.get("standard_question") or {}
    q["render_markdown"] = REF.canonical_render_markdown(q)
    initial_validation = REF.validate_refined(repaired, draft, validation_prompt_version(repaired, node["prompt_version"]))
    initial_tasks = SPAN.field_risk_tasks(repaired)
    write_json(
        item_dir / "initial_gate_report.json",
        {
            "validation": initial_validation,
            "span_tasks": initial_tasks,
            "pre_validation_source_restores": pre_validation_source_restores,
        },
    )

    model_called_count = 0
    parsed_ok_count = 0
    total_usage: dict[str, int] = {}
    patch_results: list[dict[str, Any]] = []
    current_validation = initial_validation
    current_tasks = initial_tasks

    for round_index in range(1, max(1, int(max_repair_rounds or 1)) + 1):
        should_repair = bool(current_tasks) or not current_validation.get("valid") or repaired.get("refine_status") != "REFINED_READY"
        if not should_repair:
            break
        if not current_tasks:
            patch_results.append(
                {
                    "round": round_index,
                    "applied": [],
                    "rejected": [],
                    "unresolved": [{"reason": "gate_failed_without_span_tasks"}],
                }
            )
            break

        patch_input = SPAN.build_patch_input(draft, repaired, current_tasks)
        user_prompt = SPAN.render_template(
            user_template,
            {
                "input_json": json.dumps(patch_input, ensure_ascii=False, indent=2),
                "draft_id": draft_id,
                "source_group_id": group_id,
            },
        )
        model_result = SPAN.call_patch_model(config, node, system_prompt, user_prompt, api_key)
        model_called_count += 1
        if model_result["parsed"] is not None:
            parsed_ok_count += 1
        for key, value in (model_result["raw_response"].get("usage") or {}).items():
            if isinstance(value, int):
                total_usage[key] = total_usage.get(key, 0) + value

        round_prefix = f"round_{round_index:02d}"
        write_json(item_dir / f"{round_prefix}_span_model_input.json", patch_input)
        write_text(item_dir / "used_system_prompt.md", system_prompt)
        write_text(item_dir / f"{round_prefix}_used_user_prompt.md", user_prompt)
        write_json(item_dir / f"{round_prefix}_request_messages.full.local.json", model_result["request_body"])
        write_json(item_dir / f"{round_prefix}_raw_response.json", model_result["raw_response"])
        write_text(item_dir / f"{round_prefix}_raw_content.txt", model_result["raw_content"])
        write_json(item_dir / f"{round_prefix}_parsed_patch_actions.json", model_result["parsed"] or {"parse_error": model_result["parse_error"]})
        if round_index == 1:
            write_json(item_dir / "span_model_input.json", patch_input)
            write_text(item_dir / "used_user_prompt.md", user_prompt)
            write_json(item_dir / "request_messages.full.local.json", model_result["request_body"])
            write_json(item_dir / "raw_response.json", model_result["raw_response"])
            write_text(item_dir / "raw_content.txt", model_result["raw_content"])
            write_json(item_dir / "parsed_patch_actions.json", model_result["parsed"] or {"parse_error": model_result["parse_error"]})

        patch_result = SPAN.apply_patches(repaired, model_result["parsed"], current_tasks)
        patch_result["round"] = round_index
        patch_results.append(patch_result)

        q = repaired.get("standard_question") or {}
        REF.restore_source_field_assets(repaired, draft)
        q["render_markdown"] = REF.canonical_render_markdown(q)
        REF.apply_latex_json_escape_gate(repaired)
        REF.apply_solution_policy_gate(repaired)
        repaired["status_breakdown"] = REF.compute_status(repaired)
        current_validation = REF.validate_refined(repaired, draft, validation_prompt_version(repaired, node["prompt_version"]))
        current_tasks = SPAN.field_risk_tasks(repaired)
        write_json(
            item_dir / f"{round_prefix}_gate_report.json",
            {"validation": current_validation, "span_tasks": current_tasks, "patch_application": patch_result},
        )
        if current_validation.get("valid"):
            break

    patch_result = {
        "applied": [item for result in patch_results for item in result.get("applied") or []],
        "rejected": [item for result in patch_results for item in result.get("rejected") or []],
        "unresolved": [item for result in patch_results for item in result.get("unresolved") or []],
        "rounds": patch_results,
    }

    q = repaired.get("standard_question") or {}
    REF.restore_source_field_assets(repaired, draft)
    q["render_markdown"] = REF.canonical_render_markdown(q)
    repaired.setdefault("normalization_actions", []).append(
        {
            "action": "post_refine_gate_targeted_repair",
            "scope": "node4c_refine_gate_repair_orchestrator",
            "model_called": model_called_count > 0,
            "model_called_count": model_called_count,
            "initial_validation_valid": bool(initial_validation.get("valid")),
            "span_task_count": len(initial_tasks),
            "applied_patch_count": len(patch_result.get("applied") or []),
            "rejected_patch_count": len(patch_result.get("rejected") or []),
            "max_repair_rounds": max_repair_rounds,
        }
    )
    REF.apply_latex_json_escape_gate(repaired)
    REF.apply_solution_policy_gate(repaired)
    repaired["status_breakdown"] = REF.compute_status(repaired)
    final_validation = REF.validate_refined(repaired, draft, validation_prompt_version(repaired, node["prompt_version"]))
    if not final_validation.get("valid"):
        repaired["refine_status"] = "REFINED_NEEDS_REVIEW"
        repaired["status_breakdown"] = REF.compute_status(repaired)

    write_json(item_dir / "patch_application_report.json", patch_result)
    write_json(item_dir / "final_gate_report.json", final_validation)
    write_json(item_dir / "refined_question_packet.json", repaired)
    return {
        "source_group_id": group_id,
        "draft_id": draft_id,
        "initial_valid": bool(initial_validation.get("valid")),
        "initial_error_codes": [err.get("code") or err.get("message") for err in initial_validation.get("errors") or []],
        "span_task_count": len(initial_tasks),
        "targeted_repair_called": model_called_count > 0,
        "targeted_repair_call_count": model_called_count,
        "parsed": parsed_ok_count > 0,
        "parsed_count": parsed_ok_count,
        "applied_patch_count": len(patch_result.get("applied") or []),
        "rejected_patch_count": len(patch_result.get("rejected") or []),
        "final_valid": bool(final_validation.get("valid")),
        "final_error_codes": [err.get("code") or err.get("message") for err in final_validation.get("errors") or []],
        "refine_status": repaired.get("refine_status"),
        "artifact_path": rel(item_dir / "refined_question_packet.json"),
        "usage": total_usage,
    }


def render_review(records: list[dict[str, Any]], packets: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    cards: list[str] = []
    packet_by_group = {str(packet.get("source_group_id")): packet for packet in packets}
    for record in records:
        packet = packet_by_group.get(str(record.get("source_group_id"))) or {}
        q = packet.get("standard_question") or {}
        cards.append(
            f"""
<article>
<h2>{record.get('source_group_id')} <small>{record.get('refine_status')}</small></h2>
<p>initial_valid={record.get('initial_valid')} · tasks={record.get('span_task_count')} · targeted_repair={record.get('targeted_repair_called')} · applied={record.get('applied_patch_count')} · final_valid={record.get('final_valid')}</p>
<pre>{html.escape(str(q.get('render_markdown') or ''))}</pre>
<details><summary>packet</summary><pre>{html.escape(json.dumps(packet, ensure_ascii=False, indent=2))}</pre></details>
</article>
"""
        )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>DOCX Math Refine Gate Repair Review</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;background:#eef2f7;color:#111827;line-height:1.5}}
article{{background:white;border:1px solid #d5deea;border-radius:8px;padding:16px;margin:14px 0}}
pre{{white-space:pre-wrap;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px}}
small{{color:#52627a}}
</style>
<h1>DOCX Math Refine Gate Repair Review</h1>
<p>run={html.escape(summary['run_id'])} drafts={summary['draft_count']} targeted={summary['targeted_repair_called_count']}</p>
{''.join(cards)}
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_draft_root = (ROOT / args.input_draft_root).resolve() if not Path(args.input_draft_root).is_absolute() else Path(args.input_draft_root)
    out_dir = OUT_ROOT / args.run_id
    api_key = args.api_key or os.environ.get("ARK_API_KEY", "")
    if not api_key:
        raise SystemExit("missing ARK_API_KEY or --api-key")
    os.environ["ARK_API_KEY"] = api_key

    refiner_run_id = args.refiner_run_id or f"{args.run_id}_node4_refiner"
    if not args.skip_refiner:
        cmd = [
            sys.executable,
            "tools/docx_math_question_refiner_v01.py",
            "--input-draft-root",
            str(input_draft_root),
            "--run-id",
            refiner_run_id,
            "--max-workers",
            str(args.max_workers),
        ]
        if args.doc_id_contains:
            cmd.append("--doc-id-contains")
            cmd.extend(args.doc_id_contains)
        if args.group_ids:
            cmd.append("--group-ids")
            cmd.extend(args.group_ids)
        refiner_summary = run_child(cmd, out_dir / "logs" / "node4_question_refiner.json")
    else:
        refiner_summary = read_json(ROOT / "outputs" / "docx_math_question_refiner_v0_1" / refiner_run_id / "run_summary.json")

    packets_by_group = load_packets(refiner_run_id)
    drafts_by_group = draft_by_group(input_draft_root, set(args.doc_ids or []), args.doc_id_contains or [], set(args.group_ids or []))
    config = read_json(ROOT / args.span_config)
    node = config["nodes"]["node4b_span_patch_refiner"]
    system_prompt = (ROOT / node["system_prompt_path"]).read_text(encoding="utf-8")
    user_template = (ROOT / node["user_prompt_path"]).read_text(encoding="utf-8")

    group_ids = list(args.group_ids or packets_by_group.keys())
    records: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.max_workers or 1))) as executor:
        futures = []
        for group_id in group_ids:
            draft = drafts_by_group.get(group_id)
            packet = packets_by_group.get(group_id)
            if not draft or not packet:
                continue
            futures.append(
                executor.submit(
                    repair_one,
                    config=config,
                    node=node,
                    draft=draft,
                    packet=packet,
                    system_prompt=system_prompt,
                    user_template=user_template,
                    api_key=api_key,
                    out_dir=out_dir,
                    max_repair_rounds=args.max_repair_rounds,
                )
            )
        for future in concurrent.futures.as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: item["source_group_id"])
    for record in records:
        packets.append(read_json(ROOT / record["artifact_path"]))

    summary = {
        "schema": "docx_math_refine_gate_repair_orchestrator.run_summary",
        "run_id": args.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_draft_root": rel(input_draft_root),
        "refiner_run_id": refiner_run_id,
        "refiner_summary": refiner_summary,
        "records": records,
        "draft_count": len(records),
        "initial_valid_count": sum(1 for record in records if record.get("initial_valid")),
        "targeted_repair_called_count": sum(1 for record in records if record.get("targeted_repair_called")),
        "targeted_repair_total_call_count": sum(int(record.get("targeted_repair_call_count") or 0) for record in records),
        "max_repair_rounds": args.max_repair_rounds,
        "final_valid_count": sum(1 for record in records if record.get("final_valid")),
        "refined_ready_count": sum(1 for packet in packets if packet.get("refine_status") == "REFINED_READY"),
        "total_tokens": sum(int((record.get("usage") or {}).get("total_tokens") or 0) for record in records),
        "refined_packets_json": rel(out_dir / "refined_question_packets.json"),
        "review_html": rel(out_dir / "review.html"),
    }
    write_json(out_dir / "run_summary.json", summary)
    write_json(out_dir / "refined_question_packets.json", {"schema": "docx_math_refine_gate_repair_packets_v0.1", "packets": packets, "summary": summary})
    write_text(out_dir / "review.html", render_review(records, packets, summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-draft-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-ids", nargs="*", default=[])
    parser.add_argument("--doc-id-contains", nargs="*", default=[])
    parser.add_argument("--group-ids", nargs="*", default=[])
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--span-config", default="config/docx_math_span_patch_refiner_v01.yaml")
    parser.add_argument("--refiner-run-id", default="")
    parser.add_argument("--skip-refiner", action="store_true")
    parser.add_argument("--max-repair-rounds", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
