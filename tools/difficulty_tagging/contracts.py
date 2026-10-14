from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DIFFICULTY_LABELS = {1: "易", 2: "较易", 3: "中档", 4: "较难", 5: "困难"}

DIMENSION_SCORES = {
    "knowledge_complexity": {1: 2, 2: 4, 3: 6, 4: 8, 5: 10},
    "calculation_complexity": {1: 3, 2: 6, 3: 9, 4: 12, 5: 15},
    "thinking_complexity": {1: 5, 2: 10, 3: 15, 4: 20, 5: 25},
    "reading_conversion_complexity": {1: 3, 2: 6, 3: 9, 4: 12, 5: 15},
    "method_complexity": {1: 4, 2: 8, 3: 12, 4: 16, 5: 20},
    "innovation_complexity": {1: 3, 2: 6, 3: 9, 4: 12, 5: 15},
}


def level_from_total(total: int) -> int:
    if 20 <= total <= 29:
        return 1
    if 30 <= total <= 39:
        return 2
    if 40 <= total <= 64:
        return 3
    if 65 <= total <= 85:
        return 4
    if 86 <= total <= 100:
        return 5
    raise ValueError(f"总分超出业务区间：{total}")


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgePointEvidence(StrictContract):
    pk: str = Field(min_length=1)
    name: str = Field(min_length=1)
    module: str = Field(min_length=1)
    role: Literal["main", "secondary"]


class ScoredDimension(StrictContract):
    band: int = Field(ge=1, le=5)
    score: int
    judgment: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1, max_length=6)


class KnowledgeComplexity(ScoredDimension):
    knowledge_points: list[KnowledgePointEvidence] = Field(min_length=1, max_length=8)
    module_relation: Literal["single", "same_module", "cross_module"]

    @model_validator(mode="after")
    def validate_band(self) -> "KnowledgeComplexity":
        count = len(self.knowledge_points)
        if count == 1:
            expected_band = 1
            if self.module_relation != "single":
                raise ValueError("单知识点的 module_relation 必须为 single")
        elif count == 2:
            if self.module_relation == "single":
                raise ValueError("多知识点不能使用 single")
            expected_band = 2 if self.module_relation == "same_module" else 3
        else:
            if self.module_relation == "single":
                raise ValueError("多知识点不能使用 single")
            expected_band = 4 if self.module_relation == "same_module" else 5
        if self.band != expected_band:
            raise ValueError(f"知识点数量和模块关系对应第 {expected_band} 档，而不是第 {self.band} 档")
        return self


class CalculationComplexity(ScoredDimension):
    shortest_solution_step_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_band(self) -> "CalculationComplexity":
        count = self.shortest_solution_step_count
        expected_band = 1 if count <= 4 else 2 if count <= 8 else 3 if count <= 13 else 4 if count <= 17 else 5
        if self.band != expected_band:
            raise ValueError(f"计算步骤数对应第 {expected_band} 档，而不是第 {self.band} 档")
        return self


class ThinkingComplexity(ScoredDimension):
    key_nodes: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_band(self) -> "ThinkingComplexity":
        count = len(self.key_nodes)
        expected_band = 1 if count <= 1 else 2 if count == 2 else 3 if count == 3 else 4 if count <= 5 else 5
        if self.band != expected_band:
            raise ValueError(f"思维关键节点数对应第 {expected_band} 档，而不是第 {self.band} 档")
        return self


class DimensionScores(StrictContract):
    knowledge_complexity: KnowledgeComplexity
    calculation_complexity: CalculationComplexity
    thinking_complexity: ThinkingComplexity
    reading_conversion_complexity: ScoredDimension
    method_complexity: ScoredDimension
    innovation_complexity: ScoredDimension

    @model_validator(mode="after")
    def validate_fixed_scores(self) -> "DimensionScores":
        for name, score_map in DIMENSION_SCORES.items():
            item = getattr(self, name)
            expected = score_map[item.band]
            if item.score != expected:
                raise ValueError(f"{name} 第 {item.band} 档必须为 {expected} 分")
        return self


