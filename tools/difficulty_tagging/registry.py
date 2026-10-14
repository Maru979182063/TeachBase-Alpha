from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


MATCH_FIELDS = ("subject", "stage", "question_type")
RUNNABLE_STATUSES = {"trial", "active"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderSettings(StrictModel):
    provider_id: str = Field(min_length=1)
    api_url: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = "medium"
    max_tokens: int = Field(default=3000, ge=128, le=32000)
    timeout_seconds: float = Field(default=180, gt=0, le=900)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    max_connections: int = Field(default=4, ge=1, le=64)
    max_keepalive_connections: int = Field(default=4, ge=1, le=64)
    requests_per_second: float = Field(default=1, gt=0, le=100)
    burst: int = Field(default=2, ge=1, le=100)
    retry_base_seconds: float = Field(default=1, ge=0, le=60)
    retry_max_seconds: float = Field(default=20, ge=0, le=300)
    circuit_breaker_failures: int = Field(default=6, ge=1, le=100)
    circuit_breaker_cooldown_seconds: float = Field(default=30, ge=0, le=3600)


class LabelBand(StrictModel):
    level: int = Field(ge=1, le=5)
    label: Literal["易", "较易", "中档", "较难", "困难"]


class LabelScheme(StrictModel):
    scheme_id: str = Field(min_length=1)
    bands: list[LabelBand] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_complete_five_bands(self) -> "LabelScheme":
        expected_labels = ["易", "较易", "中档", "较难", "困难"]
        ordered = sorted(self.bands, key=lambda item: item.level)
        if [item.level for item in ordered] != [1, 2, 3, 4, 5]:
            raise ValueError("五档标签必须完整覆盖 1 至 5")
        if [item.label for item in ordered] != expected_labels:
            raise ValueError("五档标签顺序必须为易、较易、中档、较难、困难")
        return self


class RouteMatch(StrictModel):
    subject: str = Field(min_length=1)
    stage: str | None = None
    question_type: str | None = None

    def active_items(self) -> dict[str, str]:
        values = self.model_dump(exclude_none=True)
        return {key: str(values[key]) for key in MATCH_FIELDS if key in values}


class DifficultyRoute(StrictModel):
    route_id: str = Field(min_length=1)
    status: Literal["draft", "trial", "active", "disabled"]
    enabled: bool = False
    priority: int = Field(default=100, ge=0, le=10000)
    match: RouteMatch
    provider_id: str = Field(min_length=1)
    prompt_bundle: str = Field(min_length=1)
    result_adapter: Literal[
        "math_six_dimension_v01",
        "math_six_dimension_semantic_v02",
        "math_six_dimension_semantic_v03",
        "math_six_dimension_semantic_v04",
        "math_canonical_projection_v01",
        "generic_five_band_v01",
    ]
    difficulty_scheme: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    label_scheme: str = Field(min_length=1)
    reference_population: str = Field(min_length=1)
    minimum_publish_confidence: float = Field(default=0.75, ge=0, le=1)
    boundary_review_margin_points: int = Field(default=0, ge=0, le=10)

    @model_validator(mode="after")
    def validate_enabled_status(self) -> "DifficultyRoute":
        if self.enabled and self.status not in RUNNABLE_STATUSES:
            raise ValueError("只有 trial 或 active 路由可以启用")
        return self


class RegistryPolicy(StrictModel):
    no_route: Literal["manual_review"] = "manual_review"
    ambiguous_route: Literal["fail_closed"] = "fail_closed"
    require_upstream_release: bool = True
    require_few_shot_for_active_route: bool = True


class DifficultyRegistry(StrictModel):
    registry_schema: Literal["difficulty_pipeline_registry_v1"] = Field(alias="schema")
    version: str = Field(min_length=1)
    policies: RegistryPolicy
    providers: list[ProviderSettings] = Field(min_length=1)
    label_schemes: list[LabelScheme] = Field(min_length=1)
    routes: list[DifficultyRoute] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references_and_ambiguity(self) -> "DifficultyRegistry":
        provider_ids = [item.provider_id for item in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_id 重复")
        label_ids = [item.scheme_id for item in self.label_schemes]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("label scheme id 重复")
        route_ids = [item.route_id for item in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("route_id 重复")
        for route in self.routes:
            if route.provider_id not in provider_ids:
                raise ValueError(f"路由引用未知 provider：{route.route_id}")
            if route.label_scheme not in label_ids:
                raise ValueError(f"路由引用未知五档方案：{route.route_id}")
        enabled_signatures: set[tuple[tuple[str, str], ...]] = set()
        for route in self.routes:
            if not route.enabled:
                continue
            signature = tuple(sorted(route.match.active_items().items()))
            if signature in enabled_signatures:
                raise ValueError(f"存在完全重复的已启用路由条件：{signature}")
            enabled_signatures.add(signature)
        return self

    def provider(self, provider_id: str) -> ProviderSettings:
        return next(item for item in self.providers if item.provider_id == provider_id)


class RouteNotFoundError(LookupError):
    pass


class AmbiguousRouteError(LookupError):
    pass


@dataclass(frozen=True)
class LoadedRegistry:
    path: Path
    sha256: str
    value: DifficultyRegistry


def _workspace_child(workspace_root: Path, value: str) -> Path:
    candidate = (workspace_root / value).resolve()
    try:
        candidate.relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"注册表路径越出工作区：{value}") from exc
    return candidate


def load_registry(path: Path, workspace_root: Path) -> LoadedRegistry:
    payload_bytes = path.read_bytes()
    raw = yaml.safe_load(payload_bytes.decode("utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError(f"注册表必须为 YAML 对象：{path}")
    value = DifficultyRegistry.model_validate(raw)
    for route in value.routes:
        prompt_path = _workspace_child(workspace_root, route.prompt_bundle)
        if not prompt_path.is_file():
            raise ValueError(f"路由提示词不存在：{route.route_id} -> {route.prompt_bundle}")
    return LoadedRegistry(path=path.resolve(), sha256=hashlib.sha256(payload_bytes).hexdigest(), value=value)


def resolve_route(
    registry: DifficultyRegistry,
    context: dict[str, Any],
    *,
    include_draft: bool = False,
) -> DifficultyRoute:
    candidates: list[tuple[int, int, DifficultyRoute]] = []
    for route in registry.routes:
        if not route.enabled and not include_draft:
            continue
        if route.status not in RUNNABLE_STATUSES and not include_draft:
            continue
        conditions = route.match.active_items()
        if all(str(context.get(key, "")) == expected for key, expected in conditions.items()):
            candidates.append((len(conditions), route.priority, route))
    if not candidates:
        selected = {key: str(context.get(key, "")) for key in MATCH_FIELDS}
        raise RouteNotFoundError(f"没有可执行难度路由：{selected}")
    candidates.sort(key=lambda item: (-item[0], item[1], item[2].route_id))
    best_specificity, best_priority, best = candidates[0]
    peers = [
        item[2].route_id
        for item in candidates
        if item[0] == best_specificity and item[1] == best_priority
    ]
    if len(peers) > 1:
        raise AmbiguousRouteError(f"难度路由优先级冲突：{peers}")
    return best
