from __future__ import annotations

import json
from pathlib import Path

from teachbase.final_chains import build_final_chain_control_dashboard, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_control_dashboard_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_control_dashboard_20260804.md"


def render_markdown(report: dict) -> str:
    lines = [
        "# Final Chain Control Dashboard 2026-08-04",
        "",
        "This dashboard combines protected final-chain readiness, adapter contracts, and scheduler lifecycle policy.",
        "All paths are relative git paths; no local absolute path is part of the reproducible input contract.",
        "",
        "## Counts",
        "",
    ]
    for lane, count in sorted(report["lane_counts"].items()):
        lines.append(f"- `{lane}`: {count}")
    lines.extend(["", "## Lifecycle Policy", ""])
    for status, next_statuses in report["job_lifecycle_policy"]["allowed_transitions"].items():
        target = ", ".join(f"`{item}`" for item in next_statuses) or "`terminal`"
        lines.append(f"- `{status}` -> {target}")
    lines.extend(["", "## Chains", ""])
    for row in report["rows"]:
        actions = ", ".join(f"`{item}`" for item in row["recommended_actions"]) or "`none`"
        blockers = ", ".join(f"`{item}`" for item in row["blocked_reasons"]) or "`none`"
        lines.append(
            f"- `{row['chain_id']}` `{row['lane']}` `{row['readiness_tier']}`; "
            f"blockers: {blockers}; actions: {actions}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    registry = load_final_chain_registry(REGISTRY)
    report = build_final_chain_control_dashboard(registry, workspace_root=ROOT)
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
