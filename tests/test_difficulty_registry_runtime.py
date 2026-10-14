from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from difficulty_tagging.prompt_bundle import load_prompt_bundle
from difficulty_tagging.registry import RouteNotFoundError, load_registry, resolve_route
from difficulty_tagging.contracts import (
    normalize_canonical_projection,
    validate_canonical_projection_shape,
)
from difficulty_tagging.run_registered_batch_v01 import (
    gate_model_result,
    load_plan_selection,
    run_batch,
    validate_knowledge_point_provenance,
)
from difficulty_tagging.tag_difficulty_v01 import compact_knowledge_result
from difficulty_tagging.build_staged_eval_plan_v01 import build_plan
from difficulty_tagging.evaluate_pdf_gold_holdout_v01 import load_selected_ids
from difficulty_tagging.evaluate_repeatability_v01 import evaluate_repeatability
from knowledge_tagging.model_api import (
    ModelTransportSettings,
    call_json_model,
    close_model_transport,
    configure_model_transport,
)


REGISTRY_PATH = ROOT / "config" / "difficulty_tagging" / "registry_v01.yaml"


def normalize_prompt_example(example) -> dict:
    shaped = validate_canonical_projection_shape(deepcopy(example.output))
    return normalize_canonical_projection(
        shaped,
        deepcopy(example.input["canonical_solution"]["shortest_solution_graph"]),
    )


def test_registry_resolves_enabled_math_route_exactly() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(
        loaded.value,
        {"subject": "数学", "stage": "高中", "question_type": "集合选择题"},
    )
    assert route.route_id == "math.senior.default.v1"
    assert route.label_scheme == "five_band.v1"
    assert route.result_adapter == "math_canonical_projection_v01"
    assert route.boundary_review_margin_points == 2


def test_label_boundary_is_routed_to_review() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    result = {
        "difficulty_scheme": route.difficulty_scheme,
        "rubric_version": route.rubric_version,
        "reference_population": route.reference_population,
        "difficulty_confidence": 0.95,
        "release_recommendation": "accept_provisional",
        "review_flags": [],
        "difficulty_source": "model_predicted",
        "total_score": 66,
    }
    status, errors = gate_model_result(result, route, live=True)
    assert status == "needs_review"
    assert errors == ["score_near_label_boundary"]


def test_draft_english_route_is_not_runnable() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    context = {"subject": "英语", "stage": "高中", "question_type": "阅读理解"}
    with pytest.raises(RouteNotFoundError):
        resolve_route(loaded.value, context)
    draft = resolve_route(loaded.value, context, include_draft=True)
    assert draft.route_id == "english.senior.reading.v1"
    assert not draft.enabled


def test_math_prompt_is_yaml_and_has_a_reviewed_few_shot() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    assert prompt.value.prompt_id == "math_senior_six_dimension_v01"
    assert [item.example_id for item in prompt.value.few_shots] == ["math_easy_direct_chain_seed_002"]
    assert prompt.value.few_shots[0].provenance["review_status"] == "expert_seed"
    result = normalize_prompt_example(prompt.value.few_shots[0])
    validate_knowledge_point_provenance(result, prompt.value.few_shots[0].input)


def test_compact_knowledge_result_exposes_level3_unit_and_level1_module() -> None:
    compact = compact_knowledge_result(
        {
            "main_knowledge_points": [
                {
                    "pk": "kp:1",
                    "path": "统计与概率 > 概率 > 随机变量及其分布 > 离散型随机变量的分布列",
                    "evidence": "需要建立分布列",
                }
            ],
            "secondary_knowledge_points": [],
        }
    )
    point = compact["main_knowledge_points"][0]
    assert point["module"] == "统计与概率"
    assert point["knowledge_unit"] == "随机变量及其分布"
    assert point["leaf_name"] == "离散型随机变量的分布列"
    assert point["path_levels"] == [
        "统计与概率",
        "概率",
        "随机变量及其分布",
        "离散型随机变量的分布列",
    ]


def test_math_provenance_gate_rejects_invented_knowledge_point() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = prompt.value.few_shots[0].input
    raw = deepcopy(prompt.value.few_shots[0].output)
    raw["semantic_reasoning"]["required_knowledge_units"][0]["registered_pk"] = "invented:pk"
    shaped = validate_canonical_projection_shape(raw)
    result = normalize_canonical_projection(
        shaped,
        prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"],
    )
    with pytest.raises(ValueError, match="上游未发布"):
        validate_knowledge_point_provenance(result, payload)


def test_math_provenance_gate_rejects_model_authored_module_or_unit_name() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = prompt.value.few_shots[0].input
    raw = deepcopy(prompt.value.few_shots[0].output)
    raw["semantic_reasoning"]["required_knowledge_units"][0]["module"] = "模型自造模块"
    shaped = validate_canonical_projection_shape(raw)
    result = normalize_canonical_projection(
        shaped,
        payload["canonical_solution"]["shortest_solution_graph"],
    )
    with pytest.raises(ValueError, match="module 必须原样来自上游"):
        validate_knowledge_point_provenance(result, payload)

    raw = deepcopy(prompt.value.few_shots[0].output)
    raw["semantic_reasoning"]["required_knowledge_units"][0]["name"] = "四级叶子标题"
    shaped = validate_canonical_projection_shape(raw)
    result = normalize_canonical_projection(
        shaped,
        payload["canonical_solution"]["shortest_solution_graph"],
    )
    with pytest.raises(ValueError, match="name 必须使用上游三级标题"):
        validate_knowledge_point_provenance(result, payload)


