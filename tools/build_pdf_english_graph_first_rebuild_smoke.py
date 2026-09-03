from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

PIPELINE_NAME = "english_text_first_graph_first"
ACTIVE_VERSION = "pdf_english_rebuild_20260806_v01"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "english_text_first_v05"
SMOKE_DIR = ROOT / "outputs" / "english_text_first_graph_first" / "final_chain_smoke_20260806_rebuild_v01"
SMOKE_ZIP = SMOKE_DIR.with_suffix(".zip")
ACTIVE_MANIFEST = ROOT / "config" / "english_text_first_graph_first" / "active_manifest.json"
REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_graph_first_rebuild_smoke_20260806.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_graph_first_rebuild_smoke_20260806.md"
REQUIRED_BRANCHES = ("reading", "writing", "grammar", "cloze")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return "<outside-workspace>"


def sanitize_text(value: str) -> str:
    return value.replace(str(ROOT), "<workspace>").replace(str(ROOT).replace("\\", "\\\\"), "<workspace>")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cmd(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": ["python", *args],
        "returncode": completed.returncode,
        "stdout_tail": sanitize_text(completed.stdout or "")[-2000:],
        "stderr_tail": sanitize_text(completed.stderr or "")[-2000:],
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rewrite_portable_summary(path: Path) -> None:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return
    if "config_path" in payload:
        payload["config_path"] = rel(Path(str(payload["config_path"])))
    if "out_dir" in payload:
        payload["out_dir"] = rel(Path(str(payload["out_dir"])))
    write_json(path, payload)


def extract_branch_pages(branch: str, page_sources: list[dict[str, str]], source_manifest: Path) -> dict[str, Any]:
    page_dir = SMOKE_DIR / "source_page_images" / branch
    page_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, source_record in enumerate(page_sources, start=1):
        source = _repository_path(source_record["path"])
        target = page_dir / f"page_{index:03d}.png"
        shutil.copyfile(source, target)
        records.append(
            {
                "page_number": index,
                "source_fixture": source_record["path"],
                "image_path": rel(target),
                "size_bytes": target.stat().st_size,
                "sha256": file_sha256(target),
            }
        )
    evidence_dir = SMOKE_DIR / "branch_evidence" / branch
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "pdf_english_graph_first.branch_review_summary.v0.1",
        "doc_id": branch,
        "branch": branch,
        "record_count": len(records),
        "page_count": len(records),
        "source_manifest": rel(source_manifest),
        "source_manifest_sha256": file_sha256(source_manifest),
        "foundation_fixture_only": True,
        "production_evidence": False,
        "model_calls_this_run": 0,
        "runtime_import_enabled": False,
        "database_write_enabled": False,
    }
    page_manifest = {
        "schema_version": "pdf_english_graph_first.branch_page_manifest.v0.1",
        "doc_id": branch,
        "records": records,
    }
    write_json(evidence_dir / "branch_summary.json", summary)
    write_json(evidence_dir / "page_manifest.json", page_manifest)
    return {
        "branch": branch,
        "page_count": len(records),
        "summary_json": rel(evidence_dir / "branch_summary.json"),
        "page_manifest": rel(evidence_dir / "page_manifest.json"),
        "source_page_dir": rel(page_dir),
        "source_manifest": rel(source_manifest),
    }


def _zip_testzip(path: Path) -> str | None:
    with zipfile.ZipFile(path) as archive:
        return archive.testzip()


def packet_count(path: Path) -> int:
    payload = read_json(path)
    packets = payload.get("packets") if isinstance(payload, dict) else None
    return len(packets) if isinstance(packets, list) else 0


