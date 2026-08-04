from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.infrastructure.artifact_store import write_json, write_text

REPORT_JSON = ROOT / "docs" / "reports" / "pdf_english_user_zip_intake_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "pdf_english_user_zip_intake_20260804.md"

EXPECTED_BRANCHES = ("reading", "writing", "grammar", "cloze")
NO_SIDE_EFFECTS = {
    "model_invoked": False,
    "database_written": False,
    "runtime_imported": False,
    "business_secrets_read": False,
}


def build_report(zip_paths: list[Path]) -> dict[str, Any]:
    records = [_zip_record(path) for path in zip_paths]
    pdf_english_records = [record for record in records if record["classification"] == "pdf_english_downstream_review"]
    received_branches = sorted(
        {
            str(record["branch"])
            for record in pdf_english_records
            if record.get("branch") in EXPECTED_BRANCHES and record.get("zip_valid") is True
        }
    )
    non_pdf_english_records = [record for record in records if record["classification"] != "pdf_english_downstream_review"]
    canonical_artifacts_present = any(
        record.get("has_active_manifest")
        or record.get("has_manifest_check_tool")
        or record.get("has_final_chain_smoke")
        for record in records
    )
    checks = [
        {
            "name": "all_input_zips_exist",
            "ok": all(record["exists"] for record in records),
            "value": [record["input_label"] for record in records if not record["exists"]],
        },
        {
            "name": "all_input_zips_valid",
            "ok": all(record.get("zip_valid") is True for record in records),
            "value": [record["input_label"] for record in records if record.get("zip_valid") is not True],
        },
        {
            "name": "four_pdf_english_branch_review_packages_present",
            "ok": received_branches == sorted(EXPECTED_BRANCHES),
            "value": received_branches,
            "expected": sorted(EXPECTED_BRANCHES),
        },
        {
            "name": "no_zip_contains_canonical_active_manifest",
            "ok": not any(record.get("has_active_manifest") for record in records),
            "value": [record["input_label"] for record in records if record.get("has_active_manifest")],
        },
        {
            "name": "no_zip_contains_manifest_checker",
            "ok": not any(record.get("has_manifest_check_tool") for record in records),
            "value": [record["input_label"] for record in records if record.get("has_manifest_check_tool")],
        },
        {
            "name": "no_zip_contains_final_chain_smoke",
            "ok": not any(record.get("has_final_chain_smoke") for record in records),
            "value": [record["input_label"] for record in records if record.get("has_final_chain_smoke")],
        },
        {
            "name": "non_pdf_english_packages_are_excluded_from_pdf_english_recovery_identity",
            "ok": all(record["classification"] in {"doc_math_review", "unknown_or_unusable"} for record in non_pdf_english_records),
            "value": [
                {"input_label": record["input_label"], "classification": record["classification"]}
                for record in non_pdf_english_records
            ],
        },
    ]
    status = (
        "downstream_review_evidence_received"
        if all(check["ok"] for check in checks[:3]) and not canonical_artifacts_present
        else "incomplete_or_mixed_user_zip_evidence"
    )
    return {
        "schema_version": "pdf_english_user_zip_intake.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "chain_id": "pdf_english",
        "canonical_pipeline_name": "english_text_first_graph_first",
        "status": status,
        "input_recording": "filename_label_and_hash_only",
        "received_branch_evidence": received_branches,
        "non_pdf_english_zip_count": len(non_pdf_english_records),
        "canonical_recovery_artifacts_present": canonical_artifacts_present,
        "legacy_artifact_recovery_ready": False,
        "rebuild_evidence_available": received_branches == sorted(EXPECTED_BRANCHES),
        "ready_claim_allowed": False,
        "old_identity_claim_allowed": False,
        "records": records,
        "checks": checks,
        "safe_next_actions": [
            "keep_these_zips_as_downstream_review_evidence",
            "do_not_treat_user_zips_as_active_manifest_or_final_smoke",
            "use_four_branch_evidence_to_support_a_fresh_pdf_english_rebuild_candidate",
            "generate_new_active_manifest_and_new_smoke_before_marking_pdf_english_ready",
        ],
        "unsafe_actions": [
            "do_not_import_review_html_as_canonical_pipeline_config",
            "do_not_claim_20260728_final_chain_smoke_recovered_from_these_zips",
            "do_not_use_doc_math_review_zip_as_pdf_english_evidence",
            "do_not_record_local_cache_paths_as_reproducible_contract",
        ],
        "execution_contract": NO_SIDE_EFFECTS,
    }


