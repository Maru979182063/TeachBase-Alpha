from pathlib import Path

import importlib.util
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "english_text_first_v05"
MODULE_PATH = ROOT / "tools" / "english_text_first_v05_pipeline.py"
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
            "parent_hint": "question 1",
        },
        {"unit_id": "u_012", "unit_type": "question_like_unit"},
    ]

    matched = pipeline.solution_units_for(units, 0, "u_010")

    assert [unit["unit_id"] for unit in matched] == ["u_011"]


def test_portable_fixture_pipeline_has_expected_ready_hold_and_visual_states(tmp_path) -> None:
    out = tmp_path / "english_v05"
    summary = pipeline.run_pipeline(FIXTURE_ROOT / "english_text_first_v05.fixture_config.json", str(out))

    assert summary["model_calls_this_run"] == 0
    assert summary["runtime_import_enabled"] is False
    reading_packets = json.loads((out / "reading_portable" / "question_packet_candidates.json").read_text(encoding="utf-8"))
    writing_packets = json.loads((out / "writing_portable" / "question_packet_candidates.json").read_text(encoding="utf-8"))
    assets = json.loads((out / "writing_portable" / "asset_manifest.json").read_text(encoding="utf-8"))

    packets = {packet["packet_id"]: packet for packet in reading_packets["packets"] + writing_packets["packets"]}
    assert packets["reading_portable_u_002"]["release_status"] == "READY"
    assert packets["reading_portable_u_004"]["release_status"] == "HOLD"
    assert "missing_solution_unit" in packets["reading_portable_u_004"]["hold_reasons"]
    assert packets["reading_portable_u_005"]["release_status"] == "HOLD"
    assert "question_unit_not_complete" in packets["reading_portable_u_005"]["hold_reasons"]
    assert packets["writing_portable_u_010"]["release_status"] == "HOLD"
    assert "visual_asset_needs_precise_bbox" in packets["writing_portable_u_010"]["hold_reasons"]
    assert assets["asset_count"] == 1
    assert assets["assets"][0]["needs_precise_bbox"] is True
    assert (out / assets["assets"][0]["asset_path"]).exists()


def test_registry_declares_english_v05_isolated() -> None:
    registry_path = ROOT / "config" / "pipeline_registry.yaml"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = {item["pipeline_id"]: item for item in registry["pipelines"]}

    entry = entries["english_text_first_v05"]

    assert entry["status"] == "experimental"
    assert entry["runtime_import_policy"]["default_enabled"] is False
    assert entry["database_write_policy"]["default_enabled"] is False
    assert "outputs/split_v03" in entry["forbidden_write_roots"]
