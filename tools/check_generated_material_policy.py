from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "generated_material_policy.json"
DEFAULT_INVENTORY_HEAD = "439249e95ffd3d27427812ac2b6a59744efb7421"
INVENTORY_PREFIXES = ("docs/reports/", "release_seed/reports/", "tests/fixtures/final_chain_samples/", "_archive/")
STABLE_EVIDENCE_STEMS = {
    "docs/reports/doc_english_code_import_20260804",
    "docs/reports/docx_math_final_import_20260804",
    "docs/reports/final_chain_inventory_20260731",
    "docs/reports/pdf_english_rebuild_source_import_20260804",
    "docs/reports/pdf_english_user_zip_intake_20260804",
    "docs/reports/phase0_evidence_manifest_20260902",
    "docs/reports/precleanup_archive_execution_20260804",
}
HISTORICAL_EVIDENCE_STEMS = {
    "docs/reports/cleanup_candidates_old_local_20260731",
    "docs/reports/final_chain_surface_classification_old_local_20260731",
}


def build_report(base: str, inventory_head: str) -> dict[str, Any]:
    paths = _inventory_paths(base, inventory_head)
    json_stems = {path[:-5] for path in paths if path.endswith(".json")}
    entries = [_classify(path, json_stems) for path in paths]
    unknown = [entry["path"] for entry in entries if entry["classification"] == "UNKNOWN"]
    tracked_ci = [
        entry["path"]
        for entry in entries
        if entry["classification"] == "CI_GENERATED_REPORT" and entry["tracked_at_head"]
    ]
    invalid = [entry["path"] for entry in entries if entry.get("format_valid") is False]
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
    return {
        "schema_version": "generated_material_policy.v0.1",
        "status": "pass" if not unknown and not tracked_ci and not invalid else "fail",
        "base": base,
        "inventory_head": inventory_head,
        "original_pre_phase2b_inventory_count": 101,
        "phase2b_added_material_count": max(0, len(entries) - 101),
        "inventory_count": len(entries),
        "classification_counts": counts,
        "unknown_paths": unknown,
        "tracked_ci_generated_paths": tracked_ci,
        "invalid_format_paths": invalid,
        "entries": entries,
    }


def _inventory_paths(base: str, inventory_head: str) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{inventory_head}", "--", *INVENTORY_PREFIXES],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return sorted(line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip())


def _classify(path: str, json_stems: set[str]) -> dict[str, Any]:
    current = ROOT / path
    tracked = _is_tracked(path)
    stem = path.removesuffix(".json").removesuffix(".md")
    if path.startswith("_archive/"):
        classification = "HISTORICAL_ARCHIVE"
        reason = "precleanup archive retained as historical trace"
    elif stem in HISTORICAL_EVIDENCE_STEMS:
        classification = "HISTORICAL_ARCHIVE"
        reason = "non-reproducible old-machine audit retained as labelled historical evidence"
    elif path.startswith("tests/fixtures/final_chain_samples/"):
        classification = "RUNTIME_REQUIRED_FIXTURE"
        reason = "portable adapter dry-run fixture with a real container format"
    elif stem in STABLE_EVIDENCE_STEMS:
        classification = "STABLE_GOLDEN_EVIDENCE"
        reason = "approved provenance or audit evidence whose hash is part of the integration record"
    elif path.startswith("release_seed/reports/"):
        classification = "CI_GENERATED_REPORT"
        reason = "release-seed gate output is uploaded by CI and not versioned"
    elif path.startswith("docs/reports/") and (path.endswith(".json") or path.removesuffix(".md") in json_stems):
        classification = "CI_GENERATED_REPORT"
        reason = "machine gate output or its rendered markdown companion"
    elif path.startswith("docs/reports/") and path.endswith(".md"):
        classification = "STABLE_GOLDEN_EVIDENCE"
        reason = "human-readable architecture or historical audit evidence without a generated JSON companion"
    else:
        classification = "UNKNOWN"
        reason = "no approved generated-material rule matched"
    entry: dict[str, Any] = {
        "path": path,
        "classification": classification,
        "reason": reason,
        "tracked_at_head": tracked,
        "exists_at_head": current.is_file(),
    }
    if current.is_file():
        entry["sha256"] = sha256(current.read_bytes()).hexdigest()
    if classification == "RUNTIME_REQUIRED_FIXTURE":
        entry["format_valid"] = _fixture_format_valid(current)
        if path.endswith(("doc_math_sample.docx", "doc_english_sample.docx")):
            entry["previous_disposition"] = "INVALID_PLACEHOLDER_REPLACED"
        if path.endswith("pdf_math_sample.pdf"):
            entry["previous_disposition"] = "INVALID_PLACEHOLDER_REPLACED"
    return entry


def _is_tracked(path: str) -> bool:
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _fixture_format_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() == ".pdf":
        return path.read_bytes().startswith(b"%PDF-")
    if path.suffix.lower() == ".docx":
        try:
            with ZipFile(path) as archive:
                return archive.testzip() is None and "word/document.xml" in archive.namelist()
        except BadZipFile:
            return False
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify aggregate-PR generated material and enforce its disposition.")
    parser.add_argument("--base", required=True, help="PR base SHA or ref.")
    parser.add_argument("--inventory-head", default=DEFAULT_INVENTORY_HEAD)
    args = parser.parse_args()
    report = build_report(args.base, args.inventory_head)
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
