from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from difficulty_tagging.parallel_dimensions import (
    DIMENSION_IDS,
    aggregate_dimension_judgments,
    validate_dimension_identity,
    validator_for_dimension,
)
from difficulty_tagging.prompt_bundle import load_prompt_bundle
from difficulty_tagging.registry import load_registry, resolve_route
import difficulty_tagging.run_registered_batch_v01 as runtime


REGISTRY_PATH = ROOT / "config" / "difficulty_tagging" / "registry_v01.yaml"


def _route_and_prompt_outputs() -> tuple[object, dict[str, dict]]:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    outputs: dict[str, dict] = {}
    for node in route.dimension_nodes:
        prompt = load_prompt_bundle(ROOT / node.prompt_bundle)
        outputs[node.dimension_id] = validator_for_dimension(node.dimension_id)(
            deepcopy(prompt.value.few_shots[0].output)
        )
    return route, outputs


def _common_payload() -> dict:
    return {
        "question_id": "Q-PARALLEL-001",
        "difficulty_scheme": "difficulty.math.senior.v2",
        "rubric_version": "six_dimension_100_point_v0.1",
        "reference_population": "已完成本题所涉知识教学的普通高中同年级学生",
        "knowledge_tagging": {
            "main_knowledge_points": [
                {
                    "pk": "kp:tangent",
                    "module": "一元函数导数及其应用",
                    "knowledge_unit": "曲线上某点处的切线方程求解",
                }
            ],
            "secondary_knowledge_points": [],
        },
        "canonical_solution": {
            "shortest_solution_graph": {
                "nodes": [
                    {
                        "node_id": "E1",
                        "node_type": "frozen_step",
                        "statement": "求导并代入切点得到斜率",
                        "depends_on": [],
                        "student_visibility": "canonical_path_not_a_student_hint",
                    },
                    {
                        "node_id": "E2",
                        "node_type": "frozen_step",
                        "statement": "代入点斜式得到切线",
                        "depends_on": ["E1"],
                        "student_visibility": "canonical_path_not_a_student_hint",
                    },
                ],
                "final_node_id": "E2",
            }
        },
    }


def _normalized_outputs() -> dict[str, dict]:
    _, outputs = _route_and_prompt_outputs()
    payload = _common_payload()
    for dimension_id, result in outputs.items():
        result["question_id"] = payload["question_id"]
        if dimension_id == "knowledge_complexity":
            result["required_knowledge_units"][0]["source_node_ids"] = ["E1"]
        elif dimension_id == "calculation_complexity":
            result["independent_calculation_steps"][0]["source_node_id"] = "E1"
            result["independent_calculation_steps"][1]["source_node_id"] = "E2"
        elif dimension_id == "thinking_complexity":
            result["independent_decision_nodes"] = []
        elif dimension_id == "reading_conversion_complexity":
            result["reading_transformation"]["source_node_ids"] = ["E1"]
        elif dimension_id == "method_complexity":
            result["method_entry"]["entry_node_ids"] = ["E1"]
        elif dimension_id == "innovation_complexity":
            result["innovation_assessment"]["source_node_ids"] = ["E1"]
        outputs[dimension_id] = validate_dimension_identity(
            validator_for_dimension(dimension_id)(result),
            dimension_id=dimension_id,
            payload=payload,
        )
    return outputs


def test_all_six_dimension_prompts_have_independent_valid_contracts() -> None:
    route, outputs = _route_and_prompt_outputs()
    assert tuple(node.dimension_id for node in route.dimension_nodes) == DIMENSION_IDS
    assert set(outputs) == set(DIMENSION_IDS)
    for dimension_id, result in outputs.items():
        assert result["dimension_id"] == dimension_id
        assert "total_score" not in result
        assert "difficulty_label" not in result


def test_aggregator_calculates_scores_and_label_without_a_seventh_model() -> None:
    result = aggregate_dimension_judgments(_normalized_outputs(), payload=_common_payload())
    assert result["dimension_scores"]["knowledge_complexity"]["score"] == 2
    assert result["dimension_scores"]["calculation_complexity"]["score"] == 3
    assert result["dimension_scores"]["thinking_complexity"]["score"] == 5
    assert result["dimension_scores"]["reading_conversion_complexity"]["score"] == 3
    assert result["dimension_scores"]["method_complexity"]["score"] == 4
    assert result["dimension_scores"]["innovation_complexity"]["score"] == 3
    assert result["total_score"] == 20
    assert result["difficulty_label"] == "易"