class DifficultyDecisionV02(StrictContract):
    contract_schema: Literal["question_difficulty_result_v0.2"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    dimension_scores: DimensionScores
    total_score: int = Field(ge=20, le=100)
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_label: Literal["易", "较易", "中档", "较难", "困难"]
    difficulty_source: Literal["model_predicted", "expert_seed"]
    difficulty_confidence: float = Field(ge=0, le=1)
    calibration_status: Literal["provisional_uncalibrated"]
    shortest_valid_solution_outline: list[str] = Field(min_length=1, max_length=18)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=6)
    release_recommendation: Literal["accept_provisional", "manual_review"]

    @model_validator(mode="after")
    def validate_totals_and_label(self) -> "DifficultyDecisionV02":
        expected_total = sum(
            getattr(self.dimension_scores, name).score for name in DIMENSION_SCORES
        )
        if self.total_score != expected_total:
            raise ValueError(f"六维分数合计为 {expected_total}，不是 {self.total_score}")
        expected_level = level_from_total(self.total_score)
        if self.difficulty_level != expected_level:
            raise ValueError(f"总分 {self.total_score} 对应第 {expected_level} 级")
        expected_label = DIFFICULTY_LABELS[expected_level]
        if self.difficulty_label != expected_label:
            raise ValueError(f"总分 {self.total_score} 对应 {expected_label}，不是 {self.difficulty_label}")
        return self


class SolutionDependencyNode(StrictContract):
    node_id: str = Field(min_length=1, max_length=40)
    node_type: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    student_visibility: str = Field(min_length=1, max_length=120)


class ShortestSolutionGraph(StrictContract):
    nodes: list[SolutionDependencyNode] = Field(min_length=1, max_length=36)
    final_node_id: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_graph(self) -> "ShortestSolutionGraph":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("最短解法依赖图的 node_id 不得重复")
        known = set(node_ids)
        if self.final_node_id not in known:
            raise ValueError("final_node_id 必须引用依赖图节点")
        dependencies = {item.node_id: list(item.depends_on) for item in self.nodes}
        for node_id, refs in dependencies.items():
            if len(refs) != len(set(refs)):
                raise ValueError(f"节点 {node_id} 的 depends_on 不得重复")
            if node_id in refs:
                raise ValueError(f"节点 {node_id} 不能依赖自身")
            unknown = set(refs).difference(known)
            if unknown:
                raise ValueError(f"节点 {node_id} 引用了未知依赖：{sorted(unknown)}")

        state: dict[str, int] = {}

        def visit(node_id: str) -> None:
            marker = state.get(node_id, 0)
            if marker == 1:
                raise ValueError("最短解法依赖图必须是无环图")
            if marker == 2:
                return
            state[node_id] = 1
            for dependency in dependencies[node_id]:
                visit(dependency)
            state[node_id] = 2

        for node_id in node_ids:
            visit(node_id)
        return self


class IndependentDecisionNode(StrictContract):
    node_id: str = Field(min_length=1, max_length=40)
    decision_type: str = Field(min_length=1, max_length=120)
    decision: str = Field(min_length=1)
    alternatives_considered: list[str] = Field(default_factory=list, max_length=6)
    why_indispensable: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1, max_length=4)

    @field_validator("alternatives_considered", "evidence", mode="before")
    @classmethod
    def normalize_text_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) and value.strip() else value


class MethodEntryAssessment(StrictContract):
    entry_type: str = Field(min_length=1, max_length=160)
    entry_node_ids: list[str] = Field(min_length=1, max_length=8)
    student_visible_cues: list[str] = Field(default_factory=list, max_length=8)
    unstated_key_moves: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1)

    @field_validator("student_visible_cues", "unstated_key_moves", mode="before")
    @classmethod
    def normalize_text_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) and value.strip() else value


class DimensionProjectionEvidence(StrictContract):
    source_node_ids: list[str] = Field(min_length=1, max_length=16)
    rationale: str = Field(min_length=1)


class DimensionProjectionSet(StrictContract):
    knowledge_complexity: DimensionProjectionEvidence
    calculation_complexity: DimensionProjectionEvidence
    thinking_complexity: DimensionProjectionEvidence
    reading_conversion_complexity: DimensionProjectionEvidence
    method_complexity: DimensionProjectionEvidence
    innovation_complexity: DimensionProjectionEvidence


