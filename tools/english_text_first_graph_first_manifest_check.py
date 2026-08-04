from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("config/english_text_first_graph_first/active_manifest.json")
EXPECTED_PIPELINE_NAME = "english_text_first_graph_first"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count_payload_items(path: Path) -> int | None:
    if path.is_dir():
        return None
    payload = read_json(path)
    for key in [
        "records",
        "packets",
        "question_packets",
        "items",
        "projections",
        "question_projections",
        "candidates",
        "document_groups",
        "nodes",
    ]:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ["record_count", "packet_count", "question_projection_count", "document_group_count"]:
            value = summary.get(key)
            if isinstance(value, int):
                return value
    return None


def summary_count(summary: dict[str, Any]) -> int | None:
    draft_summary = summary.get("draft_summary")
    if isinstance(draft_summary, dict):
        value = draft_summary.get("draft_count")
        if isinstance(value, int):
            return value
    for key in [
        "packet_count",
        "record_count",
        "pages_attempted",
        "pages_valid",
        "question_projection_count",
        "valid_packet_count",
        "valid_count",
        "groups_valid",
        "adjusted_group_count",
        "draft_count",
    ]:
        value = summary.get(key)
        if isinstance(value, int):
            return value
    return None


def validate_manifest(path: Path, workspace: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    manifest = read_json(path)

    if manifest.get("pipeline_name") != EXPECTED_PIPELINE_NAME:
        errors.append({
            "code": "wrong_pipeline_name",
            "expected": EXPECTED_PIPELINE_NAME,
            "actual": manifest.get("pipeline_name"),
        })
    if manifest.get("schema_version") != "english_text_first_graph_first.active_manifest.v0.1":
        errors.append({"code": "wrong_schema_version", "actual": manifest.get("schema_version")})

    forbidden_fragments = [
        str(item)
        for item in (manifest.get("selection_policy") or {}).get("forbidden_run_name_fragments", [])
    ]
    if not forbidden_fragments:
        errors.append({"code": "missing_forbidden_run_name_fragments"})

    source_pages = manifest.get("source_page_images")
    if not isinstance(source_pages, dict) or not source_pages:
        errors.append({"code": "missing_source_page_images"})
    else:
        for doc_key, item in source_pages.items():
            page_dir = workspace / str(item.get("path") or "")
            expected_count = item.get("expected_page_count")
            if not page_dir.exists():
                errors.append({"code": "source_page_dir_missing", "doc": doc_key, "path": str(page_dir)})
                continue
            actual_count = len(list(page_dir.glob("page_*.png")))
            if actual_count != expected_count:
                errors.append({
                    "code": "source_page_count_mismatch",
                    "doc": doc_key,
                    "expected": expected_count,
                    "actual": actual_count,
                    "path": str(page_dir),
                })

    documents = manifest.get("documents")
    if not isinstance(documents, dict) or not documents:
        errors.append({"code": "missing_documents"})
        documents = {}

    checked_runs = 0
    for doc_key, doc in documents.items():
        doc_id = str(doc.get("doc_id") or "")
        if not doc_id:
            errors.append({"code": "missing_doc_id", "doc": doc_key})
        runs = doc.get("runs")
        if not isinstance(runs, dict) or not runs:
            errors.append({"code": "missing_runs", "doc": doc_key})
            continue
        for node_key, run in runs.items():
            checked_runs += 1
            run_id = str(run.get("run_id") or "")
            if not run_id:
                errors.append({"code": "missing_run_id", "doc": doc_key, "node": node_key})
                continue
            for fragment in forbidden_fragments:
                if fragment and fragment in run_id:
                    errors.append({
                        "code": "forbidden_run_selected",
                        "doc": doc_key,
                        "node": node_key,
                        "run_id": run_id,
                        "fragment": fragment,
                    })

            summary_path = workspace / str(run.get("summary_json") or "")
            artifact_path = workspace / str(run.get("primary_artifact") or "")
            artifact_glob = str(run.get("artifact_glob") or "")
            if not summary_path.exists():
                errors.append({
                    "code": "summary_missing",
                    "doc": doc_key,
                    "node": node_key,
                    "path": str(summary_path),
                })
                continue
            if not artifact_path.exists():
                errors.append({
                    "code": "artifact_missing",
                    "doc": doc_key,
                    "node": node_key,
                    "path": str(artifact_path),
                })
                continue

            summary = read_json(summary_path)
            expected_doc_id = str(run.get("expected_doc_id") or doc_id)
            summary_doc_id = summary.get("doc_id")
            if summary_doc_id and summary_doc_id != expected_doc_id:
                errors.append({
                    "code": "doc_id_mismatch",
                    "doc": doc_key,
                    "node": node_key,
                    "expected": expected_doc_id,
                    "actual": summary_doc_id,
                })

            expected_count = run.get("expected_count")
            artifact_count_required = run.get("artifact_count_required", True)
            summary_count_required = run.get("summary_count_required", True)
            actual_summary_count = summary_count(summary)
            if artifact_glob and artifact_path.is_dir():
                actual_artifact_count = len(list(artifact_path.glob(artifact_glob)))
            else:
                actual_artifact_count = count_payload_items(artifact_path)
            if isinstance(expected_count, int):
                if summary_count_required and actual_summary_count is not None and actual_summary_count != expected_count:
                    errors.append({
                        "code": "summary_count_mismatch",
                        "doc": doc_key,
                        "node": node_key,
                        "expected": expected_count,
                        "actual": actual_summary_count,
                        "summary": str(summary_path),
                    })
                if artifact_count_required and actual_artifact_count is not None and actual_artifact_count != expected_count:
                    errors.append({
                        "code": "artifact_count_mismatch",
                        "doc": doc_key,
                        "node": node_key,
                        "expected": expected_count,
                        "actual": actual_artifact_count,
                        "artifact": str(artifact_path),
                    })
                if summary_count_required and actual_summary_count is None and (actual_artifact_count is None or not artifact_count_required):
                    warnings.append({
                        "code": "count_not_detected",
                        "doc": doc_key,
                        "node": node_key,
                        "artifact": str(artifact_path),
                    })

    return {
        "schema_version": "english_text_first_graph_first.manifest_check_result.v0.1",
        "manifest_path": str(path),
        "pipeline_name": manifest.get("pipeline_name"),
        "active_version": manifest.get("active_version"),
        "checked_run_count": checked_runs,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the active English text-first graph-first manifest.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    result = validate_manifest(manifest_path, Path.cwd())
    if args.json or not result["ok"]:
        stream = sys.stdout if result["ok"] else sys.stderr
        print(json.dumps(result, ensure_ascii=False, indent=2), file=stream)
    else:
        print(
            "english_text_first_graph_first_manifest_valid "
            f"active_version={result['active_version']} checked_runs={result['checked_run_count']} "
            f"warnings={result['warning_count']}"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
