#!/usr/bin/env python3
"""Checkpointed English DOCX chain runner from cut groups to parent/child review."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "english_docx_integrated_chain_v0_1"
REPAIR_CONFIG = ROOT / "config" / "english_docx_native_md" / "group_repair_gate_v01.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def resolve_rooted(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return ROOT / value


def repair_gate_output_dir(run_id: str, doc_id: str) -> Path:
    config = read_json(REPAIR_CONFIG)
    root = resolve_rooted(str(config.get("owned_output_root") or "outputs/english_docx_group_repair_gate_v0_1"))
    return root / run_id / doc_id


def run_command(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    log_dir: Path,
    force: bool,
    expected: Path,
) -> dict[str, Any]:
    started = time.time()
    checkpoint = log_dir / f"{name}.checkpoint.json"
    if expected.exists() and not force:
        result = {
            "name": name,
            "status": "skipped_existing",
            "expected": safe_rel(expected),
            "runtime_seconds": 0,
        }
        write_json(checkpoint, result)
        return result

    log_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(command, cwd=str(cwd), env=env, text=True, capture_output=True)
    (log_dir / f"{name}.stdout.txt").write_text(process.stdout, encoding="utf-8")
    (log_dir / f"{name}.stderr.txt").write_text(process.stderr, encoding="utf-8")
    result = {
        "name": name,
        "status": "ok" if process.returncode == 0 and expected.exists() else "failed",
        "returncode": process.returncode,
        "expected": safe_rel(expected),
        "runtime_seconds": round(time.time() - started, 3),
        "command": redact_command(command),
        "stdout_log": safe_rel(log_dir / f"{name}.stdout.txt"),
        "stderr_log": safe_rel(log_dir / f"{name}.stderr.txt"),
    }
    write_json(checkpoint, result)
    return result


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for token in command:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(token)
        if token in {"--api-key", "--key", "--token"}:
            skip_next = True
    return redacted


def normalizer_bad(summary_path: Path) -> tuple[bool, list[str]]:
    if not summary_path.exists():
        return True, ["normalizer_summary_missing"]
    summary = read_json(summary_path)
    reasons: list[str] = []
    if summary.get("status") != "ok":
        reasons.append(f"normalizer_status_{summary.get('status')}")
    if int(summary.get("issue_count") or 0) > 0:
        reasons.append(f"normalizer_issue_count_{summary.get('issue_count')}")
    if int(summary.get("needs_resolution_group_count") or 0) > 0:
        reasons.append(f"normalizer_needs_resolution_{summary.get('needs_resolution_group_count')}")
    return bool(reasons), reasons


def projection_bad(summary_path: Path) -> tuple[bool, list[str]]:
    if not summary_path.exists():
        return True, ["projection_summary_missing"]
    summary = read_json(summary_path)
    reasons: list[str] = []
    if int(summary.get("warning_count") or 0) > 0:
        reasons.append(f"projection_warning_count_{summary.get('warning_count')}")
    return bool(reasons), reasons


def run(args: argparse.Namespace) -> dict[str, Any]:
    doc_id = args.doc_id
    output_root = resolve_rooted(args.output_root)
    chain_dir = output_root / args.run_id / doc_id
    log_dir = chain_dir / "logs"
    checkpoint_path = chain_dir / "checkpoints.json"
    chain_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if args.api_key:
        env["ARK_API_KEY"] = args.api_key

    checkpoints: list[dict[str, Any]] = []
    repair_run_id = f"{args.run_id}_repair"
    repair_dir = repair_gate_output_dir(repair_run_id, doc_id)
    selected_groups = repair_dir / "selected_assembled_groups.json"
    repaired_groups = repair_dir / "repaired_assembled_groups.json"
    repair_summary_path = repair_dir / "summary.json"

    repair_cmd = [
        sys.executable,
        str(ROOT / "tools" / "english_docx_group_repair_gate_v01.py"),
        "--block-stream",
        str(args.block_stream),
        "--assembled-groups",
        str(args.assembled_groups),
        "--run-id",
        repair_run_id,
        "--doc-id",
        doc_id,
    ]
    if args.no_model:
        repair_cmd.append("--no-model")
    checkpoints.append(run_command(name="repair_gate", command=repair_cmd, cwd=ROOT, env=env, log_dir=log_dir, force=args.force, expected=selected_groups))
    write_json(checkpoint_path, {"doc_id": doc_id, "run_id": args.run_id, "checkpoints": checkpoints})
    if checkpoints[-1]["status"] == "failed":
        return finish(chain_dir, args, checkpoints, status="blocked_at_repair_gate", final_projection=None, fallback_events=["repair_gate_failed"])

    repair_summary = read_json(repair_summary_path) if repair_summary_path.exists() else {}
    selected_mode = str(repair_summary.get("selected_mode") or "")
    fallback_events = list(repair_summary.get("fallback_reasons") or [])
    normalizer_input = selected_groups

    selected_norm_dir = chain_dir / "field_normalizer_runs" / "selected" / doc_id
    selected_norm_summary = selected_norm_dir / "summary.json"
    selected_norm = selected_norm_dir / "normalized_groups.json"
    norm_cmd = [
        sys.executable,
        str(ROOT / "tools" / "english_docx_group_field_normalizer_v01.py"),
        "--block-stream",
        str(args.block_stream),
        "--assembled-groups",
        str(normalizer_input),
        "--run-id",
        "selected",
        "--doc-id",
        doc_id,
        "--out-root",
        str(chain_dir / "field_normalizer_runs"),
    ]
    if args.no_model:
        norm_cmd.append("--no-model")
    checkpoints.append(run_command(name="field_normalizer_selected", command=norm_cmd, cwd=ROOT, env=env, log_dir=log_dir, force=args.force, expected=selected_norm))
    write_json(checkpoint_path, {"doc_id": doc_id, "run_id": args.run_id, "checkpoints": checkpoints})
    if checkpoints[-1]["status"] == "failed":
        bad, reasons = True, ["field_normalizer_selected_failed"]
    else:
        bad, reasons = normalizer_bad(selected_norm_summary)

    final_norm = selected_norm
    final_norm_summary = selected_norm_summary
    final_norm_mode = "selected"
    if bad and selected_mode != "fallback_original_assembled":
        fallback_events.extend([f"selected_normalizer_bad:{reason}" for reason in reasons])
        fallback_norm_dir = chain_dir / "field_normalizer_runs" / "fallback_original" / doc_id
        fallback_norm_summary = fallback_norm_dir / "summary.json"
        fallback_norm = fallback_norm_dir / "normalized_groups.json"
        fallback_cmd = [
            sys.executable,
            str(ROOT / "tools" / "english_docx_group_field_normalizer_v01.py"),
            "--block-stream",
            str(args.block_stream),
            "--assembled-groups",
            str(args.assembled_groups),
            "--run-id",
            "fallback_original",
            "--doc-id",
            doc_id,
            "--out-root",
            str(chain_dir / "field_normalizer_runs"),
        ]
        if args.no_model:
            fallback_cmd.append("--no-model")
        checkpoints.append(run_command(name="field_normalizer_fallback_original", command=fallback_cmd, cwd=ROOT, env=env, log_dir=log_dir, force=args.force, expected=fallback_norm))
        write_json(checkpoint_path, {"doc_id": doc_id, "run_id": args.run_id, "checkpoints": checkpoints})
        fallback_bad, fallback_reasons = normalizer_bad(fallback_norm_summary)
        if checkpoints[-1]["status"] == "failed" or fallback_bad:
            fallback_events.extend([f"fallback_original_bad:{reason}" for reason in fallback_reasons])
            return finish(chain_dir, args, checkpoints, status="blocked_at_field_normalizer", final_projection=None, fallback_events=fallback_events)
        final_norm = fallback_norm
        final_norm_summary = fallback_norm_summary
        final_norm_mode = "fallback_original"
    elif bad:
        fallback_events.extend([f"normalizer_bad_after_repair_gate_original:{reason}" for reason in reasons])
        return finish(chain_dir, args, checkpoints, status="blocked_at_field_normalizer", final_projection=None, fallback_events=fallback_events)

    projection_dir = chain_dir / f"projection_{final_norm_mode}"
    projection_summary = projection_dir / "summary.json"
    projection_cmd = [
        sys.executable,
        str(ROOT / "tools" / "english_docx_parent_child_projection_v02.py"),
        "--input-normalized",
        str(final_norm),
        "--itemized",
        str(args.itemized),
        "--output-dir",
        str(projection_dir),
    ]
    checkpoints.append(run_command(name=f"parent_child_projection_{final_norm_mode}", command=projection_cmd, cwd=ROOT, env=env, log_dir=log_dir, force=args.force, expected=projection_summary))
    write_json(checkpoint_path, {"doc_id": doc_id, "run_id": args.run_id, "checkpoints": checkpoints})
    if checkpoints[-1]["status"] == "failed":
        return finish(chain_dir, args, checkpoints, status="blocked_at_projection", final_projection=None, fallback_events=fallback_events + ["projection_failed"])

    projection_has_issue, projection_reasons = projection_bad(projection_summary)
    if projection_has_issue:
        fallback_events.extend([f"projection_warning:{reason}" for reason in projection_reasons])
    status = "ok_with_projection_warnings" if projection_has_issue else "ok"
    return finish(
        chain_dir,
        args,
        checkpoints,
        status=status,
        final_projection=projection_dir / "index.html",
        fallback_events=fallback_events,
        extra={
            "repair_summary": safe_rel(repair_summary_path),
            "selected_assembled_groups": safe_rel(selected_groups),
            "repaired_assembled_groups": safe_rel(repaired_groups),
            "field_normalizer_summary": safe_rel(final_norm_summary),
            "normalized_groups": safe_rel(final_norm),
            "projection_summary": safe_rel(projection_summary),
        },
    )


def finish(
    chain_dir: Path,
    args: argparse.Namespace,
    checkpoints: list[dict[str, Any]],
    *,
    status: str,
    final_projection: Path | None,
    fallback_events: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = {
        "schema_version": "english_docx_integrated_chain_runner_summary.v0.1",
        "doc_id": args.doc_id,
        "run_id": args.run_id,
        "status": status,
        "fallback_events": fallback_events,
        "checkpoints": checkpoints,
        "artifacts": {
            "run_summary": safe_rel(chain_dir / "run_summary.json"),
            "checkpoints": safe_rel(chain_dir / "checkpoints.json"),
            "final_projection_html": safe_rel(final_projection) if final_projection else "",
            **(extra or {}),
        },
    }
    write_json(chain_dir / "run_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the protected English DOCX chain with checkpoints and fallback.")
    parser.add_argument("--block-stream", required=True, type=Path)
    parser.add_argument("--assembled-groups", required=True, type=Path)
    parser.add_argument("--itemized", required=True, type=Path)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