class SemanticReasoning(StrictContract):
    shortest_solution_graph: ShortestSolutionGraph
    independent_decision_nodes: list[IndependentDecisionNode] = Field(default_factory=list, max_length=20)
    method_entry: MethodEntryAssessment
    dimension_projections: DimensionProjectionSet

    @model_validator(mode="after")
    def validate_references(self) -> "SemanticReasoning":
        graph_ids = {item.node_id for item in self.shortest_solution_graph.nodes}
        decision_ids = [item.node_id for item in self.independent_decision_nodes]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("独立决策节点不得重复引用同一 node_id")
        unknown_decisions = set(decision_ids).difference(graph_ids)
        if unknown_decisions:
            raise ValueError(f"独立决策节点引用了未知图节点：{sorted(unknown_decisions)}")
        unknown_entries = set(self.method_entry.entry_node_ids).difference(graph_ids)
        if unknown_entries:
            raise ValueError(f"方法入口引用了未知图节点：{sorted(unknown_entries)}")
        for dimension_name in DIMENSION_SCORES:
            projection = getattr(self.dimension_projections, dimension_name)
            unknown = set(projection.source_node_ids).difference(graph_ids)
            if unknown:
                raise ValueError(f"{dimension_name} 引用了未知图节点：{sorted(unknown)}")
        return self


class ThinkingComplexityV03(ScoredDimension):
    decision_node_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_band(self) -> "ThinkingComplexityV03":
        count = len(self.decision_node_ids)
        expected_band = 1 if count <= 1 else 2 if count == 2 else 3 if count == 3 else 4 if count <= 5 else 5
        if self.band != expected_band:
            raise ValueError(f"思维独立决策节点数对应第 {expected_band} 档，而不是第 {self.band} 档")
        return self


class DimensionScoresV03(StrictContract):
    knowledge_complexity: KnowledgeComplexity
    calculation_complexity: CalculationComplexity
    thinking_complexity: ThinkingComplexityV03
    reading_conversion_complexity: ScoredDimension
    method_complexity: ScoredDimension
    innovation_complexity: ScoredDimension

    @model_validator(mode="after")
    def validate_fixed_scores(self) -> "DimensionScoresV03":
        for name, score_map in DIMENSION_SCORES.items():
            item = getattr(self, name)
            expected = score_map[item.band]
            if item.score != expected:
                raise ValueError(f"{name} 第 {item.band} 档必须为 {expected} 分")
        return self


class DifficultyDecisionV03(StrictContract):
    contract_schema: Literal["question_difficulty_result_v0.3"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    semantic_reasoning: SemanticReasoning
    dimension_scores: DimensionScoresV03
    total_score: int = Field(ge=20, le=100)
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_label: Literal["易", "较易", "中档", "较难", "困难"]
    difficulty_source: Literal["model_predicted", "expert_seed"]
    difficulty_confidence: float = Field(ge=0, le=1)
    calibration_status: Literal["provisional_uncalibrated"]
    shortest_valid_solution_outline: list[str] = Field(min_length=1, max_length=18)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=6)
    release_recommendation: Literal["accept_provisional", "manual_review"]

    @model_validator(mode="after")
    def validate_projection_and_totals(self) -> "DifficultyDecisionV03":
        semantic_ids = [item.node_id for item in self.semantic_reasoning.independent_decision_nodes]
        scored_ids = self.dimension_scores.thinking_complexity.decision_node_ids
        if scored_ids != semantic_ids:
            raise ValueError("思维维度 decision_node_ids 必须按顺序等于独立决策节点列表")
        expected_total = sum(
            getattr(self.dimension_scores, name).score for name in DIMENSION_SCORES
        )
        if self.total_score != expected_total:
            raise ValueError(f"六维分数合计为 {expected_total}，不是 {self.total_score}")
        expected_level = level_from_total(self.total_score)
        if self.difficulty_level != expected_level:
            raise ValueError(f"总分 {self.total_score} 对应第 {expected_level} 级")
        expected_label = DIFFICULTY_LABELS[expected_level]
        if self.difficulty_label != expected_label:
            raise ValueError(f"总分 {self.total_score} 对应 {expected_label}，不是 {self.difficulty_label}")
        return self


