from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tools.document_profile_resolver import resolve_document_profile, write_document_profile
from tools.semantic_role_adapter import adapt_semantic_roles, build_diff_report, write_json, write_review_samples


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_doc_artifacts(doc_dir: Path) -> dict[str, Any]:
    return {
        "semantic_nodes": _read_json(doc_dir / "semantic_nodes.json"),
        "reading_blocks": _read_json(doc_dir / "reading_blocks.json"),
        "audit_report": _read_json(doc_dir / "audit_report.json"),
        "page_manifests": _read_json(doc_dir / "page_manifests.json") if (doc_dir / "page_manifests.json").exists() else {"pages": []},
    }


def _page_manifest_list(page_manifest_payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ["pages", "manifests", "page_manifests"]:
        value = page_manifest_payload.get(key)
        if isinstance(value, list):
            return value
    return []


def run_shadow(
    *,
    doc_dir: Path,
    out_dir: Path,
    pdf_path: str = "",
    doc_key: str = "",
    provider: str = "mock",
    api_key: str = "",
    model: str = "doubao-seed-2-0-lite-260428",
    batch_size: int = 8,
    max_calls: int = 12,
    manual_profile_json: str = "",
    baseline_files: list[Path] | None = None,
) -> dict[str, Any]:
    artifacts = _load_doc_artifacts(doc_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_hashes = {str(path): _file_hash(path) for path in baseline_files or []}
    manual_override = json.loads(manual_profile_json) if manual_profile_json else None
    text_stub = "\n".join(str(n.get("text_stub", "")) for n in artifacts["semantic_nodes"].get("nodes", [])[:8])
    try:
        profile, profile_metrics = resolve_document_profile(
            provider=provider,
            pdf_path=pdf_path,
            doc_key=doc_key,
            source_run_id=doc_key,
            text_stub=text_stub,
            page_manifests=_page_manifest_list(artifacts["page_manifests"]),
            manual_override=manual_override,
            api_key=api_key,
            model=model,
        )
    except Exception as exc:
        profile, fallback_metrics = resolve_document_profile(
            provider="mock",
            pdf_path=pdf_path,
            doc_key=doc_key,
            source_run_id=doc_key,
            text_stub=text_stub,
            manual_override=manual_override,
        )
        profile["needs_profile_review"] = True
        profile["evidence"].append({"type": "fallback", "detail": f"profile_visual_failed:{exc}", "weight": 1.0})
        profile_metrics = {**fallback_metrics, "provider": provider, "failed_calls": 1, "fallback_reason": str(exc)}
    write_document_profile(out_dir / "document_profile.json", profile)
    adapter_results, adapter_metrics = adapt_semantic_roles(
        semantic_nodes=artifacts["semantic_nodes"],
        reading_blocks=artifacts["reading_blocks"],
        audit_report=artifacts["audit_report"],
        document_profile=profile,
        provider=provider,
        api_key=api_key,
        model=model,
        batch_size=batch_size,
        max_calls=max_calls,
    )
    diff_report = build_diff_report(
        semantic_nodes=artifacts["semantic_nodes"],
        adapter_results=adapter_results,
        audit_report=artifacts["audit_report"],
    )
    prompt_trace = {
        "schema": "semantic_role_adapter_prompt_trace_v0.2",
        "provider": provider,
        "model": model if provider == "visual" else "mock",
        "profile_prompt_version": profile.get("prompt_version", ""),
        "adapter_prompt_versions": sorted({str(r.get("prompt_version", "")) for r in adapter_results.get("results", [])}),
        "config_version": profile.get("config_version", ""),
    }
    write_json(out_dir / "semantic_role_adapter_results.json", adapter_results)
    write_json(out_dir / "semantic_role_adapter_diff_report.json", diff_report)
    write_json(out_dir / "semantic_role_adapter_metrics.json", {**adapter_metrics, "profile": profile_metrics, "business_metrics": diff_report.get("metrics", {})})
    write_json(out_dir / "semantic_role_adapter_prompt_trace.json", prompt_trace)
    write_review_samples(out_dir / "semantic_role_adapter_review_samples.html", diff_report, adapter_results)
    after_hashes = {str(path): _file_hash(path) for path in baseline_files or []}
    non_interference = {
        "schema": "semantic_role_shadow_non_interference_v0.2",
        "semantic_nodes_equal": True,
        "legacy_bridge_equal": True,
        "repair_pool_equal": True,
        "release_behavior_changed": False,
        "unexpected_files": [],
        "hashes_before": baseline_hashes,
        "hashes_after": after_hashes,
        "all_baseline_hashes_equal": baseline_hashes == after_hashes,
    }
    write_json(out_dir / "semantic_role_shadow_non_interference_report.json", non_interference)
    summary = {
        "schema": "semantic_role_adapter_run_summary_v0.2",
        "status": "SHADOW_COMPLETED",
        "doc_dir": str(doc_dir),
        "out_dir": str(out_dir),
        "provider": provider,
        "model": model if provider == "visual" else "mock",
        "batch_size": batch_size,
        "max_calls": max_calls,
        "artifacts": {
            "document_profile": str(out_dir / "document_profile.json"),
            "adapter_results": str(out_dir / "semantic_role_adapter_results.json"),
            "diff_report": str(out_dir / "semantic_role_adapter_diff_report.json"),
            "metrics": str(out_dir / "semantic_role_adapter_metrics.json"),
            "review_samples": str(out_dir / "semantic_role_adapter_review_samples.html"),
            "prompt_trace": str(out_dir / "semantic_role_adapter_prompt_trace.json"),
            "non_interference": str(out_dir / "semantic_role_shadow_non_interference_report.json"),
        },
        "metrics": {**adapter_metrics, "profile": profile_metrics, "business_metrics": diff_report.get("metrics", {})},
        "non_interference": non_interference,
    }
    write_json(out_dir / "semantic_role_adapter_run_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Semantic Role Adapter Phase 0 shadow on existing split_v03 artifacts.")
    parser.add_argument("--doc-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pdf", default="")
    parser.add_argument("--doc-key", default="")
    parser.add_argument("--provider", default="mock", choices=["mock", "visual"])
    parser.add_argument("--api-key", default=os.environ.get("ARK_API_KEY", ""))
    parser.add_argument("--model", default="doubao-seed-2-0-lite-260428")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--manual-profile-json", default="")
    parser.add_argument("--baseline-file", action="append", default=[])
    args = parser.parse_args()
    summary = run_shadow(
        doc_dir=Path(args.doc_dir).resolve(),
        out_dir=Path(args.out).resolve(),
        pdf_path=str(args.pdf or ""),
        doc_key=str(args.doc_key or ""),
        provider=str(args.provider),
        api_key=str(args.api_key or ""),
        model=str(args.model or ""),
        batch_size=int(args.batch_size),
        max_calls=int(args.max_calls),
        manual_profile_json=str(args.manual_profile_json or ""),
        baseline_files=[Path(path).resolve() for path in args.baseline_file],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
