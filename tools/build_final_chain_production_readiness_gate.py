from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from teachbase.infrastructure.artifact_store import write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "artifacts" / "ci" / "final_chain_production_readiness.json"
BLOCKERS = [
    "missing_standard_cli",
    "missing_result_emission",
    "missing_checkpoint_resume",
    "missing_durable_worker_runtime",
    "missing_java_ingestion_boundary",
]


def build_report() -> dict[str, Any]:
    return {
        "schema_version": "final_chain_production_readiness.v0.1",
        "gate": "FINAL_CHAIN_PRODUCTION_READINESS",
        "status": "BLOCKED",
        "required_for_backend_foundation_integration": False,
        "continuous_production_ready": False,
        "blockers": BLOCKERS,
        "scope_guard": {
            "foundation_may_merge_while_blocked": True,
            "must_not_be_faked_with_fixtures": True,
            "must_not_expand_current_pr_scope": True,
        },
        "execution_contract": {
            "model_invoked": False,
            "database_written": False,
            "runtime_imported": False,
            "business_secrets_read": False,
        },
    }


def main() -> int:
    report = build_report()
    write_json(REPORT_JSON, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # BLOCKED 是当前预期状态；该报告不作为基础集成 required check 的失败码。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
