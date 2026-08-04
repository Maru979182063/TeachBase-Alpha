from __future__ import annotations

import argparse
import json
from pathlib import Path

from teachbase.final_chains import build_cleanroom_import_audit, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_cleanroom_import_audit_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_cleanroom_import_audit_20260804.md"


def parse_label_paths(items: list[str] | None) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for item in items or []:
        label, sep, value = item.partition("=")
        if sep and label:
            parsed[label] = Path(value)
    return parsed


def render_markdown(report: dict) -> str:
    lines = [
        "# Final Chain Cleanroom Import Audit 2026-08-04",
        "",
        "This report checks canonical final-chain files before importing them into the cleanroom.",
        "All recorded file locations are relative git paths or source labels; local absolute source roots are not part of the reproducible input contract.",
        "",
        "## Summary",
        "",
        f"- chains: `{report['chain_count']}`",
        f"- required rows: `{report['row_count']}`",
        f"- missing in cleanroom: `{report['missing_in_cleanroom_count']}`",
        f"- rows with source candidates: `{report['importable_candidate_count']}`",
        "",
        "## Rows",
        "",
    ]
    for row in report["rows"]:
        candidates = [item["source_label"] for item in row["source_candidates"] if item["exists"]]
        candidate_text = ", ".join(f"`{item}`" for item in candidates) or "`none`"
        lines.append(
            f"- `{row['chain_id']}` `{row['role']}` `{row['relative_path']}`: "
            f"`{row['import_action']}`, candidates: {candidate_text}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit final-chain canonical files before cleanroom import.")
    parser.add_argument("--source-root", action="append", help="label=path source root to probe.")
    parser.add_argument("--handoff-inventory", action="append", help="chain_id=path handoff inventory JSON.")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    registry = load_final_chain_registry(REGISTRY)
    report = build_cleanroom_import_audit(
        registry,
        workspace_root=ROOT,
        source_roots=parse_label_paths(args.source_root),
        handoff_inventories=parse_label_paths(args.handoff_inventory),
    )
    if not args.no_write:
        write_json(REPORT_JSON, report)
        write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
