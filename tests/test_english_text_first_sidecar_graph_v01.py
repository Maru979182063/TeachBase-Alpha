from pathlib import Path

import importlib.util
import json
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "english_text_first_sidecar_graph_v01.py"
SPEC = importlib.util.spec_from_file_location("english_text_first_sidecar_graph_v01", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sidecar = importlib.util.module_from_spec(SPEC)
sys.modules["english_text_first_sidecar_graph_v01"] = sidecar
SPEC.loader.exec_module(sidecar)


def test_sidecar_replays_17_human_acceptance_items(tmp_path) -> None:
    out = tmp_path / "sidecar"
    summary = sidecar.run(
        type(
            "Args",
            (),
            {
                "unit_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v04c_hardened_enum_norm_full8_lite_20260715",
                "vlm_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/vlm_transcriber_full8_lite_20260715",
                "base_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/base",
                "model_gate_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/model_gate",
                "human_review": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json",
                "docs": "reading_argumentative,grammar_clauses,writing_invitation",
                "out": str(out),
                "clean": True,
            },
        )()
    )

    assert summary["human_replay_items"] == 17
    assert summary["alignment_counts"]["mismatched_direction"] == 0
    assert summary["model_calls_this_run"] == 0
    assert summary["runtime_import_enabled"] is False


def test_semantic_graph_keeps_hints_observational_only(tmp_path) -> None:
    out = tmp_path / "sidecar"
    sidecar.run(
        type(
            "Args",
            (),
            {
                "unit_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v04c_hardened_enum_norm_full8_lite_20260715",
                "vlm_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/vlm_transcriber_full8_lite_20260715",
                "base_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/base",
                "model_gate_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/model_gate",
                "human_review": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json",
                "docs": "reading_argumentative,grammar_clauses,writing_invitation",
                "out": str(out),
                "clean": True,
            },
        )()
    )
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

    for doc in projection["docs"].values():
        for item in doc["projections"]:
            assert item["used_normalized_hint_for_gate"] is False
            assert item["normalized_hints_are_observational_only"] is True


def test_predicates_are_minimal_and_source_regions_have_no_strict_mojibake(tmp_path) -> None:
    out = tmp_path / "sidecar"
    sidecar.run(
        type(
            "Args",
            (),
            {
                "unit_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v04c_hardened_enum_norm_full8_lite_20260715",
                "vlm_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/vlm_transcriber_full8_lite_20260715",
                "base_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/base",
                "model_gate_root": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/model_gate",
                "human_review": "outputs/english_text_first_pipeline_v02_spec_20260715/regression/endpoint_v05_model_prodlike_20260715_155207/human_acceptance_review/human_acceptance_review.json",
                "docs": "reading_argumentative,grammar_clauses,writing_invitation",
                "out": str(out),
                "clean": True,
            },
        )()
    )
    graph = json.loads((out / "semantic_graph.json").read_text(encoding="utf-8"))

    predicates = {claim["predicate"] for doc in graph["documents"] for claim in doc["semantic_claims"]}
    assert predicates <= sidecar.CORE_PREDICATES
    script_text = Path(sidecar.__file__).read_text(encoding="utf-8")
    assert "family ==" not in script_text
    assert "packet_family" not in script_text
    assert sum(
        1
        for doc in graph["documents"]
        for region in doc["source_evidence"]["regions"]
        if region["has_mojibake"]
    ) == 0
    assert graph["open_world_smoke"]["non_packet_objects_checked"] > 0
    assert graph["open_world_smoke"]["dangling_claims"] == 0
