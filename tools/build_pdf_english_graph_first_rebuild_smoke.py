from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
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

BRANCH_ZIPS = {
    "reading": Path("C:/Users/1/Documents/WXWork/1688857912801359/Cache/File/2026-07/en_reading_downstream_fixed_20260728.zip"),
    "writing": Path("C:/Users/1/Documents/WXWork/1688857912801359/Cache/File/2026-07/en_writing_downstream_fixed_20260728.zip"),
    "grammar": Path("C:/Users/1/Documents/WXWork/1688857912801359/Cache/File/2026-07/en_grammar_downstream_fixed_20260728.zip"),
    "cloze": Path("C:/Users/1/Documents/WXWork/1688857912801359/Cache/File/2026-07/en_cloze_gloss_end_3cases_20260728_review_v2.zip"),
}


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except OSError:
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


def extract_branch_pages(branch: str, zip_path: Path) -> dict[str, Any]:
    page_dir = SMOKE_DIR / "source_page_images" / branch
    page_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        page_entries = sorted(
            entry
            for entry in archive.namelist()
            if entry.replace("\\", "/").startswith("assets/pages/page_") and entry.lower().endswith(".png")
        )
        for index, entry in enumerate(page_entries, start=1):
            target = page_dir / f"page_{index:03d}.png"
            with archive.open(entry) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            records.append(
                {
                    "page_number": index,
                    "source_zip_entry": entry.replace("\\", "/"),
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
        "source_zip_label": zip_path.name,
        "source_zip_sha256": file_sha256(zip_path),
        "zip_testzip": _zip_testzip(zip_path),
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
        "source_zip_label": zip_path.name,
    }


def _zip_testzip(path: Path) -> str | None:
    with zipfile.ZipFile(path) as archive:
        return archive.testzip()


def packet_count(path: Path) -> int:
    payload = read_json(path)
    packets = payload.get("packets") if isinstance(payload, dict) else None
    return len(packets) if isinstance(packets, list) else 0


def build_manifest(branches: dict[str, dict[str, Any]], v05_dir: Path, sidecar_dir: Path, zip_testzip: str | None) -> dict[str, Any]:
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
        "generated_at": datetime.now().isoformat(timespec="seconds"),
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
        "branch_runs": {
            branch: {
                "run_id": f"{ACTIVE_VERSION}_{branch}",
                "source": "fresh_rebuild_smoke_from_user_zip_evidence",
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
                "source": "user_supplied_downstream_review_zip_pages",
            }
            for branch, evidence in branches.items()
        },
        "documents": documents,
        "ready_claim_policy": {
            "ready_claim_allowed": False,
            "reason": "Fresh smoke validates manifest and branch evidence; production ready still requires full raw-PDF graph-first promotion.",
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def build_report() -> dict[str, Any]:
    missing_zips = [str(path.name) for path in BRANCH_ZIPS.values() if not path.is_file()]
    if missing_zips:
        return {
            "schema_version": "pdf_english_graph_first_rebuild_smoke.v0.1",
            "status": "blocked_missing_user_zip_evidence",
            "missing_zip_labels": missing_zips,
            "execution_contract": _no_side_effect_contract(),
        }
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
            "tests/fixtures/english_text_first_v05/english_text_first_v05.fixture_config.json",
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

    branches = {branch: extract_branch_pages(branch, zip_path) for branch, zip_path in BRANCH_ZIPS.items()}

    with zipfile.ZipFile(SMOKE_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SMOKE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(SMOKE_DIR.parent))
    zip_testzip = _zip_testzip(SMOKE_ZIP)
    manifest = build_manifest(branches, v05_dir, sidecar_dir, zip_testzip)
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
        "commands": [v05_result, sidecar_result, manifest_check],
        "ready_claim_allowed": False,
        "ready_claim_blocker": "full raw-PDF graph-first promotion is still required before production ready",
        "execution_contract": _no_side_effect_contract(),
    }


def _failed_report(status: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "pdf_english_graph_first_rebuild_smoke.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "status": status,
        "commands": commands,
        "execution_contract": _no_side_effect_contract(),
    }


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
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
