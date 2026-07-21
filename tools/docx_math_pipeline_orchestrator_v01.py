from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from docx_legacy_formula_recovery_v01 import safe_slug


DEFAULT_OUT_ROOT = Path("outputs/docx_math_pipeline_orchestrator_v0_1")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path.resolve())


def require_artifact(path: str | Path, label: str) -> Path:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Missing {label}: {target}")
    return target


def run_child(cmd: list[str], *, log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    result = subprocess.run(cmd, cwd=Path.cwd(), env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    payload = {
        "cmd": cmd,
        "returncode": result.returncode,
        "runtime_seconds": round(time.time() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    write_json(log_path, payload)
    if result.returncode != 0:
        raise RuntimeError(f"child command failed: {' '.join(cmd)}; see {log_path}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"child command did not return JSON: {' '.join(cmd)}; see {log_path}") from exc


def packets_to_membership_groups(packet_candidates_path: Path, out_path: Path) -> dict[str, Any]:
    packets = read_json(packet_candidates_path).get("packets") or []
    groups: list[dict[str, Any]] = []
    for index, packet in enumerate(packets, start=1):
        block_ids = [str(item) for item in packet.get("source_block_ids") or [] if str(item)]
        if not block_ids:
            continue
        group_id = str(packet.get("draft_id") or f"dq_{index:04d}")
        groups.append(
            {
                "group_id": group_id,
                "block_ids": block_ids,
                "start_block_id": block_ids[0],
                "end_block_id": block_ids[-1],
                "confidence": str(packet.get("confidence") or "unknown"),
                "source": "docx_question_grouper_v01.question_packet_candidates",
                "source_packet": {
                    "window_id": packet.get("window_id"),
                    "evidence_block_ids": packet.get("evidence_block_ids") or [],
                    "completion_status": packet.get("completion_status") or "unknown",
                },
            }
        )
    payload = {
        "schema_version": "docx_question_grouper_membership_groups.v0.1",
        "source_question_packet_candidates": rel(packet_candidates_path),
        "groups": groups,
        "ungrouped_block_ids": [],
    }
    write_json(out_path, payload)
    return payload


def copy_block_stream(paragraph_stream: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paragraph_stream, out_path)


def api_key_arg(args: argparse.Namespace) -> list[str]:
    if args.api_key:
        return ["--api-key", args.api_key]
    return []


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    docx_path = args.docx.resolve()
    doc_id = args.doc_id or safe_slug(docx_path.stem)
    run_id = args.run_id or f"{doc_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_root = Path(args.out_root)
    run_root = out_root / run_id
    if args.clean and run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    log_dir = run_root / "child_logs"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if args.api_key:
        env["ARK_API_KEY"] = args.api_key

    stage0 = run_child(
        [
            sys.executable,
            "tools/docx_native_stage0_router_v01.py",
            "--docx",
            str(docx_path),
            "--run-id",
            f"{run_id}__stage0_router",
            "--clean",
        ]
        + (["--mathml-node-module-dir", args.mathml_node_module_dir] if args.mathml_node_module_dir else []),
        log_path=log_dir / "01_stage0_router.json",
        env=env,
    )
    paragraph_stream = require_artifact((stage0.get("artifacts") or {}).get("stage0_paragraph_stream", ""), "stage0 paragraph stream")

    tagger = run_child(
        [
            sys.executable,
            "tools/docx_native_block_tagger_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--run-id",
            f"{run_id}__block_tagger",
            "--max-workers",
            str(args.tagger_workers),
            "--timeout",
            str(args.tagger_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "02_block_tagger.json",
        env=env,
    )
    block_tags = require_artifact((tagger.get("artifacts") or {}).get("block_tags", ""), "block tags")

    grouper = run_child(
        [
            sys.executable,
            "tools/docx_question_grouper_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--block-tags",
            str(block_tags),
            "--run-id",
            f"{run_id}__question_grouper",
            "--doc-id",
            doc_id,
            "--max-workers",
            str(args.grouper_workers),
            "--timeout",
            str(args.grouper_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "03_question_grouper.json",
        env=env,
    )
    packet_candidates = require_artifact((grouper.get("artifacts") or {}).get("question_packet_candidates", ""), "question packet candidates")

    membership_root = run_root / "membership"
    membership_path = membership_root / doc_id / "full_doc_membership" / "membership_groups.json"
    membership = packets_to_membership_groups(packet_candidates, membership_path)

    normalizer = run_child(
        [
            sys.executable,
            "tools/docx_question_part_normalizer_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--block-tags",
            str(block_tags),
            "--membership-groups",
            str(membership_path),
            "--run-id",
            f"{run_id}__part_normalizer",
            "--doc-id",
            doc_id,
            "--solution-policy-hint",
            args.solution_policy_hint,
            "--concurrency",
            str(args.normalizer_workers),
            "--timeout",
            str(args.normalizer_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "04_part_normalizer.json",
        env=env,
    )
    part_root = Path("outputs/docx_question_part_normalizer_v0_1") / f"{run_id}__part_normalizer"

    block_stream_root = run_root / "block_streams"
    copy_block_stream(paragraph_stream, block_stream_root / doc_id / "immutable_block_stream.json")

    draft_root = Path("outputs/docx_math_source_backed_draft_builder_v0_1") / f"{run_id}__draft_builder"
    builder = run_child(
        [
            sys.executable,
            "tools/docx_math_source_backed_draft_builder_v01.py",
            "--part-root",
            str(part_root),
            "--block-stream-root",
            str(block_stream_root),
            "--membership-root",
            str(membership_root),
            "--out-root",
            str(draft_root),
        ],
        log_path=log_dir / "05_draft_builder.json",
        env=env,
    )

    fullchain_run_id = f"{run_id}__fullchain"
    fullchain = run_child(
        [
            sys.executable,
            "tools/docx_math_fullchain_orchestrator_v01.py",
            "--input-draft-root",
            str(draft_root),
            "--run-id",
            fullchain_run_id,
            "--doc-id-contains",
            doc_id,
            "--normal-workers",
            str(args.refiner_workers),
            "--long-workers",
            str(args.long_refiner_workers),
            "--max-retry-rounds",
            str(args.max_retry_rounds),
            "--retry-failed",
        ]
        + api_key_arg(args),
        log_path=log_dir / "06_fullchain_refiner.json",
        env=env,
    )
    fullchain_dir = Path("outputs/docx_math_fullchain_orchestrator_v0_1") / fullchain_run_id

    side_by_side: dict[str, Any] | None = None
    if not args.skip_side_by_side:
        side_by_side = run_child(
            [
                sys.executable,
                "tools/docx_math_build_side_by_side_review_v01.py",
                "--run-id",
                f"{run_id}__side_by_side",
                "--run-dirs",
                str(fullchain_dir),
                "--block-stream-root",
                str(block_stream_root),
                "--zip",
            ]
            + (["--force-render"] if args.force_render else []),
            log_path=log_dir / "07_side_by_side.json",
            env=env,
        )

    summary = {
        "schema_version": "docx_math_pipeline_orchestrator_run.v0.1",
        "run_id": run_id,
        "doc_id": doc_id,
        "source_docx": str(docx_path),
        "status": "ok" if int(fullchain.get("blocked_count") or 0) == 0 else "needs_review",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "nodes": {
            "stage0_router": stage0,
            "block_tagger": tagger,
            "question_grouper": grouper,
            "membership_adapter": {
                "membership_group_count": len(membership.get("groups") or []),
                "membership_groups": rel(membership_path),
            },
            "part_normalizer": normalizer,
            "draft_builder": builder,
            "fullchain_refiner": fullchain,
            "side_by_side": side_by_side,
        },
        "artifacts": {
            "run_root": rel(run_root),
            "paragraph_stream": rel(paragraph_stream),
            "block_tags": rel(block_tags),
            "question_packet_candidates": rel(packet_candidates),
            "membership_groups": rel(membership_path),
            "draft_root": rel(draft_root),
            "fullchain_dir": rel(fullchain_dir),
            "final_packets": rel(fullchain_dir / "final_packets.json"),
            "fullchain_review": rel(fullchain_dir / "review.html"),
            "side_by_side_index": (side_by_side or {}).get("index_html", ""),
            "side_by_side_zip": (side_by_side or {}).get("zip_path", ""),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(run_root / "pipeline_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DOCX native math pipeline from one .docx to refined packets.")
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--mathml-node-module-dir", default="")
    parser.add_argument("--solution-policy-hint", default="required", choices=["required", "optional", "absent_expected", "unknown"])
    parser.add_argument("--tagger-workers", type=int, default=6)
    parser.add_argument("--grouper-workers", type=int, default=6)
    parser.add_argument("--normalizer-workers", type=int, default=6)
    parser.add_argument("--refiner-workers", type=int, default=6)
    parser.add_argument("--long-refiner-workers", type=int, default=3)
    parser.add_argument("--tagger-timeout", type=int, default=150)
    parser.add_argument("--grouper-timeout", type=int, default=240)
    parser.add_argument("--normalizer-timeout", type=int, default=240)
    parser.add_argument("--max-retry-rounds", type=int, default=3)
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--skip-side-by-side", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