class RequiredKnowledgeUnit(StrictContract):
    unit_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    module: str = Field(min_length=1, max_length=160)
    source: Literal["registered_tag", "implicit_prerequisite"]
    registered_pk: str | None = None
    source_node_ids: list[str] = Field(min_length=1, max_length=12)
    necessity: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registered_provenance(self) -> "RequiredKnowledgeUnit":
        if self.source == "registered_tag" and not self.registered_pk:
            raise ValueError("registered_tag 知识单元必须提供 registered_pk")
        if self.source == "implicit_prerequisite" and self.registered_pk is not None:
            raise ValueError("implicit_prerequisite 知识单元不得伪造 registered_pk")
        return self


class IndependentCalculationStep(StrictContract):
    step_id: str = Field(min_length=1, max_length=40)
    source_node_id: str = Field(min_length=1, max_length=40)
    purpose: str = Field(min_length=1)


class ReadingTransformationAssessment(StrictContract):
    recommended_band: int = Field(ge=1, le=5)
    source_node_ids: list[str] = Field(min_length=1, max_length=16)
    transformations: list[str] = Field(default_factory=list, max_length=12)
    rationale: str = Field(min_length=1)


class MethodEntryAssessmentV04(MethodEntryAssessment):
    recommended_band: int = Field(ge=1, le=5)


class InnovationAssessment(StrictContract):
    recommended_band: int = Field(ge=1, le=5)
    source_node_ids: list[str] = Field(min_length=1, max_length=16)
    non_template_moves: list[str] = Field(default_factory=list, max_length=12)
    rationale: str = Field(min_length=1)


class SemanticReasoningV04(StrictContract):
    shortest_solution_graph: ShortestSolutionGraph
    required_knowledge_units: list[RequiredKnowledgeUnit] = Field(min_length=1, max_length=16)
    independent_calculation_steps: list[IndependentCalculationStep] = Field(min_length=1, max_length=40)
    independent_decision_nodes: list[IndependentDecisionNode] = Field(default_factory=list, max_length=20)
    reading_transformation: ReadingTransformationAssessment
    method_entry: MethodEntryAssessmentV04
    innovation_assessment: InnovationAssessment
    dimension_projections: DimensionProjectionSet

    @model_validator(mode="after")
    def validate_references(self) -> "SemanticReasoningV04":
        graph_ids = {item.node_id for item in self.shortest_solution_graph.nodes}

        def require_unique(values: list[str], label: str) -> None:
            if len(values) != len(set(values)):
                raise ValueError(f"{label} 的 ID 不得重复")

        knowledge_ids = [item.unit_id for item in self.required_knowledge_units]
        calculation_ids = [item.step_id for item in self.independent_calculation_steps]
        decision_ids = [item.node_id for item in self.independent_decision_nodes]
        require_unique(knowledge_ids, "必要知识单元")
        require_unique(calculation_ids, "独立计算步骤")
        require_unique(decision_ids, "独立决策节点")

        reference_groups = [
            ("必要知识单元", [node_id for item in self.required_knowledge_units for node_id in item.source_node_ids]),
            ("独立计算步骤", [item.source_node_id for item in self.independent_calculation_steps]),
            ("独立决策节点", decision_ids),
            ("阅读转换", self.reading_transformation.source_node_ids),
            ("方法入口", self.method_entry.entry_node_ids),
            ("创新判断", self.innovation_assessment.source_node_ids),
        ]
        for label, refs in reference_groups:
            unknown = set(refs).difference(graph_ids)
            if unknown:
                raise ValueError(f"{label}引用了未知图节点：{sorted(unknown)}")
        for dimension_name in DIMENSION_SCORES:
            projection = getattr(self.dimension_projections, dimension_name)
            unknown = set(projection.source_node_ids).difference(graph_ids)
            if unknown:
                raise ValueError(f"{dimension_name} 引用了未知图节点：{sorted(unknown)}")
        return self


class KnowledgeComplexityV04(ScoredDimension):
    required_knowledge_unit_ids: list[str] = Field(min_length=1, max_length=16)
    knowledge_points: list[KnowledgePointEvidence] = Field(default_factory=list, max_length=8)
    module_relation: Literal["single", "same_module", "cross_module"]


class CalculationComplexityV04(ScoredDimension):
    calculation_step_ids: list[str] = Field(min_length=1, max_length=40)
    shortest_solution_step_count: int = Field(ge=1, le=40)


