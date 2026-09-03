from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.final_chains import build_environment_interaction_contract, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_environment_contract_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_environment_contract_20260804.md"


def build_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    return build_environment_interaction_contract(registry, workspace_root=ROOT)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Environment Contract 2026-08-04",
        "",
        f"Status: `{report['status']}`",
        f"Schema: `{report['schema_version']}`",
        f"Ready chains: `{', '.join(report['ready_chain_ids'])}`",
        f"Blocked chains: `{', '.join(report['blocked_chain_ids'])}`",
        "",
        "## Filesystem",
        "",
        f"- `write_scope`: `{', '.join(report['filesystem_contract']['write_scope'])}`",
        f"- `read_scope`: `{report['filesystem_contract']['read_scope']}`",
        "",
        "## Profiles",
        "",
    ]
    for profile in report["profiles"]:
        lines.append(
            f"- `{profile['chain_id']}`: `{profile['status']}`, gate `{profile['environment_gate']}`, "
            f"required paths `{profile['required_path_present_count']}/{profile['required_path_count']}`"
        )
    lines.extend(["", "All paths are repository-relative contract paths; no local absolute path is reproducible input.", ""])
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
