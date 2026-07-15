from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from teachbase.semantic_role.candidate_manifest import write_candidate_manifest as package_write_candidate_manifest
from teachbase.semantic_role.contracts import OUTPUT_FILES, REQUIRED_FIELDS, default_cases_path, schema_path
from teachbase.semantic_role.evaluator import case_to_node as _case_to_node
from teachbase.semantic_role.evaluator import load_cases, run_eval as package_run_eval, validate_cases as package_validate_cases
from teachbase.semantic_role.cli import main as package_main

try:
    from .semantic_role_eval_legacy_predictor import predict_case as package_predict_case
except ImportError:
    from semantic_role_eval_legacy_predictor import predict_case as package_predict_case

DEFAULT_CASES = default_cases_path(ROOT)
SCHEMA_PATH = schema_path(ROOT)


def validate_cases(cases: list[dict]) -> list[str]:
    return package_validate_cases(cases, ROOT)


def predict_case(case: dict, run_id: str) -> dict:
    return package_predict_case(case, run_id, ROOT)


def write_candidate_manifest(candidate_roots: list[Path], out_path: Path) -> dict:
    return package_write_candidate_manifest(candidate_roots, out_path, ROOT)


def run_eval(*, cases_path: Path, out_root: Path, run_id: str | None = None, candidate_manifest_path: Path | None = None) -> tuple[int, dict]:
    return package_run_eval(
        cases_path=cases_path,
        out_root=out_root,
        workspace_root=ROOT,
        predictor=package_predict_case,
        run_id=run_id,
        candidate_manifest_path=candidate_manifest_path,
    )


def main() -> int:
    return package_main(predictor=package_predict_case, workspace_root=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
