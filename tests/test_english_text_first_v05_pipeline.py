from pathlib import Path

import importlib.util
import json
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "english_text_first_v05_pipeline.py"
SPEC = importlib.util.spec_from_file_location("english_text_first_v05_pipeline", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
pipeline = importlib.util.module_from_spec(SPEC)
sys.modules["english_text_first_v05_pipeline"] = pipeline
SPEC.loader.exec_module(pipeline)


def test_normalize_numeric_block_ref_to_line_ref() -> None:
    page_blocks = {8: [{"line_ref": "p008:b6", "text": "sample"}]}

    assert pipeline.normalize_ref("p008:6", page_blocks) == "p008:b6"


def test_solution_units_fallback_uses_next_solution_before_next_question() -> None:
    units = [
        {"unit_id": "u_010", "unit_type": "question_like_unit"},
        {
            "unit_id": "u_011",
            "unit_type": "solution_unit",
            "relation_to_parent": "solution_for",
            "parent_hint": "对应第1题",
        },
        {"unit_id": "u_012", "unit_type": "question_like_unit"},
    ]

    matched = pipeline.solution_units_for(units, 0, "u_010")

    assert [unit["unit_id"] for unit in matched] == ["u_011"]


def test_registry_declares_english_v05_isolated() -> None:
    registry_path = Path(__file__).resolve().parents[1] / "config" / "pipeline_registry.yaml"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = {item["pipeline_id"]: item for item in registry["pipelines"]}

    entry = entries["english_text_first_v05"]

    assert entry["status"] == "experimental"
    assert entry["runtime_import_policy"]["default_enabled"] is False
    assert "outputs/split_v03" in entry["forbidden_write_roots"]
