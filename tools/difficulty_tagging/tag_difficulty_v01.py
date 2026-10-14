from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from difficulty_tagging.contracts import validate_difficulty_decision
from knowledge_tagging.common import write_json
from knowledge_tagging.model_api import (
    ModelTransportSettings,
    call_json_model,
    close_model_transport,
    configure_model_transport,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = WORKSPACE_ROOT / "config" / "difficulty_tagging_math_senior_v01.yaml"


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(StrictConfig):
    api_url: str
    api_key_env: str = "ARK_API_KEY"
    max_connections: int = Field(default=4, ge=1, le=64)
    max_keepalive_connections: int = Field(default=4, ge=1, le=64)
    requests_per_second: float = Field(default=1, gt=0, le=100)
    burst: int = Field(default=2, ge=1, le=100)
    retry_base_seconds: float = Field(default=1, ge=0, le=60)
    retry_max_seconds: float = Field(default=20, ge=0, le=300)
    retry_jitter: str = "full"
    circuit_breaker_failures: int = Field(default=6, ge=1, le=100)
    circuit_breaker_cooldown_seconds: float = Field(default=30, ge=0, le=3600)


class NodeConfig(StrictConfig):
    prompt: str
    model: str
    reasoning_effort: str = "medium"
    max_tokens: int = Field(default=2400, ge=128, le=16000)
    timeout_seconds: float = Field(default=150, gt=0, le=600)
    retry_attempts: int = Field(default=3, ge=1, le=10)


class SchemeConfig(StrictConfig):
    id: str
    subject: str
    stage: str
    reference_population: str
    minimum_publish_confidence: float = Field(default=0.75, ge=0, le=1)


class InputConfig(StrictConfig):
    directory: str
    accepted_statuses: list[str] = Field(default_factory=lambda: ["tagged"])


class OutputConfig(StrictConfig):
    directory: str


class DifficultyTaggingConfig(StrictConfig):
    config_schema: str = Field(alias="schema")
    version: str
    provider: ProviderConfig
    node: NodeConfig
    scheme: SchemeConfig
    input: InputConfig
    output: OutputConfig

    @model_validator(mode="after")
    def validate_schema(self) -> "DifficultyTaggingConfig":
        if self.config_schema != "question_difficulty_config_v1":
            raise ValueError("不支持的难度配置 schema")
        return self


def workspace_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else WORKSPACE_ROOT / path


def load_config(path: Path) -> DifficultyTaggingConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置必须是 YAML 对象：{path}")
    return DifficultyTaggingConfig.model_validate(raw)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_taxonomy_path(path: str) -> list[str]:
    """Split a registered taxonomy path without making semantic guesses."""
    return [part.strip() for part in path.split(">") if part.strip()]


def compact_knowledge_result(final_result: dict[str, Any]) -> dict[str, Any]:
    def compact_points(key: str) -> list[dict[str, str]]:
        points = final_result.get(key)
        if not isinstance(points, list):
            return []
        rows: list[dict[str, str]] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            path = str(point.get("path", "") or "")
            levels = split_taxonomy_path(path)
            rows.append(
                {
                    "pk": str(point.get("pk", "") or ""),
                    "path": path,
                    # Knowledge units follow level-3 titles; module relation follows level 1.
                    "module": levels[0] if levels else "",
                    "knowledge_unit": levels[2] if len(levels) >= 3 else (levels[-1] if levels else ""),
                    "leaf_name": levels[-1] if levels else "",
                    "path_levels": levels,
                    "evidence": str(point.get("evidence", "") or ""),
                }
            )
        return rows

    profile = final_result.get("decision_profile")
    return {
        "schema": final_result.get("schema", ""),
        "main_knowledge_points": compact_points("main_knowledge_points"),
        "secondary_knowledge_points": compact_points("secondary_knowledge_points"),
        "question_structure": profile.get("question_structure", "") if isinstance(profile, dict) else "",
        "tagging_summary": profile.get("summary", "") if isinstance(profile, dict) else "",
    }


def upstream_is_publishable(trace: dict[str, Any], accepted_statuses: set[str]) -> tuple[bool, str]:
    if str(trace.get("status", "")) not in accepted_statuses:
        return False, "upstream_status_not_accepted"
    final_result = trace.get("final_result")
    if not isinstance(final_result, dict):
        return False, "missing_upstream_final_result"
    profile = final_result.get("decision_profile")
    if not isinstance(profile, dict) or profile.get("release_decision") != "accept":
        return False, "upstream_knowledge_tag_not_publishable"
    return True, ""


def build_model_payload(trace: dict[str, Any], scheme: SchemeConfig) -> dict[str, Any]:
    question = trace.get("question")
    if not isinstance(question, dict):
        raise ValueError("上游 trace 缺少 question 对象")
    final_result = trace.get("final_result")
    if not isinstance(final_result, dict):
        raise ValueError("上游 trace 缺少 final_result 对象")
    return {
        "question_id": str(trace.get("question_id", "") or ""),
        "subject": str(trace.get("subject", "") or question.get("subject", "")),
        "stage": str(trace.get("stage", "") or question.get("stage", "")),
        "reference_population": scheme.reference_population,
        "difficulty_scheme": scheme.id,
        "rubric_version": "six_dimension_100_point_v0.1",
        "question": {
            "stem": question.get("stem", ""),
            "options": question.get("options") or [],
            "answer": question.get("answer", ""),
            "analysis": question.get("analysis", ""),
            "visual_pages": question.get("visual_pages") or [],
        },
        "knowledge_tagging": compact_knowledge_result(final_result),
        "important_boundary": (
            "这是作答数据产生前的预测难度。答案与解析只用于复原最短有效解法，"
            "不得把它们当作学生作答时可见提示；不得输出真实正答率或 IRT 参数。"
        ),
    }


def validated_image_paths(payload: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for page in payload["question"].get("visual_pages") or []:
        if not isinstance(page, dict) or not page.get("path"):
            continue
        path = Path(str(page["path"]))
        expected = str(page.get("sha256", "") or "")
        if expected and sha256_file(path) != expected:
            raise ValueError(f"题图哈希不一致：{path}")
        paths.append(path)
    return paths


def apply_structural_gate(result: dict[str, Any], scheme: SchemeConfig) -> tuple[str, list[str]]:
    errors: list[str] = []
    if result["difficulty_scheme"] != scheme.id:
        errors.append("difficulty_scheme_mismatch")
    if result["reference_population"] != scheme.reference_population:
        errors.append("reference_population_mismatch")
    if result["difficulty_confidence"] < scheme.minimum_publish_confidence:
        errors.append("confidence_below_publish_threshold")
    if result["release_recommendation"] != "accept_provisional":
        errors.append("model_requested_manual_review")
    if result["review_flags"]:
        errors.append("review_flags_present")
    return ("scored" if not errors else "needs_review"), errors


def load_offline_results(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("离线结果文件必须是 JSON 数组")
    rows: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("question_id", "")):
            raise ValueError("离线结果中的每项都必须是带 question_id 的对象")
        rows[str(item["question_id"])] = item
    return rows


def process_trace(
    *,
    path: Path,
    config: DifficultyTaggingConfig,
    system_prompt: str,
    api_key: str,
    use_model: bool,
    offline_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    upstream = load_json(path)
    qid = str(upstream.get("question_id", "") or path.name.removesuffix(".tagging_trace.json"))
    accepted, reason = upstream_is_publishable(upstream, set(config.input.accepted_statuses))
    base = {
        "schema": "question_difficulty_trace_v0.1",
        "question_id": qid,
        "source_tagging_trace": str(path.resolve()),
        "source_tagging_trace_sha256": sha256_file(path),
        "difficulty_scheme": config.scheme.id,
        "rubric_version": "six_dimension_100_point_v0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not accepted:
        return {**base, "status": "skipped", "skip_reason": reason}

    question = upstream.get("question") if isinstance(upstream.get("question"), dict) else {}
    actual_subject = str(upstream.get("subject", "") or question.get("subject", ""))
    actual_stage = str(upstream.get("stage", "") or question.get("stage", ""))
    if actual_subject != config.scheme.subject or actual_stage != config.scheme.stage:
        return {
            **base,
            "status": "skipped",
            "skip_reason": "upstream_track_mismatch",
            "actual_subject": actual_subject,
            "actual_stage": actual_stage,
        }

    payload = build_model_payload(upstream, config.scheme)
    image_paths = validated_image_paths(payload)
    model_call: dict[str, Any] = {"called": False, "ok": False}
    if qid in offline_results:
        raw_result = offline_results[qid]
        model_call = {"called": False, "ok": True, "mode": "offline_seed"}
    elif use_model:
        model_call = call_json_model(
            api_key=api_key,
            system_prompt=system_prompt,
            user_payload=payload,
            image_paths=image_paths,
            model=config.node.model,
            api_url=config.provider.api_url,
            timeout=config.node.timeout_seconds,
            max_tokens=config.node.max_tokens,
            retries=config.node.retry_attempts - 1,
            reasoning_effort=config.node.reasoning_effort,
            validator=validate_difficulty_decision,
            repair_invalid_output=True,
        )
        if not model_call.get("ok") or not isinstance(model_call.get("parsed"), dict):
            return {
                **base,
                "status": "failed",
                "model_payload": payload,
                "model_call": model_call,
                "error": str(model_call.get("error", "model_call_failed")),
            }
        raw_result = model_call["parsed"]
    else:
        return {
            **base,
            "status": "ready_for_model",
            "model_payload": payload,
            "image_paths": [str(item) for item in image_paths],
        }

    result = validate_difficulty_decision(raw_result)
    if result["question_id"] != qid:
        raise ValueError(f"难度结果 question_id 不一致：{result['question_id']} != {qid}")
    status, gate_errors = apply_structural_gate(result, config.scheme)
    if use_model and qid not in offline_results and result["difficulty_source"] != "model_predicted":
        gate_errors.append("live_model_source_must_be_model_predicted")
        status = "needs_review"
    return {
        **base,
        "status": status,
        "model_payload": payload,
        "model_call": model_call,
        "final_result": result,
        "gate_errors": gate_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="在知识点打标下游预测题目难度")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--use-model", action="store_true")
    parser.add_argument("--offline-results", type=Path)
    args = parser.parse_args()

    config = load_config(args.config.resolve())
    input_dir = (args.input_dir or workspace_path(config.input.directory)).resolve()
    out_dir = (args.out_dir or workspace_path(config.output.directory)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = workspace_path(config.node.prompt)
    system_prompt = prompt_path.read_text(encoding="utf-8")
    offline_results = load_offline_results(args.offline_results.resolve() if args.offline_results else None)

    api_key = os.getenv(config.provider.api_key_env, "")
    if args.use_model and not api_key:
        raise SystemExit(f"缺少模型密钥环境变量：{config.provider.api_key_env}")
    configure_model_transport(
        ModelTransportSettings(
            max_connections=config.provider.max_connections,
            max_keepalive_connections=config.provider.max_keepalive_connections,
            requests_per_second=config.provider.requests_per_second,
            burst=config.provider.burst,
            retry_base_seconds=config.provider.retry_base_seconds,
            retry_max_seconds=config.provider.retry_max_seconds,
            retry_jitter=config.provider.retry_jitter,
            circuit_breaker_failures=config.provider.circuit_breaker_failures,
            circuit_breaker_cooldown_seconds=config.provider.circuit_breaker_cooldown_seconds,
        )
    )
    selected_ids = set(args.question_id)
    paths = sorted(input_dir.glob("*.tagging_trace.json"))
    if selected_ids:
        paths = [path for path in paths if path.name.removesuffix(".tagging_trace.json") in selected_ids]
    if args.limit > 0:
        paths = paths[: args.limit]

    items: list[dict[str, Any]] = []
    try:
        for path in paths:
            item = process_trace(
                path=path,
                config=config,
                system_prompt=system_prompt,
                api_key=api_key,
                use_model=args.use_model,
                offline_results=offline_results,
            )
            items.append(item)
            write_json(out_dir / f"{item['question_id']}.difficulty_trace.json", item)
    finally:
        close_model_transport()

    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    summary = {
        "schema": "question_difficulty_run_summary_v0.1",
        "config_version": config.version,
        "difficulty_scheme": config.scheme.id,
        "rubric_version": "six_dimension_100_point_v0.1",
        "reference_population": config.scheme.reference_population,
        "input_directory": str(input_dir),
        "output_directory": str(out_dir),
        "counts": counts,
        "items": [
            {
                "question_id": item["question_id"],
                "status": item["status"],
                "total_score": (item.get("final_result") or {}).get("total_score"),
                "difficulty_level": (item.get("final_result") or {}).get("difficulty_level"),
                "difficulty_label": (item.get("final_result") or {}).get("difficulty_label"),
                "difficulty_confidence": (item.get("final_result") or {}).get("difficulty_confidence"),
                "trace_path": str((out_dir / f"{item['question_id']}.difficulty_trace.json").resolve()),
            }
            for item in items
        ],
    }
    write_json(out_dir / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not counts.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