def build_manifest(
    branches: dict[str, dict[str, Any]],
    v05_dir: Path,
    sidecar_dir: Path,
    zip_testzip: str | None,
    source_manifest: Path,
    source_payload: dict[str, Any],
) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for branch, evidence in branches.items():
        runs: dict[str, Any] = {
            "downstream_review_pages": {
                "run_id": f"{ACTIVE_VERSION}_{branch}_downstream_review_pages",
                "expected_doc_id": branch,
                "summary_json": evidence["summary_json"],
                "primary_artifact": evidence["page_manifest"],
                "expected_count": evidence["page_count"],
            }
        }
        if branch in {"reading", "writing"}:
            doc_id = f"{branch}_portable"
            packets = v05_dir / doc_id / "question_packet_candidates.json"
            runs["v05_packet_candidates"] = {
                "run_id": f"{ACTIVE_VERSION}_{branch}_v05_packet_candidates",
                "expected_doc_id": doc_id,
                "summary_json": rel(v05_dir / "run_summary.json"),
                "primary_artifact": rel(packets),
                "expected_count": packet_count(packets),
                "summary_count_required": False,
            }
            runs["sidecar_projection"] = {
                "run_id": f"{ACTIVE_VERSION}_{branch}_sidecar_projection",
                "expected_doc_id": doc_id,
                "summary_json": rel(sidecar_dir / "run_summary.json"),
                "primary_artifact": rel(sidecar_dir / "projection_report.json"),
                "summary_count_required": False,
                "artifact_count_required": False,
            }
        documents[branch] = {"doc_id": branch, "runs": runs}

    return {
        "schema_version": "english_text_first_graph_first.active_manifest.v0.1",
        "pipeline_name": PIPELINE_NAME,
        "active_version": ACTIVE_VERSION,
        "manifest_kind": "fresh_rebuild_candidate",
        "generated_at": source_payload["generated_at"],
        "allow_only_manifest_runs": True,
        "forbid_timestamp_latest_selection": True,
        "selection_policy": {
            "allow_only_manifest_runs": True,
            "forbid_timestamp_latest_selection": True,
            "forbidden_run_name_fragments": ["backup", "probe", "tmp", "scratch", ".bak"],
        },
        "fresh_smoke_artifacts": {
            "smoke_dir": rel(SMOKE_DIR),
            "smoke_zip": rel(SMOKE_ZIP),
            "zip_testzip": zip_testzip,
        },
        "foundation_rebuild_source": {
            "manifest": rel(source_manifest),
            "sha256": file_sha256(source_manifest),
            "source_kind": source_payload["source_kind"],
            "production_evidence": False,
        },
        "branch_runs": {
            branch: {
                "run_id": f"{ACTIVE_VERSION}_{branch}",
                "source": "repository_controlled_foundation_fixture",
                "summary_json": evidence["summary_json"],
                "primary_artifact": evidence["page_manifest"],
                "page_count": evidence["page_count"],
            }
            for branch, evidence in branches.items()
        },
        "source_page_images": {
            branch: {
                "path": evidence["source_page_dir"],
                "expected_page_count": evidence["page_count"],
                "source": "repository_controlled_foundation_fixture",
            }
            for branch, evidence in branches.items()
        },
        "documents": documents,
        "ready_claim_policy": {
            "ready_claim_allowed": False,
            "reason": "Foundation smoke is reproducible from HEAD but is not production execution evidence.",
            "production_readiness_status": source_payload["production_readiness_status"],
            "blockers": source_payload["production_readiness_blockers"],
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def build_report(source_manifest: Path) -> dict[str, Any]:
    source_payload, source_errors = _load_and_validate_source_manifest(source_manifest)
    if source_errors:
        return _failed_report("blocked_invalid_explicit_source_manifest", [], source_errors)
    if SMOKE_DIR.exists():
        shutil.rmtree(SMOKE_DIR)
    if SMOKE_ZIP.exists():
        SMOKE_ZIP.unlink()
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)

    v05_dir = SMOKE_DIR / "v05_rebuild"
    sidecar_dir = SMOKE_DIR / "sidecar_graph"
    v05_result = run_cmd(
        [
            "tools/english_text_first_v05_pipeline.py",
            "--config",
            str(source_payload["v05_config"]["path"]),
            "--out",
            rel(v05_dir),
        ]
    )
    if v05_result["returncode"] != 0:
        return _failed_report("v05_pipeline_failed", [v05_result])
    rewrite_portable_summary(v05_dir / "run_summary.json")

    sidecar_result = run_cmd(
        [
            "tools/english_text_first_sidecar_graph_v01.py",
            "--unit-root",
            "tests/fixtures/english_text_first_v05/unit_and_v04c",
            "--vlm-root",
            "tests/fixtures/english_text_first_v05/vlm_transcriber",
            "--base-root",
            rel(v05_dir),
            "--model-gate-root",
            rel(v05_dir),
            "--human-review",
            "tests/fixtures/english_text_first_v05/human_acceptance_review/human_acceptance_review.json",
            "--docs",
            "reading_portable,writing_portable",
            "--out",
            rel(sidecar_dir),
            "--clean",
        ]
    )
    if sidecar_result["returncode"] != 0:
        return _failed_report("sidecar_graph_failed", [v05_result, sidecar_result])

    branches = {
        branch: extract_branch_pages(branch, source_payload["branches"][branch]["page_files"], source_manifest)
        for branch in REQUIRED_BRANCHES
    }

    _write_reproducible_zip(SMOKE_DIR, SMOKE_ZIP)
    zip_testzip = _zip_testzip(SMOKE_ZIP)
    manifest = build_manifest(branches, v05_dir, sidecar_dir, zip_testzip, source_manifest, source_payload)
    write_json(ACTIVE_MANIFEST, manifest)

    manifest_check = run_cmd(
        [
            "tools/english_text_first_graph_first_manifest_check.py",
            "--manifest",
            rel(ACTIVE_MANIFEST),
            "--json",
        ]
    )
    status = "pass" if manifest_check["returncode"] == 0 and zip_testzip is None else "fail"
    return {
        "schema_version": "pdf_english_graph_first_rebuild_smoke.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": status,
        "active_version": ACTIVE_VERSION,
        "active_manifest": rel(ACTIVE_MANIFEST),
        "smoke_dir": rel(SMOKE_DIR),
        "smoke_zip": rel(SMOKE_ZIP),
        "smoke_zip_testzip": zip_testzip,
        "branch_page_counts": {branch: evidence["page_count"] for branch, evidence in branches.items()},
        "source_manifest": rel(source_manifest),
        "source_manifest_sha256": file_sha256(source_manifest),
        "source_validation_errors": [],
        "commands": [v05_result, sidecar_result, manifest_check],
        "foundation_integration_status": "PASS" if status == "pass" else "FAIL",
        "production_readiness_status": "BLOCKED",
        "production_readiness_blockers": source_payload["production_readiness_blockers"],
        "ready_claim_allowed": False,
        "ready_claim_blocker": "foundation fixtures do not prove continuous production execution",
        "execution_contract": _no_side_effect_contract(),
    }


def _failed_report(
    status: str,
    commands: list[dict[str, Any]],
    source_validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "pdf_english_graph_first_rebuild_smoke.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": status,
        "commands": commands,
        "source_validation_errors": source_validation_errors or [],
        "foundation_integration_status": "FAIL",
        "production_readiness_status": "BLOCKED",
        "execution_contract": _no_side_effect_contract(),
    }


def _repository_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"absolute_path_forbidden:{value}")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"path_outside_repository:{value}") from exc
    return resolved