class DimensionScoresV04(StrictContract):
    knowledge_complexity: KnowledgeComplexityV04
    calculation_complexity: CalculationComplexityV04
    thinking_complexity: ThinkingComplexityV03
    reading_conversion_complexity: ScoredDimension
    method_complexity: ScoredDimension
    innovation_complexity: ScoredDimension

    @model_validator(mode="after")
    def validate_fixed_scores(self) -> "DimensionScoresV04":
        for name, score_map in DIMENSION_SCORES.items():
            item = getattr(self, name)
            expected = score_map[item.band]
            if item.score != expected:
                raise ValueError(f"{name} 第 {item.band} 档必须为 {expected} 分")
        return self


class DifficultyDecisionV04(StrictContract):
    contract_schema: Literal["question_difficulty_result_v0.4"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    semantic_reasoning: SemanticReasoningV04
    dimension_scores: DimensionScoresV04
    total_score: int = Field(ge=20, le=100)
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_label: Literal["易", "较易", "中档", "较难", "困难"]
    difficulty_source: Literal["model_predicted", "expert_seed"]
    difficulty_confidence: float = Field(ge=0, le=1)
    calibration_status: Literal["provisional_uncalibrated"]
    shortest_valid_solution_outline: list[str] = Field(min_length=1, max_length=18)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=6)
    release_recommendation: Literal["accept_provisional", "manual_review"]

    @model_validator(mode="after")
    def validate_semantic_projection_and_totals(self) -> "DifficultyDecisionV04":
        semantic = self.semantic_reasoning
        scores = self.dimension_scores

        unit_ids = [item.unit_id for item in semantic.required_knowledge_units]
        if scores.knowledge_complexity.required_knowledge_unit_ids != unit_ids:
            raise ValueError("知识维度必须按顺序引用全部 required_knowledge_units")
        unit_count = len(unit_ids)
        module_count = len({item.module for item in semantic.required_knowledge_units})
        expected_relation = "single" if unit_count == 1 else "same_module" if module_count == 1 else "cross_module"
        if scores.knowledge_complexity.module_relation != expected_relation:
            raise ValueError(f"必要知识单元对应 module_relation={expected_relation}")
        expected_knowledge_band = 1 if unit_count == 1 else 2 if unit_count == 2 and module_count == 1 else 3 if unit_count == 2 else 4 if module_count == 1 else 5
        if scores.knowledge_complexity.band != expected_knowledge_band:
            raise ValueError(f"必要知识单元数量和模块关系对应知识第 {expected_knowledge_band} 档")

        calculation_ids = [item.step_id for item in semantic.independent_calculation_steps]
        if scores.calculation_complexity.calculation_step_ids != calculation_ids:
            raise ValueError("计算维度必须按顺序引用全部 independent_calculation_steps")
        if scores.calculation_complexity.shortest_solution_step_count != len(calculation_ids):
            raise ValueError("shortest_solution_step_count 必须等于独立计算步骤数")
        calculation_count = len(calculation_ids)
        expected_calculation_band = 1 if calculation_count <= 4 else 2 if calculation_count <= 8 else 3 if calculation_count <= 13 else 4 if calculation_count <= 17 else 5
        if scores.calculation_complexity.band != expected_calculation_band:
            raise ValueError(f"独立计算步骤数对应计算第 {expected_calculation_band} 档")

        decision_ids = [item.node_id for item in semantic.independent_decision_nodes]
        if scores.thinking_complexity.decision_node_ids != decision_ids:
            raise ValueError("思维维度必须按顺序引用全部 independent_decision_nodes")
        if scores.reading_conversion_complexity.band != semantic.reading_transformation.recommended_band:
            raise ValueError("阅读转换分档必须等于语义判断的 recommended_band")
        if scores.method_complexity.band != semantic.method_entry.recommended_band:
            raise ValueError("方法复杂度分档必须等于方法入口的 recommended_band")
        if scores.innovation_complexity.band != semantic.innovation_assessment.recommended_band:
            raise ValueError("创新复杂度分档必须等于创新判断的 recommended_band")

        expected_total = sum(getattr(scores, name).score for name in DIMENSION_SCORES)
        if self.total_score != expected_total:
            raise ValueError(f"六维分数合计为 {expected_total}，不是 {self.total_score}")
        expected_level = level_from_total(self.total_score)
        if self.difficulty_level != expected_level:
            raise ValueError(f"总分 {self.total_score} 对应第 {expected_level} 级")
        expected_label = DIFFICULTY_LABELS[expected_level]
        if self.difficulty_label != expected_label:
            raise ValueError(f"总分 {self.total_score} 对应 {expected_label}，不是 {self.difficulty_label}")
        return self


