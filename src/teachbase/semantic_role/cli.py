from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from teachbase.semantic_role.candidate_manifest import write_candidate_manifest
from teachbase.semantic_role.contracts import default_cases_path
from teachbase.semantic_role.evaluator import PredictCase, run_eval


def build_parser(workspace_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Semantic Role Effectiveness Evaluation v0.1.")
    parser.add_argument("--cases", default=str(default_cases_path(workspace_root)))
    parser.add_argument("--out-root", default="outputs/semantic_role_effectiveness_eval")
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-manifest")
    parser.add_argument("--discover-candidate-root", action="append", default=[])
    parser.add_argument("--candidate-manifest-out")
    return parser


def main(*, predictor: PredictCase, workspace_root: Path, argv: list[str] | None = None) -> int:
    parser = build_parser(workspace_root)
    args = parser.parse_args(argv)
    if args.discover_candidate_root:
        if not args.candidate_manifest_out:
            parser.error("--candidate-manifest-out is required with --discover-candidate-root")
        manifest = write_candidate_manifest(
            [Path(root) for root in args.discover_candidate_root],
            Path(args.candidate_manifest_out),
            workspace_root,
        )
        print(
            json.dumps(
                {
                    "status": "CANDIDATE_MANIFEST_WRITTEN",
                    "candidate_count": manifest["candidate_count"],
                    "candidate_manifest": args.candidate_manifest_out,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    exit_code, summary = run_eval(
        cases_path=Path(args.cases),
        out_root=Path(args.out_root),
        workspace_root=workspace_root,
        predictor=predictor,
        run_id=args.run_id,
        candidate_manifest_path=Path(args.candidate_manifest) if args.candidate_manifest else None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


def summary_payload(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2)
