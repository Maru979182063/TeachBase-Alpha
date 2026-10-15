from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from difficulty_tagging.contracts import (
    DIFFICULTY_LABELS,
    validate_difficulty_decision,
    validate_semantic_difficulty_decision,
    validate_semantic_difficulty_decision_v04,
    validate_semantic_judgment_v1,
    validate_canonical_projection_shape,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenericDimension(StrictModel):
    dimension_id: str = Field(min_length=1)
    band: int = Field(ge=1, le=5)
    judgment: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1, max_length=8)


class GenericFiveBandDecision(StrictModel):
    contract_schema: Literal["question_difficulty_generic_result_v1"] = Field(alias="schema")
    question_id: str = Field(min_length=1)
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    reference_population: str = Field(min_length=1)
    dimensions: list[GenericDimension] = Field(min_length=1, max_length=12)
    difficulty_level: int = Field(ge=1, le=5)
    difficulty_label: Literal["易", "较易", "中档", "较难", "困难"]
    difficulty_source: Literal["model_predicted", "expert_seed"]
    difficulty_confidence: float = Field(ge=0, le=1)
    calibration_status: Literal["provisional_uncalibrated", "anchor_calibrated"]
    confidence_reason: str = Field(min_length=1)
    review_flags: list[str] = Field(default_factory=list, max_length=8)
    release_recommendation: Literal["accept_provisional", "manual_review"]

    @model_validator(mode="after")
    def validate_label(self) -> "GenericFiveBandDecision":
        expected = DIFFICULTY_LABELS[self.difficulty_level]
        if self.difficulty_label != expected:
            raise ValueError(f"第 {self.difficulty_level} 档必须标为 {expected}")
        ids = [item.dimension_id for item in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("dimensions 中的 dimension_id 不得重复")
        return self


def validate_generic_five_band(payload: dict[str, Any]) -> dict[str, Any]:
    return GenericFiveBandDecision.model_validate(payload).model_dump(mode="json", by_alias=True)


VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "math_six_dimension_v01": validate_difficulty_decision,
    "math_six_dimension_semantic_v02": validate_semantic_difficulty_decision,
    "math_six_dimension_semantic_v03": validate_semantic_difficulty_decision_v04,
    "math_six_dimension_semantic_v04": validate_semantic_judgment_v1,
    "math_canonical_projection_v01": validate_canonical_projection_shape,
    # 六维并行模式由 parallel_dimensions 分别校验并汇总，不走单结果 validator。
    # 并行节点的六份原始输出由运行器分别验证；适配器面对的是聚合后的最终结果。
    "math_parallel_dimension_projection_v1": validate_difficulty_decision,
    "generic_five_band_v01": validate_generic_five_band,
}


def validator_for(adapter_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    try:
        return VALIDATORS[adapter_id]
    except KeyError as exc:
        raise ValueError(f"未知难度结果适配器：{adapter_id}") from exc


def common_projection(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "difficulty_level": result["difficulty_level"],
        "difficulty_label": result["difficulty_label"],
        "difficulty_confidence": result["difficulty_confidence"],
        "calibration_status": result["calibration_status"],
        "review_flags": list(result.get("review_flags") or []),
        "release_recommendation": result["release_recommendation"],
    }