class SemanticReasoningJudgment(StrictContract):
    shortest_solution_graph: ShortestSolutionGraph
    required_knowledge_units: list[RequiredKnowledgeUnit] = Field(min_length=1, max_length=16)
    independent_calculation_steps: list[IndependentCalculationStep] = Field(min_length=1, max_length=40)
    independent_decision_nodes: list[IndependentDecisionNode] = Field(default_factory=list, max_length=20)
    reading_transformation: ReadingTransformationAssessment
    method_entry: MethodEntryAssessmentV04
    innovation_assessment: InnovationAssessment

    @model_validator(mode="after")
    def validate_references(self) -> "SemanticReasoningJudgment":
        graph_ids = {item.node_id for item in self.shortest_solution_graph.nodes}
        id_groups = {
            "必要知识单元": [item.unit_id for item in self.required_knowledge_units],
            "独立计算步骤": [item.step_id for item in self.independent_calculation_steps],
            "独立决策节点": [item.node_id for item in self.independent_decision_nodes],
        }
        for label, values in id_groups.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{label}的 ID 不得重复")
        reference_groups = [
            ("必要知识单元", [node_id for item in self.required_knowledge_units for node_id in item.source_node_ids]),
            ("独立计算步骤", [item.source_node_id for item in self.independent_calculation_steps]),
            ("独立决策节点", id_groups["独立决策节点"]),
            ("阅读转换", self.reading_transformation.source_node_ids),
            ("方法入口", self.method_entry.entry_node_ids),
            ("创新判断", self.innovation_assessment.source_node_ids),
        ]
        for label, refs in reference_groups:
            unknown = set(refs).difference(graph_ids)
            if unknown:
                raise ValueError(f"{label}引用了未知图节点：{sorted(unknown)}")
        return self


class SemanticDifficultyJudgmentV1(StrictContract):
    contract_schema: Literal["question_difficulty_semantic_judgment_v1"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    module_relation: Literal["single", "same_module", "cross_module"] | None = None
    semantic_reasoning: SemanticReasoningJudgment
    difficulty_confidence: float = Field(ge=0, le=1)
    shortest_valid_solution_outline: list[str] = Field(min_length=1, max_length=18)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=6)
    release_recommendation: Literal["accept_provisional", "manual_review"]


class CanonicalSemanticProjection(StrictContract):
    required_knowledge_units: list[RequiredKnowledgeUnit] = Field(min_length=1, max_length=16)
    independent_calculation_steps: list[IndependentCalculationStep] = Field(min_length=1, max_length=40)
    independent_decision_nodes: list[IndependentDecisionNode] = Field(default_factory=list, max_length=20)
    reading_transformation: ReadingTransformationAssessment
    method_entry: MethodEntryAssessmentV04
    innovation_assessment: InnovationAssessment


class CanonicalDifficultyProjectionV1(StrictContract):
    contract_schema: Literal["question_difficulty_canonical_projection_v1"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: Literal["six_dimension_100_point_v0.1"]
    reference_population: str = Field(min_length=1)
    module_relation: Literal["single", "same_module", "cross_module"] | None = None
    semantic_reasoning: CanonicalSemanticProjection
    difficulty_confidence: float = Field(ge=0, le=1)
    shortest_valid_solution_outline: list[str] = Field(min_length=1, max_length=18)
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=6)
    release_recommendation: Literal["accept_provisional", "manual_review"]


def _band_for_knowledge(units: list[RequiredKnowledgeUnit]) -> tuple[int, str]:
    count = len(units)
    module_count = len({item.module for item in units})
    relation = "single" if count == 1 else "same_module" if module_count == 1 else "cross_module"
    band = 1 if count == 1 else 2 if count == 2 and module_count == 1 else 3 if count == 2 else 4 if module_count == 1 else 5
    return band, relation


def _band_for_count(count: int, *, dimension: str) -> int:
    if dimension == "calculation":
        return 1 if count <= 4 else 2 if count <= 8 else 3 if count <= 13 else 4 if count <= 17 else 5
    return 1 if count <= 1 else 2 if count == 2 else 3 if count == 3 else 4 if count <= 5 else 5