def test_aggregator_fails_closed_when_any_dimension_is_missing() -> None:
    outputs = _normalized_outputs()
    del outputs["innovation_complexity"]
    with pytest.raises(ValueError, match="六维结果不完整"):
        aggregate_dimension_judgments(outputs, payload=_common_payload())


def test_each_dimension_rejects_unknown_frozen_graph_reference_before_aggregation() -> None:
    outputs = _normalized_outputs()
    outputs["calculation_complexity"]["independent_calculation_steps"][0][
        "source_node_id"
    ] = "MISSING"
    with pytest.raises(ValueError, match="未知冻结节点"):
        validate_dimension_identity(
            validator_for_dimension("calculation_complexity")(
                outputs["calculation_complexity"]
            ),
            dimension_id="calculation_complexity",
            payload=_common_payload(),
        )


def test_runtime_calls_six_dimension_nodes_and_no_comprehensive_model(monkeypatch) -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    payload = _common_payload()
    payload.update(
        {
            "question": {"stem": "求切线", "options": [], "answer": "", "analysis": "", "material": "", "visual_pages": []},
            "knowledge_tagging": {
                "main_knowledge_points": [
                    {
                        "pk": "kp:tangent",
                        "module": "一元函数导数及其应用",
                        "knowledge_unit": "曲线上某点处的切线方程求解",
                    }
                ],
                "secondary_knowledge_points": [],
            },
        }
    )
    outputs = _normalized_outputs()
    calls: list[str] = []
    all_six_started = Barrier(6, timeout=3)

    def fake_call_json_model(**kwargs):
        dimension_id = kwargs["user_payload"]["dimension_id"]
        calls.append(dimension_id)
        all_six_started.wait()
        parsed = kwargs["validator"](deepcopy(outputs[dimension_id]))
        return {"called": True, "ok": True, "parsed": parsed, "attempts": [{"ok": True}]}

    monkeypatch.setattr(runtime, "call_json_model", fake_call_json_model)
    provider = loaded.value.provider(route.provider_id)
    traces, result = runtime.run_parallel_dimension_nodes(
        payload=payload,
        route=route,
        provider=provider,
        api_key="test-key",
        prior_trace=None,
    )
    assert set(calls) == set(DIMENSION_IDS)
    assert len(calls) == 6
    assert len(traces) == 6
    assert result is not None
    assert result["total_score"] == 20


def test_retry_reuses_successful_dimension_nodes_and_calls_only_failed_one(monkeypatch) -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    payload = _common_payload()
    payload["question"] = {"stem": "求切线", "options": [], "answer": "", "analysis": "", "material": "", "visual_pages": []}
    outputs = _normalized_outputs()
    prior_nodes: dict[str, dict] = {}
    failed_dimension = "innovation_complexity"
    for node in route.dimension_nodes:
        prompt = load_prompt_bundle(ROOT / node.prompt_bundle)
        if node.dimension_id == failed_dimension:
            continue
        prior_nodes[node.node_id] = {
            "node_id": node.node_id,
            "dimension_id": node.dimension_id,
            "prompt_sha256": prompt.sha256,
            "model_call": {"called": True, "ok": True, "parsed": outputs[node.dimension_id]},
        }
    calls: list[str] = []

    def fake_call_json_model(**kwargs):
        dimension_id = kwargs["user_payload"]["dimension_id"]
        calls.append(dimension_id)
        parsed = kwargs["validator"](deepcopy(outputs[dimension_id]))
        return {"called": True, "ok": True, "parsed": parsed, "attempts": [{"ok": True}]}

    monkeypatch.setattr(runtime, "call_json_model", fake_call_json_model)
    traces, result = runtime.run_parallel_dimension_nodes(
        payload=payload,
        route=route,
        provider=loaded.value.provider(route.provider_id),
        api_key="test-key",
        prior_trace={"dimension_nodes": prior_nodes},
    )
    assert calls == [failed_dimension]
    assert sum(bool(trace["reused_from_prior_trace"]) for trace in traces.values()) == 5
    assert result is not None
