from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_semantic_shadow_review_baseline import build_baseline
from tools.semantic_shadow_compare import compare_artifact_sets


READY_ARTIFACTS = [
    "docs/english/assignments.json",
    "docs/english/semantic_nodes.json",
    "docs/english/audit_report.json",
    "legacy_bridge_questions.json",
    "review_repair_pool.json",
]
REVIEW_ARTIFACTS = [
    "docs/synthetic_review/assignments.json",
    "docs/synthetic_review/semantic_nodes.json",
    "docs/synthetic_review/audit_report.json",
    "legacy_bridge_questions.json",
    "review_repair_pool.json",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_ready_manifest() -> dict[str, Any]:
    path = ROOT / "outputs" / "pipeline_baseline_snapshot" / "control_plane_20260714_v02" / "baseline_manifest.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_ready_path(out_root: Path) -> dict[str, Any]:
    manifest = _load_ready_manifest()
    baseline = manifest["deterministic_baselines"][0]
    pdf_path = Path(baseline["input"]["path"])
    if not pdf_path.exists():
        raise FileNotFoundError(f"ready_path_input_missing:{pdf_path}")
    baseline_root = ROOT / "outputs" / "pipeline_baseline_snapshot" / "control_plane_20260714_v02" / "deterministic_english_mock_p5_6"
    current_root = out_root / "ready_path_real_rerun" / "deterministic_english_mock_p5_6"
    if current_root.exists():
        raise FileExistsError(f"ready_path_real_rerun_output_exists:{current_root}")
    command = [
        sys.executable,
        "-m",
        "tools.split_v03_quick_debug",
        "--pdf",
        str(pdf_path),
        "--doc-key",
        "english",
        "--pages",
        "5,6",
        "--out",
        str(current_root),
        "--provider",
        "mock",
        "--max-vlm-calls",
        "0",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            "ready_path_real_rerun_failed\n"
            f"command={' '.join(command)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    report = compare_artifact_sets(baseline_root, current_root, READY_ARTIFACTS, roots=[ROOT, baseline_root, current_root])
    return {
        "baseline_root": str(baseline_root),
        "current_root": str(current_root),
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "report": report,
    }


def run_review_path(out_root: Path) -> dict[str, Any]:
    baseline_root = ROOT / "outputs" / "pipeline_baseline_snapshot" / "semantic_shadow_review_path_20260714_v01"
    current_root = out_root / "review_path_real_rerun" / "semantic_shadow_review_path_20260714_v01"
    if current_root.exists():
        raise FileExistsError(f"review_path_real_rerun_output_exists:{current_root}")
    build_baseline(current_root)
    report = compare_artifact_sets(baseline_root, current_root, REVIEW_ARTIFACTS, roots=[ROOT, baseline_root, current_root])
    return {
        "baseline_root": str(baseline_root),
        "current_root": str(current_root),
        "command": [
            sys.executable,
            "tools/build_semantic_shadow_review_baseline.py",
            "--out",
            str(current_root),
        ],
        "report": report,
    }


def run_validation(out_root: Path) -> dict[str, Any]:
    out_root.mkdir(parents=True, exist_ok=True)
    ready = run_ready_path(out_root)
    review = run_review_path(out_root)
    ready_report_path = out_root / "ready_path_real_rerun_non_interference_report.json"
    review_report_path = out_root / "review_path_real_rerun_non_interference_report.json"
    _write_json(ready_report_path, ready["report"])
    _write_json(review_report_path, review["report"])
    summary = {
        "schema_version": "semantic_shadow_real_rerun_validation.v0.1",
        "status": "PASS" if ready["report"]["equality"] and review["report"]["equality"] else "FAIL",
        "paid_model_invoked": False,
        "ready_path": {
            "baseline_root": ready["baseline_root"],
            "current_root": ready["current_root"],
            "command": ready["command"],
            "equality": ready["report"]["equality"],
            "compared_artifact_count": ready["report"]["compared_artifact_count"],
            "report_path": str(ready_report_path),
        },
        "review_path": {
            "baseline_root": review["baseline_root"],
            "current_root": review["current_root"],
            "command": review["command"],
            "equality": review["report"]["equality"],
            "compared_artifact_count": review["report"]["compared_artifact_count"],
            "report_path": str(review_report_path),
        },
    }
    _write_json(out_root / "real_rerun_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run experiments-off real rerun validation for Semantic Role Shadow.")
    parser.add_argument("--out-root", default="outputs/semantic_role_shadow_effectiveness_validation_20260715")
    args = parser.parse_args()
    summary = run_validation(Path(args.out_root))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
