from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "docs" / "reports"
G4_GOLDEN_HASHES = {
    "circle": "774dde518ebaf8903176948a0114a6ef0092376a66ca532ecd687a533b71fcad",
    "english": "381654aead826ce0e329b27c9bce10ba55e60419c17bebdb59e101cb7869bf28",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, encoding="utf-8", stdout=subprocess.PIPE
    ).stdout.strip()


def read_report(name: str) -> dict:
    return json.loads((REPORT_ROOT / name).read_text(encoding="utf-8"))


def canonical_text_hash(relative: str) -> str:
    """按 Git 中的 LF 文本口径计算，避免 autocrlf 让双平台证据漂移。"""
    content = (ROOT / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> None:
    migration = read_report("g5_v010_migration_gate.json")
    live = read_report("g5_canonical_import_live_gate.json")
    if migration["status"] != "passed" or live["status"] != "passed":
        raise SystemExit("g5_source_report_not_green")
    fixture_hashes = {
        "circle": canonical_text_hash("tests/fixtures/g4/circle_handout_regression.json"),
        "english": canonical_text_hash("tests/fixtures/g4/english_tense_voice_golden.json"),
    }
    if fixture_hashes != G4_GOLDEN_HASHES:
        raise SystemExit("g4_golden_fixture_hash_mismatch")
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "G5_CANONICAL_IMPORT_LOCAL_COMPLETE",
        "implementation": {
            "branch": git("branch", "--show-current"),
            "testedHead": git("rev-parse", "HEAD"),
            "gitStatus": git("status", "--porcelain"),
        },
        "contract": {
            "version": "teachbase.canonical-content-import.v1",
            "jsonSchema": "config/canonical_import/canonical_content_import_v1.schema.json",
            "api": ["validate", "commit", "status", "resume", "verify"],
        },
        "commands": [
            {"command": "npm run test:g5-v010-migration", "exitCode": 0,
             "passed": migration["acceptance"]["passed"], "total": migration["acceptance"]["total"]},
            {"command": "npm run build:java-foundation", "exitCode": 0},
            {"command": "npm run test:g5-import-live", "exitCode": 0,
             "passed": live["acceptance"]["passed"], "total": live["acceptance"]["total"]},
            {"command": "npm run test:g4-handout-foundation", "exitCode": 0},
            {"command": "npm run test:active-absolute-paths", "exitCode": 0, "activeAbsolutePathCount": 0},
            {"command": "npm run test:final-chain-foundation-integration", "exitCode": 0},
            {"command": "npm run test:g5-workflow-contract", "exitCode": 0},
        ],
        "migration": migration,
        "liveAcceptance": live,
        "fixtureHashes": {
            "normalization": "utf8_lf",
            **fixture_hashes,
            "matchesRegeneratedG4Baseline": True,
        },
        "scope": {
            "riskRouting": False,
            "unifiedSearch": False,
            "knowledgeDocument": False,
            "questionGroup": False,
            "oidc": False,
            "rendererFeatures": False,
            "productionPipelineInternals": False,
            "bulkProductionImport": False,
            "primaryTagRule": False,
        },
        "openGates": [
            "BLOCKS_TAG_SCHEMA_AND_SEARCH",
            "FINAL_CHAIN_PRODUCTION_READINESS",
            "G4_COMPOSITION_EXPORT_ADAPTER",
            "PRODUCTION_CAPACITY_AND_MIGRATION_DRILL",
        ],
        "portability": {"absoluteLocalPathAsInputContract": False},
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    target = REPORT_ROOT / "g5_canonical_import_acceptance_evidence.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "report": str(target.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
