from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "docs" / "reports" / "docx_math_final_import_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "docx_math_final_import_20260804.md"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(source_root: Path, inventory_path: Path) -> dict:
    payload = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    rows = []
    counts: dict[str, int] = {}
    for item in payload.get("files", []):
        relative_path = str(item["path"]).replace("\\", "/")
        expected_sha256 = str(item["sha256"])
        source_path = source_root / relative_path
        cleanroom_path = ROOT / relative_path
        source_sha256 = sha256_file(source_path) if source_path.is_file() else ""
        cleanroom_sha256 = sha256_file(cleanroom_path) if cleanroom_path.is_file() else ""
        status = classify_row(expected_sha256, source_sha256, cleanroom_sha256)
        counts[status] = counts.get(status, 0) + 1
        rows.append(
            {
                "relative_path": relative_path,
                "status": status,
                "expected_sha256": expected_sha256,
                "source_exists": source_path.is_file(),
                "source_matches_inventory": bool(source_sha256 and source_sha256 == expected_sha256),
                "cleanroom_exists": cleanroom_path.is_file(),
                "cleanroom_matches_inventory": bool(cleanroom_sha256 and cleanroom_sha256 == expected_sha256),
                "cleanroom_sha256": cleanroom_sha256,
            }
        )
    return {
        "schema_version": "docx_math_final_import_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "inventory_file_count": len(rows),
        "counts": counts,
        "rows": rows,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def classify_row(expected_sha256: str, source_sha256: str, cleanroom_sha256: str) -> str:
    if not source_sha256:
        return "source_missing"
    if source_sha256 != expected_sha256:
        return "source_hash_mismatch"
    if not cleanroom_sha256:
        return "cleanroom_missing"
    if cleanroom_sha256 == expected_sha256:
        return "cleanroom_matches_handoff_inventory"
    return "cleanroom_hash_conflict_not_overwritten"


def render_markdown(report: dict) -> str:
    lines = [
        "# DOCX Math Final Import 2026-08-04",
        "",
        "This report verifies the DOCX math final-chain handoff inventory after cleanroom import.",
        "All file locations are relative git paths; local absolute source roots are not part of the reproducible input contract.",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(report["counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Conflicts", ""])
    conflicts = [row for row in report["rows"] if row["status"] == "cleanroom_hash_conflict_not_overwritten"]
    if not conflicts:
        lines.append("- `none`")
    for row in conflicts:
        lines.append(f"- `{row['relative_path']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DOCX math final-chain cleanroom import.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--inventory", required=True)
    args = parser.parse_args()
    report = build_report(Path(args.source_root), Path(args.inventory))
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
