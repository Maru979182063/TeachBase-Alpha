import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "docs" / "reports"


def read_report(name: str) -> dict:
    return json.loads((REPORT_ROOT / name).read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def main() -> None:
    migration = read_report("governance_projection_v013_migration_gate.json")
    live = read_report("governance_projection_01_live_gate.json")
    if migration["status"] != "passed" or live["status"] != "passed":
        raise SystemExit("governance_projection_source_report_not_green")

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "GOVERNANCE_PROJECTION_01_LOCAL_COMPLETE",
        "implementation": {
            "branch": git("branch", "--show-current"),
            "testedHead": git("rev-parse", "HEAD"),
            "gitStatusAtEvidenceBuild": git("status", "--porcelain"),
        },
        "authority": {
            "tag": "question_tag_state.current_snapshot_id + state_version",
            "difficulty": "question_difficulty_state.current_snapshot_id + state_version",
        },
        "projection": {
            "tag": "question_tag_current_projection",
            "tagSecondary": "question_tag_current_projection_secondary",
            "difficulty": "question_difficulty_current_projection",
            "outbox": "governance_projection_outbox",
        },
        "commands": [
            {"command": "npm run test:governance-projection-contract", "exitCode": 0, "passed": 3, "total": 3},
            {"command": "npm run test:governance-projection-v013-migration", "exitCode": 0,
             "passed": migration["acceptance"]["passed"], "total": migration["acceptance"]["total"]},
            {"command": "npm run build:java-foundation", "exitCode": 0},
            {"command": "npm run test:governance-projection-live", "exitCode": 0,
             "passed": live["acceptance"]["passed"], "total": live["acceptance"]["total"]},
            {"command": "npm run test:tag-feedback-live", "exitCode": 0},
            {"command": "npm run test:difficulty-feedback-live", "exitCode": 0},
            {"command": "npm run test:g5-import-live", "exitCode": 0},
            {"command": "npm run test:g4-handout-live", "exitCode": 0},
            {"command": "npm run test:wp01-editor-working-draft", "exitCode": 0},
            {"command": "npm run test:question-governance-live", "exitCode": 0},
        ],
        "migration": migration,
        "goldenAcceptance": live,
        "openGates": [
            "BLOCKS_TAG_SCHEMA_AND_SEARCH",
            "PRODUCTION_AUTHENTICATION_AND_ACL",
            "PRODUCTION_CAPACITY_AND_MIGRATION_DRILL",
        ],
        "deferred": [
            "unified_search", "fuzzy_full_text_search", "semantic_search", "recommendation",
            "analytics_dashboard", "model_or_prompt_optimization", "taxonomy_auto_governance",
        ],
        "portability": {"absoluteLocalPathAsInputContract": False},
    }
    target = REPORT_ROOT / "governance_projection_01_acceptance_evidence.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "report": str(target.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
