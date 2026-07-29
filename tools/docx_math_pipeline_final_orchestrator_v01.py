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


DEFAULT_OUT_ROOT = Path("outputs/docx_math_pipeline_final_v0_1")


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


def redact_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_value = False
    for item in cmd:
        if skip_value:
            redacted.append("<redacted>")
            skip_value = False
            continue
        redacted.append(item)
        if item == "--api-key":
            skip_value = True
    return redacted


def run_child(cmd: list[str], *, log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    result = subprocess.run(cmd, cwd=Path.cwd(), env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    display_cmd = redact_command(cmd)
    payload = {
        "cmd": display_cmd,
        "returncode": result.returncode,
        "runtime_seconds": round(time.time() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    write_json(log_path, payload)
    if result.returncode != 0:
        raise RuntimeError(f"child command failed: {' '.join(display_cmd)}; see {log_path}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"child command did not return JSON: {' '.join(display_cmd)}; see {log_path}") from exc


def boundary_packets_to_membership_groups(assembled_packets_path: Path, out_path: Path) -> dict[str, Any]:
    packets = read_json(assembled_packets_path).get("packets") or []
    groups: list[dict[str, Any]] = []
    for index, packet in enumerate(packets, start=1):
        block_ids = [str(item) for item in packet.get("source_block_ids") or [] if str(item)]
        if not block_ids:
            continue
        group_id = str(packet.get("packet_id") or packet.get("draft_id") or f"dq_{index:04d}")
        groups.append(
            {
                "group_id": group_id,
                "block_ids": block_ids,
                "start_block_id": block_ids[0],
                "end_block_id": block_ids[-1],
                "confidence": str(packet.get("start_confidence") or "unknown"),
                "source": "docx_question_boundary_cutter_v01.assembled_packets",
                "source_packet": {
                    "packet_id": packet.get("packet_id"),
                    "question_start_block_id": packet.get("question_start_block_id"),
                    "start_vote_count": packet.get("start_vote_count"),
                    "start_confidence": packet.get("start_confidence"),
                    "start_windows": packet.get("start_windows") or [],
                    "start_evidence": packet.get("start_evidence") or "",
                },
            }
        )
    payload = {
        "schema_version": "docx_question_grouper_membership_groups.v0.1",
        "source_boundary_assembled_packets": rel(assembled_packets_path),
        "groups": groups,
        "ungrouped_block_ids": read_json(assembled_packets_path).get("unassigned_candidate_blocks") or [],
    }
    write_json(out_path, payload)
    return payload


def split_membership_by_complexity_routes(
    *,
    membership_path: Path,
    routes_path: Path,
    out_root: Path,
    doc_id: str,
) -> dict[str, Any]:
    membership = read_json(membership_path)
    groups = [group for group in membership.get("groups") or [] if isinstance(group, dict)]
    route_payload = read_json(routes_path)
    route_by_group_id = {str(item.get("group_id") or ""): str(item.get("route") or "") for item in route_payload.get("items") or []}
    normal_groups: list[dict[str, Any]] = []
    long_groups: list[dict[str, Any]] = []
    hard_fail_group_ids: list[str] = []
    for group in groups:
        group_id = str(group.get("group_id") or "")
        route = route_by_group_id.get(group_id, "normal_part_normalizer")
        if route == "hard_fail":
            hard_fail_group_ids.append(group_id)
        elif route == "long_part_normalizer":
            long_groups.append(group)
        else:
            normal_groups.append(group)
    if hard_fail_group_ids:
        raise RuntimeError(f"complexity router hard-fail groups must not enter normalizer: {hard_fail_group_ids}")

    def write_membership(name: str, selected: list[dict[str, Any]]) -> Path:
        path = out_root / doc_id / name / "membership_groups.json"
        payload = {
            "schema_version": "docx_question_grouper_membership_groups.v0.1",
            "source_membership_groups": rel(membership_path),
            "source_complexity_routes": rel(routes_path),
            "groups": selected,
            "ungrouped_block_ids": [],
        }
        write_json(path, payload)
        return path

    normal_path = write_membership("normal_membership", normal_groups)
    long_path = write_membership("long_membership", long_groups)
    summary = {
        "normal_group_count": len(normal_groups),
        "long_group_count": len(long_groups),
        "hard_fail_group_count": len(hard_fail_group_ids),
        "normal_membership_groups": rel(normal_path),
        "long_membership_groups": rel(long_path),
    }
    write_json(out_root / doc_id / "membership_split_summary.json", summary)
    return summary


def child_artifact(summary: dict[str, Any], key: str, label: str) -> Path:
    artifacts = summary.get("artifacts") or {}
    return require_artifact(artifacts.get(key, ""), label)


def stage0_handoff_path(stage0_summary: dict[str, Any]) -> Path | None:
    raw = (stage0_summary.get("artifacts") or {}).get("handoff_manifest", "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def should_stop_after_stage0(stage0_summary: dict[str, Any], args: argparse.Namespace) -> tuple[bool, dict[str, Any]]:
    handoff_path = stage0_handoff_path(stage0_summary)
    handoff = read_json(handoff_path) if handoff_path else {}
    contract = handoff.get("routing_contract") or {}
    status = str(handoff.get("status") or "")
    fallback_required = bool(contract.get("must_not_enter_native_block_tagger")) or status == "NEEDS_FORMULA_FALLBACK"
    policy = str(args.stage0_fallback_policy or "block")
    decision = {
        "policy": policy,
        "handoff_manifest": rel(handoff_path) if handoff_path else "",
        "handoff_status": status or "missing",
        "fallback_required": fallback_required,
        "required_next_action": contract.get("required_next_action", ""),
        "fallback_reasons": contract.get("fallback_reasons") or [],
        "fallback_jobs": handoff.get("fallback_jobs") or [],
    }
    return fallback_required and policy == "block", decision


def merge_part_normalizer_outputs(
    *,
    normal_summary: dict[str, Any],
    long_summary: dict[str, Any],
    membership_path: Path,
    out_root: Path,
    doc_id: str,
) -> dict[str, Any]:
    out_dir = out_root / doc_id / "question_part_normalization"
    group_order = {
        str(group.get("group_id") or ""): index
        for index, group in enumerate(read_json(membership_path).get("groups") or [])
        if isinstance(group, dict)
    }

    def load_items(summary: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        part_path = child_artifact(summary, "question_part_normalizations", f"{label} part normalizations")
        full_path = child_artifact(summary, "normalization_results_full", f"{label} full normalization results")
        issues_path = child_artifact(summary, "issues", f"{label} issues")
        return (
            [item for item in read_json(part_path).get("items") or [] if isinstance(item, dict)],
            [item for item in read_json(full_path).get("items") or [] if isinstance(item, dict)],
            [item for item in read_json(issues_path).get("issues") or [] if isinstance(item, dict)],
        )

    normal_items, normal_full, normal_issues = load_items(normal_summary, "normal")
    long_items, long_full, long_issues = load_items(long_summary, "long")

    def item_order(item: dict[str, Any]) -> int:
        return group_order.get(str(item.get("question_group_id") or ""), 10**9)

    merged_items = sorted(normal_items + long_items, key=item_order)
    merged_full = sorted(normal_full + long_full, key=item_order)
    merged_issues = normal_issues + long_issues
    write_json(out_dir / "question_part_normalizations.json", {"schema_version": "docx_question_part_normalizer_results.v0.1", "items": merged_items})
    write_json(out_dir / "normalization_results_full.json", {"schema_version": "docx_question_part_normalizer_full_results.v0.1", "items": merged_full})
    write_json(out_dir / "issues.json", {"schema_version": "docx_question_part_normalizer_issues.v0.1", "issues": merged_issues})
    blocking = [issue for issue in merged_issues if str(issue.get("severity") or "blocking") != "warning"]
    summary = {
        "schema_version": "docx_question_part_normalizer_merge_summary.v0.1",
        "status": "ok" if not blocking else "needs_resolution",
        "doc_id": doc_id,
        "normal_group_count": len(normal_items),
        "long_group_count": len(long_items),
        "merged_group_count": len(merged_items),
        "blocking_issue_count": len(blocking),
        "issue_count": len(merged_issues),
        "artifacts": {
            "question_part_normalizations": rel(out_dir / "question_part_normalizations.json"),
            "normalization_results_full": rel(out_dir / "normalization_results_full.json"),
            "issues": rel(out_dir / "issues.json"),
        },
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    write_json(out_dir / "summary.json", summary)
    if blocking:
        raise RuntimeError(f"merged part normalization has blocking issues: {len(blocking)}")
    return summary


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
    stop_after_stage0, stage0_gate = should_stop_after_stage0(stage0, args)
    if stop_after_stage0:
        summary = {
            "schema_version": "docx_math_pipeline_final_run.v0.1",
            "pipeline_id": "docx_math_pipeline_final_v01",
            "pipeline_name": "DOCX Math Native Final Pipeline",
            "run_id": run_id,
            "doc_id": doc_id,
            "source_docx": str(docx_path),
            "status": "blocked_stage0_formula_fallback_required",
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "nodes": {
                "stage0_router": stage0,
                "stage0_handoff_gate": stage0_gate,
            },
            "artifacts": {
                "run_root": rel(run_root),
                "stage0_router_summary": (stage0.get("artifacts") or {}).get("router_summary", ""),
                "stage0_handoff_manifest": stage0_gate.get("handoff_manifest", ""),
                "stage0_review": (stage0.get("artifacts") or {}).get("router_review", ""),
            },
            "runtime_import_enabled": False,
            "database_write_enabled": False,
        }
        write_json(run_root / "pipeline_summary.json", summary)
        return summary
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
    raw_block_tags = require_artifact((tagger.get("artifacts") or {}).get("block_tags", ""), "block tags")
    tagger_block_stream = require_artifact(raw_block_tags.parent / "immutable_block_stream.json", "tagger immutable block stream")

    asset_role_tagger = run_child(
        [
            sys.executable,
            "tools/docx_asset_role_visual_tagger_v01.py",
            "--paragraph-stream",
            str(tagger_block_stream),
            "--block-tags",
            str(raw_block_tags),
            "--run-id",
            f"{run_id}__asset_role_visual_tagger",
            "--doc-id",
            doc_id,
            "--config",
            "config/docx_asset_role_visual_tagger_v01.yaml",
            "--max-workers",
            str(args.asset_role_workers),
            "--timeout",
            str(args.asset_role_timeout),
            "--clean",
        ]
        + api_key_arg(args),
        log_path=log_dir / "02b_asset_role_visual_tagger.json",
        env=env,
    )
    block_tags = require_artifact((asset_role_tagger.get("artifacts") or {}).get("enhanced_block_tags", ""), "enhanced block tags")
    asset_role_map = require_artifact((asset_role_tagger.get("artifacts") or {}).get("asset_role_map", ""), "asset role map")

    boundary_cutter = run_child(
        [
            sys.executable,
            "tools/docx_question_boundary_cutter_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--block-tags",
            str(block_tags),
            "--run-id",
            f"{run_id}__question_boundary_cutter",
            "--doc-id",
            doc_id,
            "--max-workers",
            str(args.boundary_workers),
            "--timeout",
            str(args.boundary_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "03_question_boundary_cutter.json",
        env=env,
    )
    assembled_packets = require_artifact((boundary_cutter.get("artifacts") or {}).get("assembled_packets", ""), "boundary assembled packets")
    if int(boundary_cutter.get("unassigned_candidate_block_count") or 0) > 0:
        raise RuntimeError(
            f"boundary cutter left unassigned candidate blocks: {boundary_cutter.get('unassigned_candidate_block_count')}"
        )

    membership_root = run_root / "membership"
    membership_path = membership_root / doc_id / "full_doc_membership" / "membership_groups.json"
    membership = boundary_packets_to_membership_groups(assembled_packets, membership_path)

    complexity_router = run_child(
        [
            sys.executable,
            "tools/docx_question_complexity_router_v01.py",
            "--paragraph-stream",
            str(tagger_block_stream),
            "--block-tags",
            str(block_tags),
            "--membership-groups",
            str(membership_path),
            "--run-id",
            f"{run_id}__complexity_router",
            "--doc-id",
            doc_id,
            "--config",
            "config/docx_question_complexity_router_v01.yaml",
        ],
        log_path=log_dir / "04_complexity_router.json",
        env=env,
    )
    complexity_routes = require_artifact((complexity_router.get("artifacts") or {}).get("question_complexity_routes", ""), "question complexity routes")

    split_root = run_root / "membership_split"
    membership_split = split_membership_by_complexity_routes(
        membership_path=membership_path,
        routes_path=complexity_routes,
        out_root=split_root,
        doc_id=doc_id,
    )
    normal_membership_path = require_artifact(membership_split["normal_membership_groups"], "normal membership groups")
    long_membership_path = require_artifact(membership_split["long_membership_groups"], "long membership groups")

    normal_normalizer = run_child(
        [
            sys.executable,
            "tools/docx_question_part_normalizer_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--block-tags",
            str(block_tags),
            "--membership-groups",
            str(normal_membership_path),
            "--run-id",
            f"{run_id}__part_normalizer_normal",
            "--doc-id",
            doc_id,
            "--config",
            "config/docx_question_part_normalizer_v01.yaml",
            "--solution-policy-hint",
            args.solution_policy_hint,
            "--concurrency",
            str(args.normalizer_workers),
            "--timeout",
            str(args.normalizer_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "05a_part_normalizer_normal.json",
        env=env,
    )

    long_normalizer = run_child(
        [
            sys.executable,
            "tools/docx_question_part_long_normalizer_v01.py",
            "--paragraph-stream",
            str(paragraph_stream),
            "--block-tags",
            str(block_tags),
            "--membership-groups",
            str(long_membership_path),
            "--run-id",
            f"{run_id}__part_normalizer_long",
            "--doc-id",
            doc_id,
            "--config",
            "config/docx_question_part_long_normalizer_v01.yaml",
            "--solution-policy-hint",
            args.solution_policy_hint,
            "--concurrency",
            str(args.long_normalizer_workers),
            "--timeout",
            str(args.long_normalizer_timeout),
            "--no-resume",
        ]
        + api_key_arg(args),
        log_path=log_dir / "05b_part_normalizer_long.json",
        env=env,
    )

    part_root = Path("outputs/docx_question_part_normalizer_v0_1") / f"{run_id}__part_normalizer"
    part_merge = merge_part_normalizer_outputs(
        normal_summary=normal_normalizer,
        long_summary=long_normalizer,
        membership_path=membership_path,
        out_root=part_root,
        doc_id=doc_id,
    )

    block_stream_root = run_root / "block_streams"
    copy_block_stream(tagger_block_stream, block_stream_root / doc_id / "immutable_block_stream.json")

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
            "--block-tags",
            str(block_tags),
            "--asset-role-map",
            str(asset_role_map),
            "--out-root",
            str(draft_root),
        ],
        log_path=log_dir / "06_draft_builder.json",
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
        log_path=log_dir / "07_fullchain_refiner.json",
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
            log_path=log_dir / "08_side_by_side.json",
            env=env,
        )

    summary = {
        "schema_version": "docx_math_pipeline_final_run.v0.1",
        "pipeline_id": "docx_math_pipeline_final_v01",
        "pipeline_name": "DOCX Math Native Final Pipeline",
        "run_id": run_id,
        "doc_id": doc_id,
        "source_docx": str(docx_path),
        "status": "ok" if int(fullchain.get("blocked_count") or 0) == 0 else "needs_review",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "nodes": {
            "stage0_router": stage0,
            "stage0_handoff_gate": stage0_gate,
            "block_tagger": tagger,
            "asset_role_visual_tagger": asset_role_tagger,
            "question_boundary_cutter": boundary_cutter,
            "membership_adapter": {
                "membership_group_count": len(membership.get("groups") or []),
                "membership_groups": rel(membership_path),
                "source_boundary_assembled_packets": rel(assembled_packets),
            },
            "complexity_router": complexity_router,
            "membership_split": membership_split,
            "part_normalizer_normal": normal_normalizer,
            "part_normalizer_long": long_normalizer,
            "part_normalizer_merge": part_merge,
            "draft_builder": builder,
            "fullchain_refiner": fullchain,
            "side_by_side": side_by_side,
        },
        "artifacts": {
            "run_root": rel(run_root),
            "paragraph_stream": rel(paragraph_stream),
            "immutable_block_stream": rel(tagger_block_stream),
            "raw_block_tags": rel(raw_block_tags),
            "block_tags": rel(block_tags),
            "asset_role_map": rel(asset_role_map),
            "boundary_assembled_packets": rel(assembled_packets),
            "boundary_events": (boundary_cutter.get("artifacts") or {}).get("boundary_events", ""),
            "boundary_trace": (boundary_cutter.get("artifacts") or {}).get("boundary_trace", ""),
            "membership_groups": rel(membership_path),
            "question_complexity_routes": rel(complexity_routes),
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
    parser = argparse.ArgumentParser(description="Run isolated FINAL DOCX native math pipeline from one .docx to refined packets.")
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--mathml-node-module-dir", default="")
    parser.add_argument("--solution-policy-hint", default="required", choices=["required", "optional", "absent_expected", "unknown"])
    parser.add_argument("--tagger-workers", type=int, default=6)
    parser.add_argument("--asset-role-workers", type=int, default=4)
    parser.add_argument("--boundary-workers", type=int, default=6)
    parser.add_argument("--normalizer-workers", type=int, default=6)
    parser.add_argument("--long-normalizer-workers", type=int, default=3)
    parser.add_argument("--refiner-workers", type=int, default=6)
    parser.add_argument("--long-refiner-workers", type=int, default=3)
    parser.add_argument("--tagger-timeout", type=int, default=150)
    parser.add_argument("--asset-role-timeout", type=int, default=120)
    parser.add_argument("--boundary-timeout", type=int, default=240)
    parser.add_argument("--normalizer-timeout", type=int, default=240)
    parser.add_argument("--long-normalizer-timeout", type=int, default=300)
    parser.add_argument("--max-retry-rounds", type=int, default=3)
    parser.add_argument(
        "--stage0-fallback-policy",
        default="block",
        choices=["block", "allow"],
        help="block stops native downstream when Stage0 requires formula fallback; allow keeps the old unsafe behavior for diagnostics only.",
    )
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--skip-side-by-side", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
