from __future__ import annotations

import json
from pathlib import Path

from tools.run_semantic_role_effectiveness_eval import DEFAULT_CASES, run_eval


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = ROOT / "tests" / "golden" / "semantic_role_effectiveness_phase2a_c2d874a"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize(value):
    volatile_keys = {"created_at", "started_at", "finished_at"}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in volatile_keys:
                result[key] = "<TIMESTAMP>"
            elif key == "run_id":
                result[key] = "<RUN_ID>"
            elif key == "out_dir":
                result[key] = "<OUT_DIR>"
            elif key in {"cases_path", "schema_path"}:
                text = str(item).replace("\\", "/")
                marker = "tests/fixtures/semantic_role_effectiveness_v01/"
                result[key] = marker + text.split(marker, 1)[1] if marker in text else "<WORKSPACE_PATH>"
            else:
                result[key] = normalize(item)
        return result
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        text = value.replace("\\", "/")
        if "C:/Users/" in text or "/tmp/" in text or "Temp/" in text:
            marker = "tests/fixtures/semantic_role_effectiveness_v01/"
            return marker + text.split(marker, 1)[1] if marker in text else "<PATH>"
        return text.replace("phase2a_golden", "<RUN_ID>")
    return value


def test_semantic_role_eval_matches_committed_c2d_golden(tmp_path: Path) -> None:
    manifest = load_json(GOLDEN_ROOT / "manifest.json")
    assert manifest["baseline_commit"] == "c2d874a487a5dfaefa4ba76b7634ab883d2d2e24"
    assert manifest["baseline_exit_code"] == 20

    exit_code, summary = run_eval(cases_path=DEFAULT_CASES, out_root=tmp_path, run_id="phase2a_golden")

    assert exit_code == 20
    assert summary["status"] == "SEMANTIC_ROLE_EVALUATION_DATASET_REVIEW_REQUIRED"

    out_dir = tmp_path / "phase2a_golden"
    compared = 0
    for row in manifest["files"]:
        source_path = out_dir / row["source"]
        golden_path = GOLDEN_ROOT / row["canonical"]
        assert source_path.exists(), row["source"]
        actual = normalize(load_json(source_path))
        expected = load_json(golden_path)
        assert actual == expected, row["source"]
        compared += 1

    assert compared == manifest["file_count"] == 18
    assert "C:\\Users\\" not in json.dumps(manifest, ensure_ascii=False)
    assert "C:/Users/" not in json.dumps(manifest, ensure_ascii=False)