def test_semantic_contract_rejects_cyclic_solution_graph() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    graph = deepcopy(prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"])
    graph["nodes"][0]["depends_on"] = ["E2"]
    with pytest.raises(ValueError, match="无环图"):
        normalize_canonical_projection(payload, graph)


def test_semantic_contract_rejects_unknown_reading_node() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    payload["semantic_reasoning"]["reading_transformation"]["source_node_ids"] = ["missing"]
    graph = prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"]
    with pytest.raises(ValueError, match="canonical_solution 之外"):
        normalize_canonical_projection(payload, graph)


def test_semantic_contract_rejects_unknown_decision_node() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    payload["semantic_reasoning"]["independent_decision_nodes"] = [
        {
            "node_id": "missing",
            "decision_type": "方法选择",
            "decision": "选择一条不存在的路线",
            "alternatives_considered": [],
            "why_indispensable": "用于验证引用门禁",
            "evidence": ["测试"],
        }
    ]
    graph = prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"]
    with pytest.raises(ValueError, match="canonical_solution 之外"):
        normalize_canonical_projection(payload, graph)


def test_semantic_contract_preserves_model_authored_categories_and_normalizes_text_lists() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    method_entry = payload["semantic_reasoning"]["method_entry"]
    method_entry["entry_type"] = "标准回忆与显式设问共同触发"
    method_entry["student_visible_cues"] = "题面直接要求曲线在给定点的切线方程"
    graph = deepcopy(prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"])
    graph["nodes"][0]["node_type"] = "冻结步骤：定义直接调用"
    result = normalize_canonical_projection(payload, graph)
    assert result["semantic_reasoning"]["method_entry"]["entry_type"] == "标准回忆与显式设问共同触发"
    assert result["semantic_reasoning"]["method_entry"]["student_visible_cues"] == [
        "题面直接要求曲线在给定点的切线方程"
    ]


def test_semantic_v04_contract_binds_model_semantics_to_numeric_bands() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    payload["semantic_reasoning"]["method_entry"]["recommended_band"] = 5
    graph = prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"]
    result = normalize_canonical_projection(payload, graph)
    assert result["dimension_scores"]["method_complexity"] == {
        "band": 5,
        "score": 20,
        "judgment": "设问直接触发唯一标准链，多步公式串联仍无方法筛选或模板适配",
        "evidence": ["题面直接要求曲线在给定点的切线方程"],
    }


def test_semantic_v04_contract_counts_implicit_prerequisite_without_forging_pk() -> None:
    loaded = load_registry(REGISTRY_PATH, ROOT)
    route = resolve_route(loaded.value, {"subject": "数学", "stage": "高中"})
    prompt = load_prompt_bundle(ROOT / route.prompt_bundle)
    payload = deepcopy(prompt.value.few_shots[0].output)
    payload["semantic_reasoning"]["required_knowledge_units"].append(
        {
            "unit_id": "k2",
            "name": "平方根化简",
            "module": "代数运算",
            "source": "implicit_prerequisite",
            "registered_pk": None,
            "source_node_ids": ["E1"],
            "necessity": "得到最终数值所需的直接化简",
        }
    )
    graph = prompt.value.few_shots[0].input["canonical_solution"]["shortest_solution_graph"]
    result = normalize_canonical_projection(payload, graph)
    result = validate_knowledge_point_provenance(result, prompt.value.few_shots[0].input)
    assert result["semantic_reasoning"]["required_knowledge_units"][1]["registered_pk"] is None
    assert result["dimension_scores"]["knowledge_complexity"]["score"] == 6
    assert result["total_score"] == 24
    assert result["release_recommendation"] == "manual_review"
    assert "implicit_knowledge_unit_unregistered" in result["review_flags"]


def test_dry_run_writes_resumable_trace_and_summary(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "Q-REGISTRY-001",
                    "status": "tagged",
                    "subject": "数学",
                    "stage": "高中",
                    "question": {
                        "stem": "已知复数 z=-1-i，求 |z|。",
                        "options": [],
                        "answer": "√2",
                        "analysis": "代入复数模长公式。",
                    },
                    "model_concepts": {
                        "schema": "knowledge_open_concepts_role_hypotheses_v0.3",
                        "question_facts": {
                            "target_object": "复数的模",
                            "asked_operation": "计算",
                            "scope": "高中数学",
                        },
                        "task_evidence": [
                            {
                                "id": "E1",
                                "fact": "将实部和虚部代入模长公式并化简",
                                "depends_on": [],
                            }
                        ],
                    },
                    "final_result": {
                        "schema": "knowledge_tagging_result_v1",
                        "decision_profile": {"release_decision": "accept"},
                        "main_knowledge_points": [
                            {"pk": "P1", "path": "复数 > 复数的模", "evidence": "直接求模"}
                        ],
                        "secondary_knowledge_points": [],
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    first = run_batch(
        input_path=input_path,
        registry_path=REGISTRY_PATH,
        output_dir=output_dir,
        selected_ids=set(),
        use_model=False,
        resume=True,
        offline_results={},
    )
    second = run_batch(
        input_path=input_path,
        registry_path=REGISTRY_PATH,
        output_dir=output_dir,
        selected_ids=set(),
        use_model=False,
        resume=True,
        offline_results={},
    )
    assert first["status_counts"] == {"ready_for_model": 1}
    assert second["status_counts"] == first["status_counts"]
    trace_paths = list((output_dir / "traces").glob("*.difficulty_trace.json"))
    assert len(trace_paths) == 1
    trace = json.loads(trace_paths[0].read_text(encoding="utf-8"))
    assert trace["route_id"] == "math.senior.default.v1"
    assert trace["provenance"]["few_shot_ids"] == ["math_easy_direct_chain_seed_002"]
    assert trace["provenance"]["canonical_solution_source"] == "frozen_upstream_task_evidence"
    assert trace["provenance"]["canonical_solution_quality"] == "provisional_model_extracted_evidence"
    assert len(trace["provenance"]["canonical_solution_sha256"]) == 64
    assert trace["model_payload"]["canonical_solution"]["source"] == "frozen_upstream_task_evidence"
    assert trace["model_payload"]["canonical_solution"]["shortest_solution_graph"]["nodes"][0]["node_id"] == "E1"


def test_model_transport_injects_few_shot_as_chat_turns() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"ok": True})}}],
                "usage": {"total_tokens": 10},
            },
        )

    configure_model_transport(
        ModelTransportSettings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = call_json_model(
            api_key="test",
            system_prompt="system",
            user_payload={"question_id": "Q1"},
            few_shots=[({"question_id": "EX1"}, {"label": "易"})],
            validator=lambda payload: payload,
        )
    finally:
        close_model_transport()
    assert result["ok"]
    assert [item["role"] for item in captured["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_staged_eval_plan_is_balanced_disjoint_and_complete(tmp_path: Path) -> None:
    rows = []
    for level in range(1, 6):
        for ordinal in range(1, 13):
            rows.append(
                {
                    "gold_item_id": f"L{level}-{ordinal:02d}",
                    "gold_level": level,
                    "gold_label": str(level),
                    "source_id": f"source-{level}",
                    "source_item_ordinal": ordinal,
                }
            )
    observed = {f"L1-{ordinal:02d}" for ordinal in range(1, 13)}
    plan = build_plan(rows, observed, calibration_per_level=3, validation_per_level=2)
    phases = plan["public_phases"]
    assert {key: len(value) for key, value in phases.items()} == {
        "calibration": 15,
        "frozen_validation": 10,
        "full_remainder": 35,
    }
    all_ids = [qid for values in phases.values() for qid in values]
    assert len(all_ids) == len(set(all_ids)) == 60
    assert plan["strict_blind_validation_by_level"]["1"]["strictly_unobserved_count"] == 0
    assert plan["strict_blind_validation_by_level"]["2"]["strictly_unobserved_count"] == 2

    public_path = tmp_path / "plan.json"
    public_path.write_text(json.dumps({"public_phases": phases}), encoding="utf-8")
    assert load_selected_ids(public_path, "calibration") == set(phases["calibration"])
    selected, provenance = load_plan_selection(public_path, "frozen_validation")
    assert selected == set(phases["frozen_validation"])
    assert provenance["phase"] == "frozen_validation"
    assert provenance["selected_count"] == 10


def test_repeatability_gate_requires_same_prompt_and_complete_coverage() -> None:
    def trace(qid: str, label: str, score: int, prompt_hash: str) -> dict:
        return {
            "question_id": qid,
            "status": "scored",
            "provenance": {"prompt_sha256": prompt_hash},
            "subject_result": {
                "difficulty_label": label,
                "total_score": score,
                "dimension_scores": {
                    key: {"score": value}
                    for key, value in {
                        "knowledge_complexity": 2,
                        "calculation_complexity": 3,
                        "thinking_complexity": 5,
                        "reading_conversion_complexity": 3,
                        "method_complexity": 4,
                        "innovation_complexity": 3,
                    }.items()
                },
            },
        }

    first = {"Q1": trace("Q1", "易", 20, "a" * 64), "Q2": trace("Q2", "较易", 35, "a" * 64)}
    second = {"Q1": trace("Q1", "易", 22, "a" * 64), "Q2": trace("Q2", "较易", 34, "a" * 64)}
    gate = {"same_label_rate_min": 0.90, "mean_absolute_score_drift_max": 3.0}
    report = evaluate_repeatability(first, second, ["Q1", "Q2"], gate)
    assert report["gate_passed"]

    second["Q2"]["provenance"]["prompt_sha256"] = "b" * 64
    report = evaluate_repeatability(first, second, ["Q1", "Q2"], gate)
    assert not report["gate_passed"]
    assert report["prompt_hash_mismatch_ids"] == ["Q2"]
