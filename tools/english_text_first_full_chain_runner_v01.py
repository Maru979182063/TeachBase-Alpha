from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parents[1]
CONTROLLED_ROOT = WORKSPACE / "outputs/english_text_first_pipeline_v02_spec_20260715/controlled_runs"


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE / path


def rel_workspace(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def override_packet_family(input_json: Path, output_json: Path, family: str) -> dict[str, Any]:
    payload = read_json(input_json)
    candidates = payload.get("packet_candidates") if isinstance(payload, dict) else []
    changed = 0
    if isinstance(candidates, list):
        for packet in candidates:
            if not isinstance(packet, dict):
                continue
            if packet.get("projection_status") == "PRESERVED_NON_DIRECT":
                continue
            if str(packet.get("packet_family") or "").strip().lower() == family:
                continue
            packet["packet_family"] = family
            changed += 1
    payload.setdefault("experimental_overrides", []).append(
        {
            "kind": "packet_family_override",
            "family": family,
            "changed_count": changed,
            "note": "Sidecar experiment only; source refs and content are unchanged.",
        }
    )
    write_json(output_json, payload)
    return {"changed_count": changed, "output_json": rel_workspace(output_json)}


def copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def run_cmd(args: list[str], *, log_dir: Path, label: str) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=WORKSPACE,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    elapsed = round(time.time() - started, 3)
    (log_dir / f"{label}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (log_dir / f"{label}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    result = {
        "label": label,
        "command": [sys.executable, *args],
        "returncode": proc.returncode,
        "elapsed_seconds": elapsed,
    }
    write_json(log_dir / f"{label}.result.json", result)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {proc.returncode}; see {rel_workspace(log_dir)}")
    return result


def valid_node2_page(run_dir: Path, doc_id: str, page: int) -> bool:
    record_path = run_dir / doc_id / f"page_{page:03d}" / "record_manifest.json"
    if not record_path.exists():
        return False
    try:
        record = read_json(record_path)
    except Exception:
        return False
    return bool((record.get("validation") or {}).get("valid"))


def valid_node3_group(run_dir: Path, doc_id: str, group_id: str) -> bool:
    record_path = run_dir / doc_id / group_id / "normalized_group_record.json"
    validation_path = run_dir / doc_id / group_id / "validation_report.json"
    if not record_path.exists() or not validation_path.exists():
        return False
    try:
        validation = read_json(validation_path)
    except Exception:
        return False
    return bool(validation.get("valid"))


def merge_node2_shards(*, shard_run_dirs: list[Path], out_dir: Path, doc_id: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for shard in shard_run_dirs:
        summary_path = shard / "run_summary.json"
        if not summary_path.exists():
            continue
        summary = read_json(summary_path)
        records.extend(summary.get("records") or [])
        copy_tree_contents(shard / doc_id, out_dir / doc_id)
        for name in ("used_config.json", "used_system_prompt.md", "used_user_prompt_template.md"):
            src = shard / name
            dst = out_dir / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
    records.sort(key=lambda record: int(record.get("page_number") or 0))
    payload = {
        "schema": "english_text_first_sliding_window_composer.merged_run_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node2_sliding_window_composer",
        "out_dir": rel_workspace(out_dir),
        "model": records[0].get("model") if records else "",
        "prompt_version": records[0].get("prompt_version") if records else "",
        "windows_attempted": len(records),
        "windows_parsed": sum(1 for record in records if record.get("parsed")),
        "windows_valid": sum(1 for record in records if (record.get("validation") or {}).get("valid")),
        "windows_fallback": sum(1 for record in records if record.get("used_fallback")),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": records,
        "review_html": rel_workspace(out_dir / "review.html"),
    }
    write_json(out_dir / "run_summary.json", payload)
    return payload


def merge_node3_shards(*, shard_run_dirs: list[Path], out_dir: Path, doc_id: str, group_ids: list[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for shard in shard_run_dirs:
        summary_path = shard / "run_summary.json"
        if not summary_path.exists():
            continue
        summary = read_json(summary_path)
        records.extend(summary.get("records") or [])
        copy_tree_contents(shard / doc_id, out_dir / doc_id)
        for name in ("used_config.json", "used_system_prompt.md", "used_user_prompt_template.md"):
            src = shard / name
            dst = out_dir / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
    order = {gid: index for index, gid in enumerate(group_ids)}
    records.sort(key=lambda record: order.get(str(record.get("document_group_id") or ""), 10**9))
    payload = {
        "schema": "english_group_normalizer.run_summary.merged_sidecar",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node": "node3_group_normalizer",
        "doc_id": doc_id,
        "out_dir": rel_workspace(out_dir),
        "group_count": len(records),
        "valid_count": sum(1 for record in records if (record.get("validation") or {}).get("valid")),
        "runtime_import_enabled": False,
        "database_write_enabled": False,
        "records": [
            {
                "source_group_id": str(record.get("document_group_id") or ""),
                "merged_from_run": rel_workspace(Path(record.get("_merged_from_run", ""))) if record.get("_merged_from_run") else "",
            }
            for record in records
        ],
    }
    write_json(out_dir / "run_summary.json", payload)
    return payload


def node2_parallel(
    *,
    config: Path,
    doc_id: str,
    node1a_run: Path,
    node1b_run: Path,
    page_count: int,
    run_id: str,
    workers: int,
    logs: Path,
) -> Path:
    out_dir = CONTROLLED_ROOT / run_id
    shard_dirs: list[Path] = []
    tasks: list[tuple[int, str, Path]] = []
    for page in range(1, page_count + 1):
        shard_id = f"{run_id}__p{page:03d}"
        shard_dir = CONTROLLED_ROOT / shard_id
        shard_dirs.append(shard_dir)
        if not valid_node2_page(shard_dir, doc_id, page):
            tasks.append((page, shard_id, shard_dir))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {}
        for page, shard_id, _ in tasks:
            label = f"node2_p{page:03d}"
            future_map[
                executor.submit(
                    run_cmd,
                    [
                        "tools/english_text_first_sliding_window_composer_v01.py",
                        "--config",
                        rel_workspace(config),
                        "--node1a-run",
                        f"{doc_id}={rel_workspace(node1a_run)}",
                        "--node1b-run",
                        f"{doc_id}={rel_workspace(node1b_run)}",
                        "--pages",
                        f"{doc_id}:{page}",
                        "--run-id",
                        shard_id,
                    ],
                    log_dir=logs,
                    label=label,
                )
            ] = page
        for future in concurrent.futures.as_completed(future_map):
            future.result()
    missing = [page for page in range(1, page_count + 1) if not valid_node2_page(CONTROLLED_ROOT / f"{run_id}__p{page:03d}", doc_id, page)]
    if missing:
        raise RuntimeError(f"Node2 incomplete pages: {missing}")
    merge_node2_shards(shard_run_dirs=shard_dirs, out_dir=out_dir, doc_id=doc_id)
    return out_dir


def node3_parallel(
    *,
    config: Path,
    doc_id: str,
    document_groups_json: Path,
    node2_run: Path,
    run_id: str,
    workers: int,
    logs: Path,
) -> Path:
    dedupe = read_json(document_groups_json)
    group_ids = [str(group["document_group_id"]) for group in dedupe.get("document_groups") or []]
    out_dir = CONTROLLED_ROOT / run_id
    shard_dirs: list[Path] = []
    tasks: list[tuple[str, str, Path]] = []
    for group_id in group_ids:
        shard_id = f"{run_id}__{group_id}"
        shard_dir = CONTROLLED_ROOT / shard_id
        shard_dirs.append(shard_dir)
        if not valid_node3_group(shard_dir, doc_id, group_id):
            tasks.append((group_id, shard_id, shard_dir))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {}
        for group_id, shard_id, _ in tasks:
            label = f"node3_{group_id}"
            future_map[
                executor.submit(
                    run_cmd,
                    [
                        "tools/english_text_first_group_normalizer_v01.py",
                        "--config",
                        rel_workspace(config),
                        "--document-groups-json",
                        rel_workspace(document_groups_json),
                        "--node2-run",
                        rel_workspace(node2_run),
                        "--doc-id",
                        doc_id,
                        "--group-ids",
                        group_id,
                        "--run-id",
                        shard_id,
                    ],
                    log_dir=logs,
                    label=label,
                )
            ] = group_id
        for future in concurrent.futures.as_completed(future_map):
            future.result()
    missing = [gid for gid in group_ids if not valid_node3_group(CONTROLLED_ROOT / f"{run_id}__{gid}", doc_id, gid)]
    if missing:
        raise RuntimeError(f"Node3 incomplete groups: {missing}")
    merge_node3_shards(shard_run_dirs=shard_dirs, out_dir=out_dir, doc_id=doc_id, group_ids=group_ids)
    return out_dir


def run_single_doc(args: argparse.Namespace) -> dict[str, Any]:
    config = workspace_path(args.config)
    logs = CONTROLLED_ROOT / f"{args.run_prefix}_logs"
    started = time.time()

    node2_run = node2_parallel(
        config=config,
        doc_id=args.doc_id,
        node1a_run=workspace_path(args.node1a_run),
        node1b_run=workspace_path(args.node1b_run),
        page_count=args.page_count,
        run_id=f"{args.run_prefix}_node2",
        workers=args.node2_workers,
        logs=logs,
    )
    node2d_run = CONTROLLED_ROOT / f"{args.run_prefix}_node2d"
    run_cmd(
        [
            "tools/english_text_first_group_deduper_v01.py",
            "--node2-run",
            rel_workspace(node2_run),
            "--doc-id",
            args.doc_id,
            "--out-dir",
            rel_workspace(node2d_run),
        ],
        log_dir=logs,
        label="node2d",
    )
    document_groups_json = node2d_run / "document_groups.json"

    node3_run = node3_parallel(
        config=config,
        doc_id=args.doc_id,
        document_groups_json=document_groups_json,
        node2_run=node2_run,
        run_id=f"{args.run_prefix}_node3",
        workers=args.node3_workers,
        logs=logs,
    )
    node3b_run = CONTROLLED_ROOT / f"{args.run_prefix}_node3b"
    run_cmd(
        [
            "tools/english_text_first_group_relation_resolver_v01.py",
            "--config",
            rel_workspace(config),
            "--document-groups-json",
            rel_workspace(document_groups_json),
            "--node2-run",
            rel_workspace(node2_run),
            "--node3-run",
            rel_workspace(node3_run),
            "--doc-id",
            args.doc_id,
            "--run-id",
            node3b_run.name,
            "--chunked",
            "--max-groups-per-chunk",
            str(args.node3b_chunk_size),
            "--overlap-groups",
            str(args.node3b_overlap),
        ],
        log_dir=logs,
        label="node3b",
    )
    graph_json = node3b_run / "group_projection_graph.json"

    node3c_run = CONTROLLED_ROOT / f"{args.run_prefix}_node3c"
    run_cmd(
        [
            "tools/english_text_first_group_ownership_reconciler_v01.py",
            "--config",
            rel_workspace(config),
            "--node3-run",
            rel_workspace(node3_run),
            "--group-projection-graph",
            rel_workspace(graph_json),
            "--doc-id",
            args.doc_id,
            "--run-id",
            node3c_run.name,
        ],
        log_dir=logs,
        label="node3c",
    )

    node4_run = CONTROLLED_ROOT / f"{args.run_prefix}_node4"
    run_cmd(
        [
            "tools/english_text_first_source_backed_draft_builder_v01.py",
            "--config",
            rel_workspace(config),
            "--document-groups-json",
            rel_workspace(document_groups_json),
            "--node2-run",
            rel_workspace(node2_run),
            "--node3-run",
            rel_workspace(node3c_run),
            "--group-projection-graph",
            rel_workspace(graph_json),
            "--doc-id",
            args.doc_id,
            "--run-id",
            node4_run.name,
        ],
        log_dir=logs,
        label="node4",
    )

    node5_run = CONTROLLED_ROOT / f"{args.run_prefix}_node5"
    run_cmd(
        [
            "tools/english_text_first_question_packet_builder_v01.py",
            "--config",
            rel_workspace(config),
            "--draft-items-json",
            rel_workspace(node4_run / "draft_items.json"),
            "--doc-id",
            args.doc_id,
            "--run-id",
            node5_run.name,
        ],
        log_dir=logs,
        label="node5",
    )

    node5a_run = CONTROLLED_ROOT / f"{args.run_prefix}_node5a"
    run_cmd(
        [
            "tools/english_text_first_candidate_continuation_repair_v01.py",
            "--question-packet-candidates-json",
            rel_workspace(node5_run / "question_packet_candidates.json"),
            "--run-id",
            node5a_run.name,
            "--family",
            args.family,
            "--manifest",
            rel_workspace(workspace_path(args.manifest)),
            "--output-root",
            rel_workspace(CONTROLLED_ROOT),
        ],
        log_dir=logs,
        label="node5a",
    )
    node5b_input = node5a_run / "question_packet_candidates.repaired.json"
    family_override = {}
    if args.override_packet_family:
        override_path = node5a_run / f"question_packet_candidates.{args.override_packet_family}.experiment.json"
        family_override = override_packet_family(node5b_input, override_path, args.override_packet_family)
        node5b_input = override_path

    node5b_run = CONTROLLED_ROOT / f"{args.run_prefix}_node5b"
    run_cmd(
        [
            "tools/english_text_first_question_packet_refiner_v01.py",
            "--config",
            rel_workspace(config),
            "--question-packet-candidates-json",
            rel_workspace(node5b_input),
            "--doc-id",
            args.doc_id,
            "--max-workers",
            str(args.node5b_workers),
            "--run-id",
            node5b_run.name,
        ],
        log_dir=logs,
        label="node5b",
    )

    node6a_run = CONTROLLED_ROOT / f"{args.run_prefix}_node6a"
    run_cmd(
        [
            "tools/english_text_first_runtime_projection_planner_v01.py",
            "--refined-packets-json",
            rel_workspace(node5b_run / "refined_question_packets.json"),
            "--packet-candidates-json",
            rel_workspace(node5b_input),
            "--group-projection-graph-json",
            rel_workspace(graph_json),
            "--run-id",
            node6a_run.name,
        ],
        log_dir=logs,
        label="node6a",
    )

    display_run = CONTROLLED_ROOT / f"{args.run_prefix}_display_projection"
    run_cmd(
        [
            "tools/english_text_first_display_projection_planner_v01.py",
            "--refined-packets-json",
            rel_workspace(node5b_run / "refined_question_packets.json"),
            "--runtime-projection-plan-json",
            rel_workspace(node6a_run / "runtime_projection_plan.json"),
            "--output-dir",
            rel_workspace(display_run),
        ],
        log_dir=logs,
        label="display_projection",
    )

    node6b_run = CONTROLLED_ROOT / f"{args.run_prefix}_node6b"
    run_cmd(
        [
            "tools/english_text_first_question_render_normalizer_v01.py",
            "--config",
            rel_workspace(config),
            "--refined-packets-json",
            rel_workspace(node5b_run / "refined_question_packets.json"),
            "--runtime-projection-plan-json",
            rel_workspace(node6a_run / "runtime_projection_plan.json"),
            "--display-projection-plan-json",
            rel_workspace(display_run / "display_projection_plan.json"),
            "--max-workers",
            str(args.node6b_workers),
            "--run-id",
            node6b_run.name,
        ],
        log_dir=logs,
        label="node6b",
    )

    package_dir = workspace_path(args.package_dir) if args.package_dir else WORKSPACE / "outputs" / f"{args.run_prefix}_pkg"
    run_cmd(
        [
            "tools/english_text_first_review_pack_renderer_v01.py",
            "--records-json",
            rel_workspace(node6b_run / "rendered_question_records.json"),
            "--refined-packets-json",
            rel_workspace(node5b_run / "refined_question_packets.json"),
            "--out-dir",
            rel_workspace(package_dir),
            "--output-name",
            "index.html",
            "--question-structure-mode",
            "--title",
            args.title,
        ],
        log_dir=logs,
        label="review_package",
    )

    result = {
        "schema": "english_text_first_full_chain_runner_v0.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_id": args.doc_id,
        "family": args.family,
        "elapsed_seconds": round(time.time() - started, 3),
        "runs": {
            "node2": rel_workspace(node2_run),
            "node2d": rel_workspace(node2d_run),
            "node3": rel_workspace(node3_run),
            "node3b": rel_workspace(node3b_run),
            "node3c": rel_workspace(node3c_run),
            "node4": rel_workspace(node4_run),
            "node5": rel_workspace(node5_run),
            "node5a": rel_workspace(node5a_run),
            "node5b_input": rel_workspace(node5b_input),
            "node5b": rel_workspace(node5b_run),
            "node6a": rel_workspace(node6a_run),
            "display_projection": rel_workspace(display_run),
            "node6b": rel_workspace(node6b_run),
            "package": rel_workspace(package_dir),
            "logs": rel_workspace(logs),
        },
        "artifacts": {
            "review_html": rel_workspace(package_dir / "index.html"),
            "node6b_records": rel_workspace(node6b_run / "rendered_question_records.json"),
            "node5b_refined": rel_workspace(node5b_run / "refined_question_packets.json"),
        },
        "experimental_override": family_override,
    }
    write_json(CONTROLLED_ROOT / f"{args.run_prefix}_full_chain_summary.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumeable full-chain runner for English text-first graph-first pipeline.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--page-count", type=int, required=True)
    parser.add_argument("--node1a-run", required=True)
    parser.add_argument("--node1b-run", required=True)
    parser.add_argument("--manifest", default="config/english_text_first_graph_first/active_manifest.json")
    parser.add_argument("--override-packet-family", default="")
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--package-dir", default="")
    parser.add_argument("--title", default="English text-first review package")
    parser.add_argument("--node2-workers", type=int, default=2)
    parser.add_argument("--node3-workers", type=int, default=2)
    parser.add_argument("--node3b-chunk-size", type=int, default=12)
    parser.add_argument("--node3b-overlap", type=int, default=2)
    parser.add_argument("--node5b-workers", type=int, default=2)
    parser.add_argument("--node6b-workers", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(run_single_doc(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