def normalize_semantic_judgment(payload: dict[str, Any]) -> dict[str, Any]:
    judgment = SemanticDifficultyJudgmentV1.model_validate(payload)
    semantic = judgment.semantic_reasoning
    units = semantic.required_knowledge_units
    calculations = semantic.independent_calculation_steps
    decisions = semantic.independent_decision_nodes
    knowledge_band, module_relation = _band_for_knowledge(units)
    calculation_band = _band_for_count(len(calculations), dimension="calculation")
    thinking_band = _band_for_count(len(decisions), dimension="thinking")

    dimension_bands = {
        "knowledge_complexity": knowledge_band,
        "calculation_complexity": calculation_band,
        "thinking_complexity": thinking_band,
        "reading_conversion_complexity": semantic.reading_transformation.recommended_band,
        "method_complexity": semantic.method_entry.recommended_band,
        "innovation_complexity": semantic.innovation_assessment.recommended_band,
    }
    dimension_scores: dict[str, Any] = {
        "knowledge_complexity": {
            "band": knowledge_band,
            "score": DIMENSION_SCORES["knowledge_complexity"][knowledge_band],
            "judgment": f"必要知识单元 {len(units)} 个",
            "evidence": [item.necessity for item in units[:6]],
            "required_knowledge_unit_ids": [item.unit_id for item in units],
            "knowledge_points": [],
            "module_relation": module_relation,
        },
        "calculation_complexity": {
            "band": calculation_band,
            "score": DIMENSION_SCORES["calculation_complexity"][calculation_band],
            "judgment": f"独立计算步骤 {len(calculations)} 个",
            "evidence": [item.purpose for item in calculations[:6]],
            "calculation_step_ids": [item.step_id for item in calculations],
            "shortest_solution_step_count": len(calculations),
        },
        "thinking_complexity": {
            "band": thinking_band,
            "score": DIMENSION_SCORES["thinking_complexity"][thinking_band],
            "judgment": f"独立决策节点 {len(decisions)} 个",
            "evidence": [item.decision for item in decisions[:6]] or ["无独立路线决策"],
            "decision_node_ids": [item.node_id for item in decisions],
        },
        "reading_conversion_complexity": {
            "band": semantic.reading_transformation.recommended_band,
            "score": DIMENSION_SCORES["reading_conversion_complexity"][semantic.reading_transformation.recommended_band],
            "judgment": semantic.reading_transformation.rationale,
            "evidence": semantic.reading_transformation.transformations[:6] or [semantic.reading_transformation.rationale],
        },
        "method_complexity": {
            "band": semantic.method_entry.recommended_band,
            "score": DIMENSION_SCORES["method_complexity"][semantic.method_entry.recommended_band],
            "judgment": semantic.method_entry.rationale,
            "evidence": semantic.method_entry.unstated_key_moves[:6] or semantic.method_entry.student_visible_cues[:6] or [semantic.method_entry.rationale],
        },
        "innovation_complexity": {
            "band": semantic.innovation_assessment.recommended_band,
            "score": DIMENSION_SCORES["innovation_complexity"][semantic.innovation_assessment.recommended_band],
            "judgment": semantic.innovation_assessment.rationale,
            "evidence": semantic.innovation_assessment.non_template_moves[:6] or [semantic.innovation_assessment.rationale],
        },
    }
    projection_sources = {
        "knowledge_complexity": list(dict.fromkeys(node_id for item in units for node_id in item.source_node_ids)),
        "calculation_complexity": list(dict.fromkeys(item.source_node_id for item in calculations)),
        "thinking_complexity": list(dict.fromkeys(item.node_id for item in decisions)) or [semantic.method_entry.entry_node_ids[0]],
        "reading_conversion_complexity": semantic.reading_transformation.source_node_ids,
        "method_complexity": semantic.method_entry.entry_node_ids,
        "innovation_complexity": semantic.innovation_assessment.source_node_ids,
    }
    projection_rationales = {
        "knowledge_complexity": dimension_scores["knowledge_complexity"]["judgment"],
        "calculation_complexity": dimension_scores["calculation_complexity"]["judgment"],
        "thinking_complexity": dimension_scores["thinking_complexity"]["judgment"],
        "reading_conversion_complexity": semantic.reading_transformation.rationale,
        "method_complexity": semantic.method_entry.rationale,
        "innovation_complexity": semantic.innovation_assessment.rationale,
    }
    total = sum(DIMENSION_SCORES[name][band] for name, band in dimension_bands.items())
    level = level_from_total(total)
    normalized = {
        "schema": "question_difficulty_result_v0.4",
        "question_id": judgment.question_id,
        "difficulty_scheme": judgment.difficulty_scheme,
        "rubric_version": judgment.rubric_version,
        "reference_population": judgment.reference_population,
        "semantic_reasoning": {
            **semantic.model_dump(mode="json"),
            "dimension_projections": {
                name: {"source_node_ids": projection_sources[name], "rationale": projection_rationales[name]}
                for name in DIMENSION_SCORES
            },
        },
        "dimension_scores": dimension_scores,
        "total_score": total,
        "difficulty_level": level,
        "difficulty_label": DIFFICULTY_LABELS[level],
        "difficulty_source": "model_predicted",
        "difficulty_confidence": judgment.difficulty_confidence,
        "calibration_status": "provisional_uncalibrated",
        "shortest_valid_solution_outline": judgment.shortest_valid_solution_outline,
        "confidence_reason": judgment.confidence_reason,
        "review_flags": judgment.review_flags,
        "release_recommendation": judgment.release_recommendation,
    }
    return DifficultyDecisionV04.model_validate(normalized).model_dump(mode="json", by_alias=True)


