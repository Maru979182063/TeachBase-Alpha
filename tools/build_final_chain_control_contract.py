from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from teachbase.final_chains import build_final_chain_control_contract, load_final_chain_registry
from teachbase.infrastructure.artifact_store import write_json, write_text

REGISTRY = ROOT / "config" / "final_chain_registry.yaml"
REPORT_JSON = ROOT / "docs" / "reports" / "final_chain_control_contract_20260804.json"
REPORT_MD = ROOT / "docs" / "reports" / "final_chain_control_contract_20260804.md"


def build_report() -> dict[str, Any]:
    registry = load_final_chain_registry(REGISTRY)
    return build_final_chain_control_contract(registry)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Final Chain Control Contract 2026-08-04",
        "",
        f"Schema: `{report['schema_version']}`",
        f"Consumer: `{report['consumer_role']}`",
        f"Chains: `{', '.join(report['chain_ids'])}`",
        "",
        "## Control Plane",
        "",
    ]
    for key, value in report["control_plane_contract"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Forbidden Side Effects", ""])
    for key, value in report["forbidden_side_effects"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Commands", ""])
    for key, value in report["commands"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("All paths are relative git paths; no local absolute path is part of the reproducible input contract.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    write_text(REPORT_MD, render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
