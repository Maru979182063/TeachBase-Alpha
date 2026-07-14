from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.document_profile_resolver import resolve_document_profile
from tools.pipeline_run_context import generate_run_id
from tools.semantic_role_adapter import build_adapter_diff_report, run_semantic_role_adapter_shadow
from tools.semantic_shadow_compare import compare_artifact_sets, load_json


ALLOWED_SIDECARS = [
    "document_profile.json",
    "semantic_role_adapter_results.json",
    "semantic_role_adapter_diff_report.json",
    "semantic_role_adapter_metrics.json",
    "semantic_role_adapter_prompt_trace.json",
    "semantic_role_adapter_review_samples.html",
    "semantic_role_shadow_non_interference_report.json",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_core(doc_root: Path, stable_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    assignments = load_json(doc_root / "assignments.json")
    semantic_nodes = load_json(doc_root / "semantic_nodes.json")
    audit_report = load_json(doc_root / "audit_report.json")
    legacy_bridge = load_json(stable_root / "legacy_bridge_questions.json")
    repair_pool = load_json(stable_root / "review_repair_pool.json")
    return assignments, semantic_nodes, audit_report, legacy_bridge, repair_pool


def _artifact_paths(doc_root: Path, stable_root: Path) -> list[str]:
    doc_rel = doc_root.relative_to(stable_root).as_posix()
    return [
        f"{doc_rel}/assignments.json",
        f"{doc_rel}/semantic_nodes.json",
        f"{doc_rel}/audit_report.json",
        "legacy_bridge_questions.json",
        "review_repair_pool.json",
    ]


def _review_samples_html(adapter_results: dict[str, Any]) -> str:
    rows = []
    for row in adapter_results.get("observations", []) or []:
        reasons = ", ".join(html.escape(str(reason)) for reason in row.get("review_reasons", []))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('node_id', '')))}</td>"
            f"<td>{html.escape(str(row.get('current_node_type', '')))}</td>"
            f"<td>{html.escape(str(row.get('current_review_status', '')))}</td>"
            f"<td>{reasons}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Semantic Role Shadow Review Samples</title></head>"
        "<body><table><thead><tr><th>node_id</th><th>node_type</th><th>review_status</th><th>review_reasons</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def _assert_owned_outputs(out_dir: Path, files: list[Path]) -> None:
    root = out_dir.resolve()
    names = sorted(path.name for path in files)
    if names != sorted(ALLOWED_SIDECARS):
        raise RuntimeError(f"unexpected_shadow_sidecars:{names}")
    for path in files:
        resolved = path.resolve()
        if root not in [resolved, *resolved.parents]:
            raise RuntimeError(f"shadow_output_outside_owned_root:{path}")


def run_shadow(
    *,
    stable_root: Path,
    doc_root: Path,
    out_root: Path,
    run_id: str | None = None,
    enable_shadow: bool = False,
    current_root: Path | None = None,
) -> dict[str, Any]:
    current_root = current_root or stable_root
    artifacts = _artifact_paths(doc_root, stable_root)
    compare_report = compare_artifact_sets(
        stable_root,
        current_root,
        artifacts,
        roots=[Path.cwd(), stable_root, current_root],
    )
    if not enable_shadow:
        return {
            "schema_version": "semantic_role_shadow_off_result.v0.1",
            "shadow_enabled": False,
            "document_profile_resolver_called": False,
            "semantic_role_adapter_called": False,
            "visual_semantic_assignments_v03_called": False,
            "sidecar_output_dir": "",
            "non_interference": compare_report,
        }

    run_id = run_id or generate_run_id("semantic_role_shadow")
    out_dir = out_root / run_id
    if out_dir.exists():
        raise FileExistsError(f"semantic_role_shadow_output_exists:{out_dir}")
    out_dir.mkdir(parents=True)

    assignments, semantic_nodes, audit_report, legacy_bridge, repair_pool = _load_core(doc_root, stable_root)
    document_profile = resolve_document_profile(
        doc_root=doc_root,
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
    )
    adapter_results = run_semantic_role_adapter_shadow(
        semantic_nodes=semantic_nodes,
        audit_report=audit_report,
        document_profile=document_profile,
    )
    diff_report = build_adapter_diff_report(
        semantic_nodes=semantic_nodes,
        adapter_results=adapter_results,
    )
    metrics = {
        "schema_version": "semantic_role_adapter_metrics_shadow.v0.1",
        "shadow_enabled": True,
        "model_invoked": False,
        "paid_model_invoked": False,
        "assignments_count": len(assignments.get("assignments", [])),
        "semantic_node_count": len(semantic_nodes.get("nodes", [])),
        "audit_record_count": len(audit_report.get("records", [])),
        "legacy_bridge_question_count": len(legacy_bridge.get("questions", [])),
        "review_repair_pool_count": len(repair_pool.get("items", [])),
        "adapter_observation_count": len(adapter_results.get("observations", [])),
        "diff_count": diff_report.get("diff_count", 0),
    }
    prompt_trace = {
        "schema_version": "semantic_role_adapter_prompt_trace_shadow.v0.1",
        "model_invoked": False,
        "paid_model_invoked": False,
        "prompt_content_recorded": False,
        "prompt_content_changed": False,
        "trace": [],
    }

    files = [
        out_dir / "document_profile.json",
        out_dir / "semantic_role_adapter_results.json",
        out_dir / "semantic_role_adapter_diff_report.json",
        out_dir / "semantic_role_adapter_metrics.json",
        out_dir / "semantic_role_adapter_prompt_trace.json",
        out_dir / "semantic_role_adapter_review_samples.html",
        out_dir / "semantic_role_shadow_non_interference_report.json",
    ]
    _write_json(files[0], document_profile)
    _write_json(files[1], adapter_results)
    _write_json(files[2], diff_report)
    _write_json(files[3], metrics)
    _write_json(files[4], prompt_trace)
    files[5].write_text(_review_samples_html(adapter_results), encoding="utf-8")
    _write_json(files[6], compare_report)
    _assert_owned_outputs(out_dir, files)
    return {
        "schema_version": "semantic_role_shadow_on_result.v0.1",
        "shadow_enabled": True,
        "sidecar_output_dir": str(out_dir),
        "sidecar_files": [str(path) for path in files],
        "non_interference": compare_report,
    }


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Semantic Role Adapter in isolated shadow sidecar mode.")
    parser.add_argument("--stable-root", required=True)
    parser.add_argument("--doc-root", required=True)
    parser.add_argument("--current-root")
    parser.add_argument("--out-root", default="outputs/semantic_role_shadow")
    parser.add_argument("--run-id")
    parser.add_argument("--enable-shadow", action="store_true")
    args = parser.parse_args()
    shadow_enabled = args.enable_shadow or _env_flag("SEMANTIC_ROLE_ADAPTER_SHADOW")
    if _env_flag("SEMANTIC_VISUAL_ASSIGNMENT_EXPERIMENT"):
        raise RuntimeError("SEMANTIC_VISUAL_ASSIGNMENT_EXPERIMENT must remain false for this shadow runner")
    result = run_shadow(
        stable_root=Path(args.stable_root),
        doc_root=Path(args.doc_root),
        current_root=Path(args.current_root) if args.current_root else None,
        out_root=Path(args.out_root),
        run_id=args.run_id,
        enable_shadow=shadow_enabled,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["non_interference"]["equality"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
