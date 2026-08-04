from __future__ import annotations

import argparse
import json
from pathlib import Path

import docx_question_part_twostage_probe_v01 as twostage


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "docx_question_part_long_normalizer_v01.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="DOCX long question part normalizer v0.1.")
    parser.add_argument("--paragraph-stream", required=True, type=Path)
    parser.add_argument("--block-tags", required=True, type=Path)
    parser.add_argument("--membership-groups", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--group-ids", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-root", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-group-attempts", type=int, default=0)
    parser.add_argument("--solution-policy-hint", default="unknown", choices=["required", "optional", "absent_expected", "unknown"])
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    summary = twostage.run(args)
    summary["schema_version"] = "docx_question_part_long_normalizer_summary.v0.1"
    summary["node"] = "docx_question_part_long_normalizer_v01"
    summary["status"] = summary.get("status") or "unknown"
    artifacts = summary.get("artifacts") or {}
    part_path = Path(str(artifacts.get("question_part_normalizations") or ""))
    if part_path.exists():
        twostage.write_json(part_path.with_name("summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