def _zip_record(path: Path) -> dict[str, Any]:
    label = path.name
    record: dict[str, Any] = {
        "input_label": label,
        "exists": path.is_file(),
        "classification": "unknown_or_unusable",
        "branch": "",
    }
    if not path.is_file():
        record.update({"zip_valid": False, "zip_error": "missing"})
        return record
    record["size_bytes"] = path.stat().st_size
    record["sha256"] = _file_sha256(path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            lower_names = [name.lower() for name in names]
            testzip = archive.testzip()
            titles = _html_titles(archive, names)
            record.update(
                {
                    "zip_valid": testzip is None,
                    "zip_testzip": testzip,
                    "entry_count": len(names),
                    "html_count": sum(name.endswith(".html") for name in lower_names),
                    "json_count": sum(name.endswith(".json") for name in lower_names),
                    "png_count": sum(name.endswith(".png") for name in lower_names),
                    "docx_count": sum(name.endswith(".docx") for name in lower_names),
                    "has_active_manifest": any("active_manifest.json" in name for name in lower_names),
                    "has_manifest_check_tool": any("manifest_check" in name for name in lower_names),
                    "has_final_chain_smoke": any("final_chain_smoke_20260728" in name for name in lower_names),
                    "html_titles": titles,
                }
            )
            classification, branch = _classify(label, titles, archive, names)
            record["classification"] = classification
            record["branch"] = branch
    except zipfile.BadZipFile:
        record.update({"zip_valid": False, "zip_error": "bad_zip_file"})
    return record


def _classify(label: str, titles: list[str], archive: zipfile.ZipFile, names: list[str]) -> tuple[str, str]:
    text = " ".join([label, *titles]).lower()
    for branch in EXPECTED_BRANCHES:
        if f"en_{branch}" in text or f"english_{branch}" in text or (branch == "cloze" and "完形填空" in text):
            return "pdf_english_downstream_review", branch
    if "docx math" in text or "docx_math" in text or _doc_math_schema_present(archive, names):
        return "doc_math_review", ""
    return "unknown_or_unusable", ""


def _doc_math_schema_present(archive: zipfile.ZipFile, names: list[str]) -> bool:
    for name in names:
        if not name.lower().endswith(".json"):
            continue
        try:
            payload = json.loads(archive.read(name).decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("schema") or "").startswith("docx_math"):
            return True
    return False


def _html_titles(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    titles: list[str] = []
    for name in names:
        if not name.lower().endswith(".html"):
            continue
        try:
            text = archive.read(name).decode("utf-8", errors="replace")
        except KeyError:
            continue
        match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title not in titles:
                titles.append(title)
    return titles[:8]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF English User Zip Intake 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Received branch evidence: `{', '.join(report['received_branch_evidence'])}`",
        f"Ready claim allowed: `{str(report['ready_claim_allowed']).lower()}`",
        "",
        "## Records",
        "",
    ]
    for record in report["records"]:
        branch = f" `{record['branch']}`" if record.get("branch") else ""
        lines.append(f"- `{record['classification']}`{branch} `{record['input_label']}`")
    lines.extend(["", "## Checks", ""])
    for check in report["checks"]:
        status = "pass" if check["ok"] else "fail"
        lines.append(f"- `{status}` `{check['name']}`")
    lines.extend(["", "## Safe Next Actions", ""])
    for action in report["safe_next_actions"]:
        lines.append(f"- `{action}`")
    lines.append("")
    lines.append("Input zips are recorded by filename label and hash only; no local cache path is part of the reproducible contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify user-supplied PDF English recovery/rebuild zip evidence.")
    parser.add_argument("--zip", dest="zips", action="append", default=[], help="Path to a candidate zip.")
    args = parser.parse_args()

    report = build_report([Path(item) for item in args.zips])
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "downstream_review_evidence_received" else 2


if __name__ == "__main__":
    raise SystemExit(main())
