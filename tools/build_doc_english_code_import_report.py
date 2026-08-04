from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "doc_english_code_import_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "doc_english_code_import_20260804.md"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_report(source_root: Path) -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    chain = next(item for item in registry["chains"] if item["chain_id"] == "doc_english")
    paths = [
        str(path).replace("\\", "/")
        for path in chain["protected_paths"]
        if str(path).startswith(("tools/", "config/", "prompts/"))
    ]
    output_paths = [str(path).replace("\\", "/") for path in chain["protected_paths"] if str(path).startswith("outputs/")]
    rows = []
    counts: dict[str, int] = {}
    for relative_path in paths:
        source_path = source_root / relative_path
        cleanroom_path = ROOT / relative_path
        source_sha256 = sha256_file(source_path) if source_path.is_file() else ""
        cleanroom_sha256 = sha256_file(cleanroom_path) if cleanroom_path.is_file() else ""
        status = classify_row(source_sha256, cleanroom_sha256)
        counts[status] = counts.get(status, 0) + 1
        rows.append(
            {
                "relative_path": relative_path,
                "status": status,
                "source_exists": source_path.is_file(),
                "cleanroom_exists": cleanroom_path.is_file(),
                "source_sha256": source_sha256,
                "cleanroom_sha256": cleanroom_sha256,
            }
        )
    return {
        "schema_version": "doc_english_code_import_report.v0.1",
        "workspace_contract": "relative_git_paths_only",
        "absolute_paths_as_inputs": False,
        "import_scope": "code_config_prompt_only",
        "protected_code_config_prompt_count": len(paths),
        "protected_output_path_count": len(output_paths),
        "output_paths_imported": False,
        "counts": counts,
        "rows": rows,
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def classify_row(source_sha256: str, cleanroom_sha256: str) -> str:
    if not source_sha256:
        return "source_missing"
    if not cleanroom_sha256:
        return "cleanroom_missing"
    if source_sha256 == cleanroom_sha256:
        return "cleanroom_matches_source"
    return "cleanroom_hash_conflict"


def render_markdown(report: dict) -> str:
    lines = [
        "# DOC English Code Import 2026-08-04",
        "",
        "This report verifies the DOCX English cleanroom import for code, config, and prompt files only.",
        "Protected output artifacts are intentionally not imported in this step.",
        "All file locations are relative git paths; local absolute source roots are not part of the reproducible input contract.",
        "",
        "## Counts",
        "",
    ]
    for status, count in sorted(report["counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(
        [
            f"- `protected_output_path_count`: {report['protected_output_path_count']}",
            f"- `output_paths_imported`: {str(report['output_paths_imported']).lower()}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DOCX English code/config/prompt cleanroom import.")
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    report = build_report(Path(args.source_root))
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