def _fixture_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_and_validate_source_manifest(path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        resolved_manifest = path.resolve()
        resolved_manifest.relative_to(ROOT.resolve())
        payload = read_json(resolved_manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, [f"source_manifest_unreadable:{type(exc).__name__}"]
    if payload.get("schema_version") != "pdf_english_foundation_rebuild_sources.v0.1":
        errors.append("source_manifest_schema_invalid")
    if payload.get("scope") != "final_chain_foundation_integration_only":
        errors.append("source_manifest_scope_invalid")
    if payload.get("production_evidence") is not False:
        errors.append("source_manifest_must_not_claim_production_evidence")
    try:
        fixture_root = _repository_path(str(payload.get("fixture_root") or ""))
        if _fixture_tree_sha256(fixture_root) != payload.get("fixture_tree_sha256"):
            errors.append("fixture_tree_hash_mismatch")
        config_record = payload.get("v05_config") or {}
        config_path = _repository_path(str(config_record.get("path") or ""))
        if not config_path.is_file() or file_sha256(config_path) != config_record.get("sha256"):
            errors.append("v05_config_hash_mismatch")
        branches = payload.get("branches") or {}
        if sorted(branches) != sorted(REQUIRED_BRANCHES):
            errors.append("four_branch_sources_required")
        for branch in REQUIRED_BRANCHES:
            page_files = (branches.get(branch) or {}).get("page_files") or []
            if not page_files:
                errors.append(f"branch_page_source_missing:{branch}")
            for record in page_files:
                source = _repository_path(str(record.get("path") or ""))
                if not source.is_file() or file_sha256(source) != record.get("sha256"):
                    errors.append(f"branch_page_hash_mismatch:{branch}")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    return payload, errors


def _write_reproducible_zip(source_dir: Path, target: Path) -> None:
    # 固定 ZIP 元数据，保证 Windows 与 Linux 对同一受控输入生成相同归档。
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in source_dir.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source_dir.parent).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English Graph-First Rebuild Smoke 2026-08-06",
        "",
        f"Status: `{report['status']}`",
        "",
    ]
    if report.get("active_manifest"):
        lines.extend(
            [
                f"- Active manifest: `{report['active_manifest']}`",
                f"- Smoke dir: `{report['smoke_dir']}`",
                f"- Smoke zip: `{report['smoke_zip']}`",
                f"- Ready claim allowed: `{report['ready_claim_allowed']}`",
                "",
                "## Branch Page Counts",
                "",
            ]
        )
        for branch, count in sorted(report.get("branch_page_counts", {}).items()):
            lines.append(f"- `{branch}`: {count}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild PDF English foundation smoke from an explicit hashed source manifest.")
    parser.add_argument(
        "--source-manifest",
        required=True,
        help="Repository-relative pdf_english_foundation_rebuild_sources manifest.",
    )
    args = parser.parse_args()
    report = build_report(Path(args.source_manifest))
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
