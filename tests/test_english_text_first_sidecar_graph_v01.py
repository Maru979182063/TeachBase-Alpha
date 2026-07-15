from pathlib import Path

import importlib.util
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "english_text_first_v05"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pipeline = load_module("english_text_first_v05_pipeline", ROOT / "tools" / "english_text_first_v05_pipeline.py")
sidecar = load_module("english_text_first_sidecar_graph_v01", ROOT / "tools" / "english_text_first_sidecar_graph_v01.py")


def build_pipeline_fixture(tmp_path: Path) -> Path:
    out = tmp_path / "pipeline"
    summary = pipeline.run_pipeline(FIXTURE_ROOT / "english_text_first_v05.fixture_config.json", str(out))
    assert summary["model_calls_this_run"] == 0
    assert summary["runtime_import_enabled"] is False
    return out


def run_sidecar(tmp_path: Path) -> tuple[dict, Path]:
    pipeline_out = build_pipeline_fixture(tmp_path)
    sidecar_out = tmp_path / "sidecar"
    summary = sidecar.run(
        type(
            "Args",
            (),
            {
                "unit_root": str(FIXTURE_ROOT / "unit_and_v04c"),
                "vlm_root": str(FIXTURE_ROOT / "vlm_transcriber"),
                "base_root": str(pipeline_out),
                "model_gate_root": str(pipeline_out),
                "human_review": str(FIXTURE_ROOT / "human_acceptance_review" / "human_acceptance_review.json"),
                "docs": "reading_portable,writing_portable",
                "out": str(sidecar_out),
                "clean": True,
            },
        )()
    )
    return summary, sidecar_out


def test_sidecar_replays_portable_human_acceptance_items(tmp_path) -> None:
    summary, _ = run_sidecar(tmp_path)

    assert summary["human_replay_items"] == 4
    assert summary["alignment_counts"]["mismatched_direction"] == 0
    assert summary["model_calls_this_run"] == 0
    assert summary["runtime_import_enabled"] is False


def test_semantic_graph_keeps_hints_observational_only(tmp_path) -> None:
    _, out = run_sidecar(tmp_path)
    graph = json.loads((out / "semantic_graph.json").read_text(encoding="utf-8"))
    projection = json.loads((out / "projection_report.json").read_text(encoding="utf-8"))

    for doc in graph["documents"]:
        for obj in doc["semantic_objects"]:
            for hint in obj.get("normalized_hints", []):
                assert hint["not_semantic_fact"] is True
                assert hint["not_gate_input"] is True
            if obj.get("source_unit_id") and "question_like_unit" in {
                item.get("label") for item in obj.get("observations", [])
            }:
                assert obj["kind"]["kind_is_open_world"] is True
                assert obj["kind"]["open_text"] != "question_like_unit"

    statuses = {
        item["object_id"]: item["projection_status"]
        for doc in projection["docs"].values()
        for item in doc["projections"]
    }
    assert statuses["reading_portable:u_002"] == "READY"
    assert statuses["reading_portable:u_004"] == "BLOCKED"
    assert statuses["reading_portable:u_005"] == "BLOCKED"
    assert statuses["writing_portable:u_010"] == "READY_WITH_LOSS"
    for doc in projection["docs"].values():
        for item in doc["projections"]:
            assert item["used_normalized_hint_for_gate"] is False
            assert item["normalized_hints_are_observational_only"] is True


def test_predicates_are_minimal_and_source_regions_have_no_strict_mojibake(tmp_path) -> None:
    _, out = run_sidecar(tmp_path)
    graph = json.loads((out / "semantic_graph.json").read_text(encoding="utf-8"))

    predicates = {claim["predicate"] for doc in graph["documents"] for claim in doc["semantic_claims"]}
    assert predicates <= sidecar.CORE_PREDICATES
    assert sum(
        1
        for doc in graph["documents"]
        for region in doc["source_evidence"]["regions"]
        if region["has_mojibake"]
    ) == 0
    assert graph["open_world_smoke"]["non_packet_objects_checked"] > 0
    assert graph["open_world_smoke"]["dangling_claims"] == 0