def validate_canonical_projection_shape(payload: dict[str, Any]) -> dict[str, Any]:
    return CanonicalDifficultyProjectionV1.model_validate(payload).model_dump(mode="json", by_alias=True)


def normalize_canonical_projection(
    payload: dict[str, Any], canonical_graph: dict[str, Any]
) -> dict[str, Any]:
    projection = CanonicalDifficultyProjectionV1.model_validate(payload)
    graph = ShortestSolutionGraph.model_validate(canonical_graph)
    graph_ids = {item.node_id for item in graph.nodes}
    semantic = projection.semantic_reasoning
    reference_groups = [
        ("必要知识单元", [node_id for item in semantic.required_knowledge_units for node_id in item.source_node_ids]),
        ("独立计算步骤", [item.source_node_id for item in semantic.independent_calculation_steps]),
        ("独立决策节点", [item.node_id for item in semantic.independent_decision_nodes]),
        ("阅读转换", semantic.reading_transformation.source_node_ids),
        ("方法入口", semantic.method_entry.entry_node_ids),
        ("创新判断", semantic.innovation_assessment.source_node_ids),
    ]
    for label, refs in reference_groups:
        unknown = set(refs).difference(graph_ids)
        if unknown:
            raise ValueError(f"{label}引用了 canonical_solution 之外的节点：{sorted(unknown)}")
    synthetic = {
        "schema": "question_difficulty_semantic_judgment_v1",
        "question_id": projection.question_id,
        "difficulty_scheme": projection.difficulty_scheme,
        "rubric_version": projection.rubric_version,
        "reference_population": projection.reference_population,
        "semantic_reasoning": {
            "shortest_solution_graph": graph.model_dump(mode="json"),
            **semantic.model_dump(mode="json"),
        },
        "difficulty_confidence": projection.difficulty_confidence,
        "shortest_valid_solution_outline": projection.shortest_valid_solution_outline,
        "confidence_reason": projection.confidence_reason,
        "review_flags": projection.review_flags,
        "release_recommendation": projection.release_recommendation,
    }
    return normalize_semantic_judgment(synthetic)


def validate_difficulty_decision(payload: dict[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if schema == "question_difficulty_result_v0.4":
        contract = DifficultyDecisionV04
    elif schema == "question_difficulty_result_v0.3":
        contract = DifficultyDecisionV03
    else:
        contract = DifficultyDecisionV02
    return contract.model_validate(payload).model_dump(mode="json", by_alias=True)


def validate_semantic_difficulty_decision(payload: dict[str, Any]) -> dict[str, Any]:
    return DifficultyDecisionV03.model_validate(payload).model_dump(mode="json", by_alias=True)


def validate_semantic_difficulty_decision_v04(payload: dict[str, Any]) -> dict[str, Any]:
    return DifficultyDecisionV04.model_validate(payload).model_dump(mode="json", by_alias=True)


def validate_semantic_judgment_v1(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_semantic_judgment(payload)
