from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from difficulty_tagging.contracts import (
    IndependentCalculationStep,
    IndependentDecisionNode,
    InnovationAssessment,
    MethodEntryAssessmentV04,
    ReadingTransformationAssessment,
    RequiredKnowledgeUnit,
    ShortestSolutionGraph,
    normalize_semantic_judgment,
)


DIMENSION_IDS = (
    "knowledge_complexity",
    "calculation_complexity",
    "thinking_complexity",
    "reading_conversion_complexity",
    "method_complexity",
    "innovation_complexity",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DimensionJudgmentBase(StrictModel):
    schema_name: Literal["math_difficulty_dimension_judgment_v1"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=4)
    release_recommendation: Literal["accept_provisional", "manual_review"]


class KnowledgeDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["knowledge_complexity"]
    required_knowledge_units: list[RequiredKnowledgeUnit] = Field(min_length=1, max_length=16)


class CalculationDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["calculation_complexity"]
    independent_calculation_steps: list[IndependentCalculationStep] = Field(min_length=1, max_length=40)


class ThinkingDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["thinking_complexity"]
    independent_decision_nodes: list[IndependentDecisionNode] = Field(default_factory=list, max_length=20)


class ReadingDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["reading_conversion_complexity"]
    reading_transformation: ReadingTransformationAssessment


class MethodDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["method_complexity"]
    method_entry: MethodEntryAssessmentV04


class InnovationDimensionJudgment(DimensionJudgmentBase):
    dimension_id: Literal["innovation_complexity"]
    innovation_assessment: InnovationAssessment


DIMENSION_MODELS: dict[str, type[DimensionJudgmentBase]] = {
    "knowledge_complexity": KnowledgeDimensionJudgment,
    "calculation_complexity": CalculationDimensionJudgment,
    "thinking_complexity": ThinkingDimensionJudgment,
    "reading_conversion_complexity": ReadingDimensionJudgment,
    "method_complexity": MethodDimensionJudgment,
    "innovation_complexity": InnovationDimensionJudgment,
}


def validator_for_dimension(dimension_id: str):
    try:
        model = DIMENSION_MODELS[dimension_id]
    except KeyError as exc:
        raise ValueError(f"未知数学难度维度：{dimension_id}") from exc

    def validate(payload: dict[str, Any]) -> dict[str, Any]:
        return model.model_validate(payload).model_dump(mode="json", by_alias=True)

    return validate


def validate_dimension_identity(
    result: dict[str, Any], *, dimension_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    expected = {
        "question_id": payload["question_id"],
        "difficulty_scheme": payload["difficulty_scheme"],
        "rubric_version": payload["rubric_version"],
        "reference_population": payload["reference_population"],
    }
    if result.get("dimension_id") != dimension_id:
        raise ValueError(f"维度节点必须输出 dimension_id={dimension_id}")
    for field, value in expected.items():
        if result.get(field) != value:
            raise ValueError(f"维度节点 {dimension_id} 的 {field} 未原样复制输入")

    canonical = payload.get("canonical_solution")
    graph_payload = canonical.get("shortest_solution_graph") if isinstance(canonical, dict) else None
    graph = ShortestSolutionGraph.model_validate(graph_payload)
    graph_ids = {item.node_id for item in graph.nodes}

    def require_graph_refs(refs: list[str], label: str) -> None:
        unknown = set(refs).difference(graph_ids)
        if unknown:
            raise ValueError(f"维度节点 {dimension_id} 的{label}引用了未知冻结节点：{sorted(unknown)}")

    def require_unique(values: list[str], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"维度节点 {dimension_id} 的{label}不得重复")

    if dimension_id == "knowledge_complexity":
        units = result["required_knowledge_units"]
        require_unique([item["unit_id"] for item in units], "知识单元 ID")
        require_graph_refs(
            [node_id for item in units for node_id in item["source_node_ids"]], "知识依据"
        )
        upstream = payload.get("knowledge_tagging")
        allowed: dict[str, tuple[str, str]] = {}
        if isinstance(upstream, dict):
            for field in ("main_knowledge_points", "secondary_knowledge_points"):
                for point in upstream.get(field) or []:
                    if isinstance(point, dict) and point.get("pk"):
                        allowed[str(point["pk"])] = (
                            str(point.get("module", "") or ""),
                            str(point.get("knowledge_unit", "") or ""),
                        )
        for item in units:
            if item["source"] != "registered_tag":
                continue
            registered_pk = str(item["registered_pk"])
            source = allowed.get(registered_pk)
            if source is None:
                raise ValueError(f"知识维度引用了上游未发布的 pk：{registered_pk}")
            if (item["module"], item["name"]) != source:
                raise ValueError(f"知识维度未原样复制上游三级知识单元：{registered_pk}")
    elif dimension_id == "calculation_complexity":
        steps = result["independent_calculation_steps"]
        require_unique([item["step_id"] for item in steps], "计算步骤 ID")
        require_graph_refs([item["source_node_id"] for item in steps], "计算步骤")
    elif dimension_id == "thinking_complexity":
        nodes = result["independent_decision_nodes"]
        require_unique([item["node_id"] for item in nodes], "关键节点 ID")
        require_graph_refs([item["node_id"] for item in nodes], "关键节点")
    elif dimension_id == "reading_conversion_complexity":
        require_graph_refs(result["reading_transformation"]["source_node_ids"], "阅读转换")
    elif dimension_id == "method_complexity":
        require_graph_refs(result["method_entry"]["entry_node_ids"], "方法入口")
    elif dimension_id == "innovation_complexity":
        require_graph_refs(result["innovation_assessment"]["source_node_ids"], "创新判断")
    return result


def aggregate_dimension_judgments(
    results: dict[str, dict[str, Any]], *, payload: dict[str, Any]
) -> dict[str, Any]:
    missing = set(DIMENSION_IDS).difference(results)
    extra = set(results).difference(DIMENSION_IDS)
    if missing or extra:
        raise ValueError(f"六维结果不完整：missing={sorted(missing)} extra={sorted(extra)}")

    canonical = payload.get("canonical_solution")
    graph_payload = canonical.get("shortest_solution_graph") if isinstance(canonical, dict) else None
    graph = ShortestSolutionGraph.model_validate(graph_payload)

    knowledge = KnowledgeDimensionJudgment.model_validate(results["knowledge_complexity"])
    calculation = CalculationDimensionJudgment.model_validate(results["calculation_complexity"])
    thinking = ThinkingDimensionJudgment.model_validate(results["thinking_complexity"])
    reading = ReadingDimensionJudgment.model_validate(results["reading_conversion_complexity"])
    method = MethodDimensionJudgment.model_validate(results["method_complexity"])
    innovation = InnovationDimensionJudgment.model_validate(results["innovation_complexity"])
    judgments = [knowledge, calculation, thinking, reading, method, innovation]

    flagged_dimensions = [item.dimension_id for item in judgments if item.review_flags]
    review_flags = [f"dimension_review:{dimension_id}" for dimension_id in flagged_dimensions]
    if any(item.release_recommendation == "manual_review" for item in judgments):
        release_recommendation = "manual_review"
    else:
        release_recommendation = "accept_provisional"

    # 详细节点 flags 保留在各节点 trace；总结果只标记受影响维度，最多六项。
    synthetic = {
        "schema": "question_difficulty_semantic_judgment_v1",
        "question_id": payload["question_id"],
        "difficulty_scheme": payload["difficulty_scheme"],
        "rubric_version": payload["rubric_version"],
        "reference_population": payload["reference_population"],
        "semantic_reasoning": {
            "shortest_solution_graph": graph.model_dump(mode="json"),
            "required_knowledge_units": [
                item.model_dump(mode="json") for item in knowledge.required_knowledge_units
            ],
            "independent_calculation_steps": [
                item.model_dump(mode="json") for item in calculation.independent_calculation_steps
            ],
            "independent_decision_nodes": [
                item.model_dump(mode="json") for item in thinking.independent_decision_nodes
            ],
            "reading_transformation": reading.reading_transformation.model_dump(mode="json"),
            "method_entry": method.method_entry.model_dump(mode="json"),
            "innovation_assessment": innovation.innovation_assessment.model_dump(mode="json"),
        },
        "difficulty_confidence": min(item.confidence for item in judgments),
        "shortest_valid_solution_outline": [
            item.statement for item in graph.nodes[:18]
        ],
        "confidence_reason": "；".join(
            f"{item.dimension_id}:{item.confidence_reason}" for item in judgments
        ),
        "review_flags": review_flags,
        "release_recommendation": release_recommendation,
    }
    return normalize_semantic_judgment(synthetic)
