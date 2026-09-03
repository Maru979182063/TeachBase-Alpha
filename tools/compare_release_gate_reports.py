from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "release_gate_baseline_debt_comparison.json"


def build_report(base_report_path: Path, head_report_path: Path) -> dict[str, Any]:
    base = _load(base_report_path)
    head = _load(head_report_path)
    base_failures = _failure_ids(base)
    head_failures = _failure_ids(head)
    checks = [
        {
            "name": "base_and_head_cover_same_test_count",
            "ok": int(head["summary"]["total"]) == int(base["summary"]["total"]),
            "value": {"base": base["summary"]["total"], "head": head["summary"]["total"]},
        },
        {
            "name": "head_pass_count_not_lower",
            "ok": int(head["summary"]["passed"]) >= int(base["summary"]["passed"]),
            "value": {"base": base["summary"]["passed"], "head": head["summary"]["passed"]},
        },
        {
            "name": "head_failure_set_not_expanded",
            "ok": head_failures.issubset(base_failures),
            "value": {"base": sorted(base_failures), "head": sorted(head_failures)},
        },
        {
            "name": "baseline_debt_is_explicit",
            "ok": int(base["summary"]["failed"]) > 0 and base["summary"].get("verdict") == "NO-GO",
            "value": base["summary"],
        },
    ]
    return {
        "schema_version": "release_gate_baseline_debt_comparison.v0.1",
        "status": "pass" if all(check["ok"] for check in checks) else "fail",
        "classification": "BASELINE_DEBT",
        "base_report_label": "integration_base_release_gate",
        "head_report_label": "aggregate_head_release_gate",
        "checks": checks,
    }


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise ValueError("release gate report must be a JSON object with summary")
    return payload


def _failure_ids(report: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in report.get("results", [])
        if isinstance(item, dict) and item.get("status") == "failed"
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove aggregate release-gate debt is no worse than the PR base.")
    parser.add_argument("--base-report", required=True)
    parser.add_argument("--head-report", required=True)
    args = parser.parse_args()
    report = build_report(Path(args.base_report), Path(args.head_report))
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
