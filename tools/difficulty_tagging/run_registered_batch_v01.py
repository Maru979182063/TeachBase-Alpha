from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from difficulty_tagging.prompt_bundle import load_prompt_bundle
from difficulty_tagging.contracts import (
    ShortestSolutionGraph,
    normalize_canonical_projection,
    validate_difficulty_decision,
)
from difficulty_tagging.parallel_dimensions import (
    aggregate_dimension_judgments,
    validate_dimension_identity,
    validator_for_dimension,
)
from difficulty_tagging.registry import (
    AmbiguousRouteError,
    DifficultyRoute,
    LoadedRegistry,
    RouteNotFoundError,
    load_registry,
    resolve_route,
)
from difficulty_tagging.result_adapters import common_projection, validator_for
from difficulty_tagging.tag_difficulty_v01 import compact_knowledge_result
from knowledge_tagging.model_api import (
    ModelTransportSettings,
    call_json_model,
    close_model_transport,
    configure_model_transport,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = WORKSPACE_ROOT / "config" / "difficulty_tagging" / "registry_v01.yaml"
TERMINAL_ITEM_STATUSES = {"scored", "needs_review", "skipped", "ready_for_model"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_input_source(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        files = sorted(path.glob("*.tagging_trace.json"), key=lambda item: item.name)
        if not files:
            raise ValueError(f"输入目录没有 tagging trace：{path}")
        for item in files:
            digest.update(item.name.encode("utf-8"))
            digest.update(item.read_bytes())
        return digest.hexdigest()
    raise ValueError(f"输入不存在：{path}")


def workspace_child(value: str | Path) -> Path:
    path = Path(value)
    candidate = path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()
    try:
        candidate.relative_to(WORKSPACE_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"配置路径越出工作区：{value}") from exc
    return candidate


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        files = sorted(path.glob("*.tagging_trace.json"), key=lambda item: item.name)
        if not files:
            raise ValueError(f"输入目录没有 tagging trace：{path}")
        values = [json.loads(item.read_text(encoding="utf-8-sig")) for item in files]
        if not all(isinstance(item, dict) for item in values):
            raise ValueError("每个 tagging trace 必须是 JSON 对象")
        return values
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        raw = json.loads(text)
        if isinstance(raw, list):
            values = raw
        elif isinstance(raw, dict):
            values = next(
                (raw[key] for key in ("questions", "items", "rows", "traces") if isinstance(raw.get(key), list)),
                [raw],
            )
        else:
            raise ValueError("输入 JSON 顶层必须为对象或数组")
    if not all(isinstance(item, dict) for item in values):
        raise ValueError("每条输入都必须是 JSON 对象")
    return list(values)


def question_id(record: dict[str, Any]) -> str:
    for key in ("question_id", "id", "qid", "item_id"):
        value = str(record.get(key, "") or "").strip()
        if value:
            return value
    raise ValueError("输入记录缺少 question_id")


def question_context(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    question = record.get("question") if isinstance(record.get("question"), dict) else record
    context = {
        "subject": str(record.get("subject", "") or question.get("subject", "")),
        "stage": str(record.get("stage", "") or question.get("stage", "")),
        "question_type": str(record.get("question_type", "") or question.get("question_type", "")),
    }
    return question, context


def upstream_release_gate(record: dict[str, Any], required: bool) -> tuple[bool, str]:
    if not required:
        return True, ""
    if str(record.get("status", "")) != "tagged":
        return False, "upstream_status_not_tagged"
    final_result = record.get("final_result")
    if not isinstance(final_result, dict):
        return False, "missing_upstream_final_result"
    decision_profile = final_result.get("decision_profile")
    if not isinstance(decision_profile, dict) or decision_profile.get("release_decision") != "accept":
        return False, "upstream_release_not_accepted"
    return True, ""


def build_canonical_solution(record: dict[str, Any]) -> dict[str, Any]:
    supplied = record.get("canonical_solution")
    if isinstance(supplied, dict):
        supplied_graph = supplied.get("shortest_solution_graph")
        if not isinstance(supplied_graph, dict):
            raise ValueError("canonical_solution_missing_shortest_solution_graph")
        graph = ShortestSolutionGraph.model_validate(supplied_graph).model_dump(mode="json")
        return {
            "source": str(supplied.get("source", "business_or_teacher_canonical_solution")),
            "source_schema": str(supplied.get("source_schema", "") or ""),
            "question_facts": supplied.get("question_facts") or {},
            "shortest_solution_graph": graph,
            "sha256": sha256_json(graph),
            "quality": str(supplied.get("quality", "reviewed")),
            "policy": "difficulty_model_must_reference_this_graph_and_must_not_create_or_replace_solution_steps",
        }

    concepts = record.get("model_concepts")
    if not isinstance(concepts, dict):
        raise ValueError("canonical_solution_missing_model_concepts")
    evidence = concepts.get("task_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("canonical_solution_missing_task_evidence")
    nodes: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("canonical_solution_evidence_item_invalid")
        node_id = str(item.get("id", "") or "").strip()
        fact = str(item.get("fact", "") or "").strip()
        dependencies = item.get("depends_on") or []
        if not node_id or not fact or not isinstance(dependencies, list):
            raise ValueError("canonical_solution_evidence_fields_invalid")
        nodes.append(
            {
                "node_id": node_id,
                "node_type": "frozen_upstream_solution_step",
                "statement": fact,
                "depends_on": [str(value) for value in dependencies],
                "student_visibility": "canonical_path_not_a_student_hint",
            }
        )
    node_ids = [item["node_id"] for item in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("canonical_solution_duplicate_node_id")
    referenced = {dependency for item in nodes for dependency in item["depends_on"]}
    unknown = referenced.difference(node_ids)
    if unknown:
        raise ValueError(f"canonical_solution_unknown_dependencies:{sorted(unknown)}")
    sinks = [node_id for node_id in node_ids if node_id not in referenced]
    if not sinks:
        raise ValueError("canonical_solution_has_no_final_node")
    final_node_id = sinks[0]
    if len(sinks) > 1:
        final_node_id = "canonical_final"
        suffix = 1
        while final_node_id in node_ids:
            suffix += 1
            final_node_id = f"canonical_final_{suffix}"
        nodes.append(
            {
                "node_id": final_node_id,
                "node_type": "canonical_aggregation",
                "statement": "汇总冻结解法中的并列结论",
                "depends_on": sinks,
                "student_visibility": "canonical_path_not_a_student_hint",
            }
        )
    graph = ShortestSolutionGraph.model_validate(
        {"nodes": nodes, "final_node_id": final_node_id}
    ).model_dump(mode="json")
    return {
        "source": "frozen_upstream_task_evidence",
        "source_schema": str(concepts.get("schema", "") or ""),
        "question_facts": concepts.get("question_facts") or {},
        "shortest_solution_graph": graph,
        "sha256": sha256_json(graph),
        "quality": "provisional_model_extracted_evidence",
        "policy": "difficulty_model_must_reference_this_graph_and_must_not_create_or_replace_solution_steps",
    }


def build_payload(record: dict[str, Any], route: DifficultyRoute) -> dict[str, Any]:
    question, context = question_context(record)
    upstream_result = record.get("final_result") if isinstance(record.get("final_result"), dict) else {}
    payload = {
        "question_id": question_id(record),
        **context,
        "reference_population": route.reference_population,
        "difficulty_scheme": route.difficulty_scheme,
        "rubric_version": route.rubric_version,
        "question": {
            "stem": question.get("stem", ""),
            "options": question.get("options") or [],
            "answer": question.get("answer", ""),
            "analysis": question.get("analysis", ""),
            "material": question.get("material", ""),
            "visual_pages": question.get("visual_pages") or [],
        },
        "knowledge_tagging": compact_knowledge_result(upstream_result),
        "important_boundary": (
            "这是作答数据产生前的预测难度；不得编造正答率、区分度或 IRT 参数。"
            "不得重新解题或选择其他解法；只能使用 canonical_solution 中冻结的路径。"
        ),
    }
    if route.result_adapter in {
        "math_canonical_projection_v01",
        "math_parallel_dimension_projection_v1",
    }:
        payload["canonical_solution"] = build_canonical_solution(record)
    return payload


def image_paths_from_payload(payload: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for page in payload["question"].get("visual_pages") or []:
        if not isinstance(page, dict) or not page.get("path"):
            continue
        path = Path(str(page["path"])).resolve()
        expected = str(page.get("sha256", "") or "")
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"题图哈希不一致：{path}")
        paths.append(path)
    return paths


def validate_knowledge_point_provenance(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    upstream = payload.get("knowledge_tagging")
    if not isinstance(upstream, dict):
        raise ValueError("输入缺少 knowledge_tagging")

    allowed: dict[str, dict[str, str]] = {}
    for source_key, role in (("main_knowledge_points", "main"), ("secondary_knowledge_points", "secondary")):
        points = upstream.get(source_key)
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            pk = str(point.get("pk", "") or "")
            path = str(point.get("path", "") or "")
            if not pk or pk in allowed:
                raise ValueError("上游知识点 pk 缺失或重复")
            allowed[pk] = {
                "role": role,
                "module": str(point.get("module", "") or ""),
                "name": str(point.get("knowledge_unit", "") or path.rsplit(">", 1)[-1].strip()),
            }

    dimensions = result.get("dimension_scores")
    knowledge = dimensions.get("knowledge_complexity") if isinstance(dimensions, dict) else None
    if result.get("schema") == "question_difficulty_result_v0.4" and isinstance(knowledge, dict):
        semantic = result.get("semantic_reasoning")
        units = semantic.get("required_knowledge_units") if isinstance(semantic, dict) else None
        if not isinstance(units, list):
            raise ValueError("语义难度结果缺少 required_knowledge_units")
        registered_pks = [
            str(item.get("registered_pk", "") or "")
            for item in units
            if isinstance(item, dict) and item.get("source") == "registered_tag"
        ]
        if not registered_pks:
            raise ValueError("必要知识单元必须至少追溯一个上游正式标签")
        if len(registered_pks) != len(set(registered_pks)):
            raise ValueError("必要知识单元重复引用上游正式标签")
        unknown = set(registered_pks).difference(allowed)
        if unknown:
            raise ValueError(f"必要知识单元引用了上游未发布的知识点 pk：{sorted(unknown)}")
        registered_units = [
            item
            for item in units
            if isinstance(item, dict) and item.get("source") == "registered_tag"
        ]
        registered_unit_names: list[str] = []
        for item in registered_units:
            pk = str(item.get("registered_pk", "") or "")
            source = allowed[pk]
            if str(item.get("module", "") or "") != source["module"]:
                raise ValueError(f"必要知识单元 {pk} 的 module 必须原样来自上游一级模块")
            if str(item.get("name", "") or "") != source["name"]:
                raise ValueError(f"必要知识单元 {pk} 的 name 必须使用上游三级标题")
            registered_unit_names.append(source["name"])
        if len(registered_unit_names) != len(set(registered_unit_names)):
            raise ValueError("同一三级标题只能统计为一个必要知识单元")
        knowledge["knowledge_points"] = [
            {"pk": pk, **allowed[pk]}
            for pk in registered_pks
        ]
        if any(
            isinstance(item, dict) and item.get("source") == "implicit_prerequisite"
            for item in units
        ):
            flags = result.setdefault("review_flags", [])
            if "implicit_knowledge_unit_unregistered" not in flags:
                if len(flags) >= 6:
                    raise ValueError("隐含知识单元需要人工复核，但 review_flags 已达到合同上限")
                flags.append("implicit_knowledge_unit_unregistered")
            result["release_recommendation"] = "manual_review"
    selected = knowledge.get("knowledge_points") if isinstance(knowledge, dict) else None
    if not isinstance(selected, list) or not selected:
        raise ValueError("难度结果缺少知识点依据")

    selected_pks: set[str] = set()
    selected_modules: list[str] = []
    for point in selected:
        if not isinstance(point, dict):
            raise ValueError("知识点依据必须是对象")
        pk = str(point.get("pk", "") or "")
        if pk in selected_pks:
            raise ValueError(f"难度结果重复引用上游知识点 pk：{pk}")
        selected_pks.add(pk)
        source = allowed.get(pk)
        if source is None:
            raise ValueError(f"难度结果引用了上游未发布的知识点 pk：{pk}")
        for field in ("role", "module", "name"):
            actual = str(point.get(field, "") or "")
            if actual != source[field]:
                raise ValueError(f"知识点 {pk} 的 {field} 必须原样来自上游：{source[field]}")
        selected_modules.append(source["module"])

    if result.get("schema") != "question_difficulty_result_v0.4":
        expected_relation = (
            "single"
            if len(selected_modules) == 1
            else "same_module"
            if len(set(selected_modules)) == 1
            else "cross_module"
        )
        if knowledge.get("module_relation") != expected_relation:
            raise ValueError(f"module_relation 应由上游模块归属确定为 {expected_relation}")
    return result


def result_validator_for(route: DifficultyRoute, payload: dict[str, Any]):
    base_validator = validator_for(route.result_adapter)
    if route.result_adapter == "math_canonical_projection_v01":
        canonical = payload.get("canonical_solution")
        graph = canonical.get("shortest_solution_graph") if isinstance(canonical, dict) else None
        if not isinstance(graph, dict):
            raise ValueError("输入缺少 canonical_solution.shortest_solution_graph")

        def validate_canonical(raw: dict[str, Any]) -> dict[str, Any]:
            shaped = base_validator(raw)
            normalized = normalize_canonical_projection(shaped, graph)
            return validate_knowledge_point_provenance(normalized, payload)

        return validate_canonical
    if route.result_adapter not in {
        "math_six_dimension_v01",
        "math_six_dimension_semantic_v02",
        "math_six_dimension_semantic_v03",
        "math_six_dimension_semantic_v04",
    }:
        return base_validator

    def validate(raw: dict[str, Any]) -> dict[str, Any]:
        return validate_knowledge_point_provenance(base_validator(raw), payload)

    return validate


def configure_provider(provider: Any) -> None:
    configure_model_transport(
        ModelTransportSettings(
            max_connections=provider.max_connections,
            max_keepalive_connections=provider.max_keepalive_connections,
            requests_per_second=provider.requests_per_second,
            burst=provider.burst,
            retry_base_seconds=provider.retry_base_seconds,
            retry_max_seconds=provider.retry_max_seconds,
            retry_jitter="full",
            circuit_breaker_failures=provider.circuit_breaker_failures,
            circuit_breaker_cooldown_seconds=provider.circuit_breaker_cooldown_seconds,
        )
    )


def dimension_prompt_provenance(route: DifficultyRoute) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in route.dimension_nodes:
        prompt = load_prompt_bundle(workspace_child(node.prompt_bundle))
        rows.append(
            {
                "node_id": node.node_id,
                "dimension_id": node.dimension_id,
                "prompt_id": prompt.value.prompt_id,
                "prompt_version": prompt.value.version,
                "prompt_sha256": prompt.sha256,
                "few_shot_ids": [item.example_id for item in prompt.value.few_shots],
            }
        )
    return rows


def run_parallel_dimension_nodes(
    *,
    payload: dict[str, Any],
    route: DifficultyRoute,
    provider: Any,
    api_key: str,
    prior_trace: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """并行执行六个独立维度节点；已成功且版本未变的节点可在重试时复用。"""
    prior_nodes = (
        prior_trace.get("dimension_nodes")
        if isinstance(prior_trace, dict) and isinstance(prior_trace.get("dimension_nodes"), dict)
        else {}
    )
    images = image_paths_from_payload(payload)
    node_traces: dict[str, dict[str, Any]] = {}

    def execute(node: Any) -> tuple[str, dict[str, Any]]:
        prompt = load_prompt_bundle(workspace_child(node.prompt_bundle))
        validator = validator_for_dimension(node.dimension_id)
        previous = prior_nodes.get(node.node_id) if isinstance(prior_nodes, dict) else None
        if isinstance(previous, dict) and previous.get("prompt_sha256") == prompt.sha256:
            previous_call = previous.get("model_call")
            previous_parsed = previous_call.get("parsed") if isinstance(previous_call, dict) else None
            if isinstance(previous_call, dict) and previous_call.get("ok") and isinstance(previous_parsed, dict):
                parsed = validate_dimension_identity(
                    validator(previous_parsed), dimension_id=node.dimension_id, payload=payload
                )
                return node.node_id, {
                    **previous,
                    "model_call": {**previous_call, "parsed": parsed},
                    "reused_from_prior_trace": True,
                }

        node_payload = {
            **payload,
            "dimension_id": node.dimension_id,
            "dimension_boundary": (
                "只判断 dimension_id 指定的一个维度；不得输出其他维度、总分或难度标签。"
            ),
        }

        def validate(raw: dict[str, Any]) -> dict[str, Any]:
            return validate_dimension_identity(
                validator(raw), dimension_id=node.dimension_id, payload=payload
            )

        model_call = call_json_model(
            api_key=api_key,
            system_prompt=prompt.value.system_prompt,
            user_payload=node_payload,
            image_paths=images,
            model=provider.model,
            api_url=provider.api_url,
            timeout=provider.timeout_seconds,
            max_tokens=node.max_tokens,
            retries=provider.retry_attempts - 1,
            reasoning_effort=provider.reasoning_effort,
            validator=validate,
            few_shots=prompt.value.few_shot_pairs(),
            repair_invalid_output=True,
        )
        return node.node_id, {
            "node_id": node.node_id,
            "dimension_id": node.dimension_id,
            "prompt_id": prompt.value.prompt_id,
            "prompt_version": prompt.value.version,
            "prompt_sha256": prompt.sha256,
            "few_shot_ids": [item.example_id for item in prompt.value.few_shots],
            "model_call": model_call,
            "reused_from_prior_trace": False,
        }

    # 这里的并发单位是同一道题的六个维度，不是六道题。
    with ThreadPoolExecutor(max_workers=len(route.dimension_nodes)) as executor:
        futures = {executor.submit(execute, node): node for node in route.dimension_nodes}
        for future in as_completed(futures):
            node = futures[future]
            try:
                node_id, trace = future.result()
            except Exception as exc:
                node_id = node.node_id
                trace = {
                    "node_id": node.node_id,
                    "dimension_id": node.dimension_id,
                    "model_call": {
                        "called": True,
                        "ok": False,
                        "error": f"dimension_node_exception:{type(exc).__name__}:{exc}",
                        "attempts": [],
                    },
                    "reused_from_prior_trace": False,
                }
            node_traces[node_id] = trace

    parsed_by_dimension: dict[str, dict[str, Any]] = {}
    for node in route.dimension_nodes:
        trace = node_traces[node.node_id]
        model_call = trace.get("model_call")
        parsed = model_call.get("parsed") if isinstance(model_call, dict) else None
        if isinstance(model_call, dict) and model_call.get("ok") and isinstance(parsed, dict):
            parsed_by_dimension[node.dimension_id] = parsed

    if len(parsed_by_dimension) != len(route.dimension_nodes):
        return node_traces, None
    return node_traces, aggregate_dimension_judgments(parsed_by_dimension, payload=payload)


def gate_model_result(result: dict[str, Any], route: DifficultyRoute, *, live: bool) -> tuple[str, list[str]]:
    errors: list[str] = []
    if result.get("difficulty_scheme") != route.difficulty_scheme:
        errors.append("difficulty_scheme_mismatch")
    if result.get("rubric_version") != route.rubric_version:
        errors.append("rubric_version_mismatch")
    if result.get("reference_population") != route.reference_population:
        errors.append("reference_population_mismatch")
    if float(result.get("difficulty_confidence", 0)) < route.minimum_publish_confidence:
        errors.append("confidence_below_publish_threshold")
    if result.get("release_recommendation") != "accept_provisional":
        errors.append("model_requested_manual_review")
    if result.get("review_flags"):
        errors.append("review_flags_present")
    total_score = result.get("total_score")
    if isinstance(total_score, int) and route.boundary_review_margin_points:
        cut_points = (29, 39, 64, 85)
        if any(
            abs(total_score - cut_point) <= route.boundary_review_margin_points
            for cut_point in cut_points
        ):
            errors.append("score_near_label_boundary")
    if live and result.get("difficulty_source") != "model_predicted":
        errors.append("live_result_source_must_be_model_predicted")
    return ("scored" if not errors else "needs_review"), errors


def trace_name(qid: str) -> str:
    return f"{hashlib.sha256(qid.encode('utf-8')).hexdigest()[:24]}.difficulty_trace.json"


def process_record(
    record: dict[str, Any],
    *,
    loaded_registry: LoadedRegistry,
    use_model: bool,
    offline_results: dict[str, dict[str, Any]],
    prior_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qid = question_id(record)
    record_sha256 = sha256_json(record)
    base = {
        "schema": "registered_question_difficulty_trace_v1",
        "question_id": qid,
        "input_record_sha256": record_sha256,
        "registry_version": loaded_registry.value.version,
        "registry_sha256": loaded_registry.sha256,
        "created_at": utc_now(),
    }
    accepted, reason = upstream_release_gate(record, loaded_registry.value.policies.require_upstream_release)
    if not accepted:
        return {**base, "status": "skipped", "skip_reason": reason}

    _, context = question_context(record)
    try:
        route = resolve_route(loaded_registry.value, context)
    except RouteNotFoundError as exc:
        return {
            **base,
            "status": "needs_review",
            "gate_errors": ["no_runnable_route"],
            "route_context": context,
            "error": str(exc),
        }
    except AmbiguousRouteError as exc:
        return {
            **base,
            "status": "failed",
            "retryable": False,
            "error_code": "ambiguous_route",
            "route_context": context,
            "error": str(exc),
        }

    prompt_loaded = load_prompt_bundle(workspace_child(route.prompt_bundle))
    active_prompts = [prompt_loaded]
    if route.execution_mode == "parallel_dimension_nodes_v1":
        active_prompts = [
            load_prompt_bundle(workspace_child(node.prompt_bundle))
            for node in route.dimension_nodes
        ]
    if (
        route.status == "active"
        and loaded_registry.value.policies.require_few_shot_for_active_route
        and any(not prompt.value.few_shots for prompt in active_prompts)
    ):
        return {
            **base,
            "status": "failed",
            "retryable": False,
            "error_code": "active_route_requires_few_shot",
            "route_id": route.route_id,
        }

    try:
        payload = build_payload(record, route)
    except ValueError as exc:
        return {
            **base,
            "status": "needs_review",
            "retryable": False,
            "error_code": "canonical_solution_unavailable",
            "route_id": route.route_id,
            "gate_errors": ["canonical_solution_unavailable"],
            "error": str(exc),
        }
    provenance = {
        "route_id": route.route_id,
        "route_status": route.status,
        "provider_id": route.provider_id,
        "prompt_id": prompt_loaded.value.prompt_id,
        "prompt_version": prompt_loaded.value.version,
        "prompt_sha256": prompt_loaded.sha256,
        "few_shot_ids": [item.example_id for item in prompt_loaded.value.few_shots],
        "result_adapter": route.result_adapter,
        "label_scheme": route.label_scheme,
        "execution_mode": route.execution_mode,
    }
    if route.execution_mode == "parallel_dimension_nodes_v1":
        provenance["dimension_prompts"] = dimension_prompt_provenance(route)
    canonical = payload.get("canonical_solution")
    if isinstance(canonical, dict):
        provenance.update(
            {
                "canonical_solution_source": canonical.get("source"),
                "canonical_solution_quality": canonical.get("quality"),
                "canonical_solution_sha256": canonical.get("sha256"),
            }
        )
    if qid in offline_results:
        if route.execution_mode == "parallel_dimension_nodes_v1":
            result = validate_difficulty_decision(offline_results[qid])
            result = validate_knowledge_point_provenance(result, payload)
        else:
            validator = result_validator_for(route, payload)
            result = validator(offline_results[qid])
        if result.get("question_id") != qid:
            return {
                **base,
                "status": "failed",
                "retryable": False,
                "error_code": "offline_result_question_id_mismatch",
                "route_id": route.route_id,
                "provenance": provenance,
            }
        status, gate_errors = gate_model_result(result, route, live=False)
        return {
            **base,
            "status": status,
            "route_id": route.route_id,
            "difficulty": common_projection(result),
            "subject_result": result,
            "gate_errors": gate_errors,
            "model_call": {"called": False, "ok": True, "mode": "offline_expert_replay"},
            "provenance": {**provenance, "execution_mode": "offline_expert_replay"},
        }
    if not use_model:
        return {
            **base,
            "status": "ready_for_model",
            "route_id": route.route_id,
            "model_payload": payload,
            "provenance": provenance,
        }

    provider = loaded_registry.value.provider(route.provider_id)
    api_key = os.getenv(provider.api_key_env, "")
    if not api_key:
        return {
            **base,
            "status": "failed",
            "retryable": False,
            "error_code": "missing_provider_api_key",
            "route_id": route.route_id,
            "provenance": provenance,
        }
    if route.execution_mode == "parallel_dimension_nodes_v1":
        node_traces, result = run_parallel_dimension_nodes(
            payload=payload,
            route=route,
            provider=provider,
            api_key=api_key,
            prior_trace=prior_trace,
        )
        if result is None:
            failed_nodes = [
                node_id
                for node_id, trace in node_traces.items()
                if not isinstance(trace.get("model_call"), dict)
                or not trace["model_call"].get("ok")
            ]
            return {
                **base,
                "status": "failed",
                "retryable": True,
                "error_code": "dimension_nodes_incomplete",
                "failed_dimension_nodes": sorted(failed_nodes),
                "route_id": route.route_id,
                "model_payload": payload,
                "dimension_nodes": node_traces,
                "model_call": {
                    "called": True,
                    "ok": False,
                    "mode": "parallel_dimension_nodes_v1",
                },
                "provenance": provenance,
            }
        result = validate_knowledge_point_provenance(result, payload)
        status, gate_errors = gate_model_result(result, route, live=True)
        return {
            **base,
            "status": status,
            "route_id": route.route_id,
            "difficulty": common_projection(result),
            "subject_result": result,
            "gate_errors": gate_errors,
            "dimension_nodes": node_traces,
            "model_call": {
                "called": True,
                "ok": True,
                "mode": "parallel_dimension_nodes_v1",
                "call_count": sum(
                    0 if trace.get("reused_from_prior_trace") else 1
                    for trace in node_traces.values()
                ),
            },
            "provenance": provenance,
        }

    validator = result_validator_for(route, payload)
    model_call = call_json_model(
        api_key=api_key,
        system_prompt=prompt_loaded.value.system_prompt,
        user_payload=payload,
        image_paths=image_paths_from_payload(payload),
        model=provider.model,
        api_url=provider.api_url,
        timeout=provider.timeout_seconds,
        max_tokens=provider.max_tokens,
        retries=provider.retry_attempts - 1,
        reasoning_effort=provider.reasoning_effort,
        validator=validator,
        few_shots=prompt_loaded.value.few_shot_pairs(),
        repair_invalid_output=True,
    )
    if not model_call.get("ok") or not isinstance(model_call.get("parsed"), dict):
        attempts = model_call.get("attempts") if isinstance(model_call.get("attempts"), list) else []
        retryable = bool(attempts) and all(bool(item.get("retryable")) for item in attempts)
        if model_call.get("error") == "circuit_open":
            retryable = True
        return {
            **base,
            "status": "failed",
            "retryable": retryable,
            "error_code": "model_call_failed",
            "route_id": route.route_id,
            "model_payload": payload,
            "model_call": model_call,
            "provenance": provenance,
        }
    result = model_call["parsed"]
    if result.get("question_id") != qid:
        return {
            **base,
            "status": "failed",
            "retryable": False,
            "error_code": "result_question_id_mismatch",
            "route_id": route.route_id,
            "model_call": model_call,
            "provenance": provenance,
        }
    status, gate_errors = gate_model_result(result, route, live=True)
    return {
        **base,
        "status": status,
        "route_id": route.route_id,
        "difficulty": common_projection(result),
        "subject_result": result,
        "gate_errors": gate_errors,
        "model_call": model_call,
        "provenance": provenance,
    }


def run_batch(
    *,
    input_path: Path,
    registry_path: Path,
    output_dir: Path,
    selected_ids: set[str],
    use_model: bool,
    resume: bool,
    offline_results: dict[str, dict[str, Any]],
    max_workers: int = 4,
    selection_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_workers < 1:
        raise ValueError("max_workers 必须大于等于 1")
    loaded_registry = load_registry(registry_path, WORKSPACE_ROOT)
    rows = load_rows(input_path)
    ids = [question_id(item) for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("输入中存在重复 question_id")
    if selected_ids:
        missing = selected_ids.difference(ids)
        if missing:
            raise ValueError(f"指定 question_id 不存在：{sorted(missing)}")
        rows = [item for item in rows if question_id(item) in selected_ids]

    providers = {route.provider_id for route in loaded_registry.value.routes if route.enabled}
    if len(providers) != 1:
        raise ValueError("当前单模型运行模式要求所有已启用路由只引用一个 provider")
    configure_provider(loaded_registry.value.provider(next(iter(providers))))

    output_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = output_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    def process_and_persist(record: dict[str, Any]) -> dict[str, Any]:
        qid = question_id(record)
        trace_path = traces_dir / trace_name(qid)
        previous_for_retry: dict[str, Any] | None = None
        if resume and trace_path.is_file():
            previous = json.loads(trace_path.read_text(encoding="utf-8"))
            prompt_is_current = True
            previous_route_id = str(previous.get("route_id", "") or "")
            if previous_route_id and isinstance(previous.get("provenance"), dict):
                route = next(
                    (item for item in loaded_registry.value.routes if item.route_id == previous_route_id),
                    None,
                )
                prompt_is_current = bool(route) and (
                    previous["provenance"].get("prompt_sha256")
                    == load_prompt_bundle(workspace_child(route.prompt_bundle)).sha256
                )
                if prompt_is_current and route.execution_mode == "parallel_dimension_nodes_v1":
                    observed = {
                        item.get("node_id"): item.get("prompt_sha256")
                        for item in previous["provenance"].get("dimension_prompts", [])
                        if isinstance(item, dict)
                    }
                    expected = {
                        node.node_id: load_prompt_bundle(
                            workspace_child(node.prompt_bundle)
                        ).sha256
                        for node in route.dimension_nodes
                    }
                    prompt_is_current = observed == expected
            same_input_and_registry = (
                previous.get("input_record_sha256") == sha256_json(record)
                and previous.get("registry_sha256") == loaded_registry.sha256
                and prompt_is_current
            )
            if (
                previous.get("status") in TERMINAL_ITEM_STATUSES
                and same_input_and_registry
            ):
                return previous
            if same_input_and_registry:
                previous_for_retry = previous
        result = process_record(
            record,
            loaded_registry=loaded_registry,
            use_model=use_model,
            offline_results=offline_results,
            prior_trace=previous_for_retry,
        )
        atomic_write(trace_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "event": "difficulty_item_persisted",
                    "question_id": qid,
                    "status": result.get("status", "unknown"),
                    "trace": str(trace_path),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return result

    try:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(rows) or 1)) as executor:
            results = list(executor.map(process_and_persist, rows))
    finally:
        close_model_transport()

    status_counts = Counter(str(item.get("status", "unknown")) for item in results)
    review_rows = [item for item in results if item.get("status") in {"needs_review", "failed"}]
    atomic_write(
        output_dir / "results.jsonl",
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in results),
    )
    atomic_write(
        output_dir / "review_queue.jsonl",
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in review_rows),
    )
    summary = {
        "schema": "registered_difficulty_batch_summary_v1",
        "registry_version": loaded_registry.value.version,
        "registry_sha256": loaded_registry.sha256,
        "input_uri": str(input_path.resolve()),
        "input_sha256": sha256_input_source(input_path),
        "output_uri": str(output_dir.resolve()),
        "use_model": use_model,
        "item_count": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "review_count": len(review_rows),
        "selection_provenance": selection_provenance or {"mode": "all_or_explicit_ids"},
        "finished_at": utc_now(),
    }
    atomic_write(output_dir / "run_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def load_offline_results(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list):
        raise ValueError("离线结果必须是 JSON 数组")
    results: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("离线结果的每一项必须是对象")
        qid = question_id(item)
        if qid in results:
            raise ValueError(f"离线结果 question_id 重复：{qid}")
        results[qid] = item
    return results


def load_plan_selection(path: Path, phase: str) -> tuple[set[str], dict[str, Any]]:
    raw_bytes = path.read_bytes()
    plan = json.loads(raw_bytes.decode("utf-8-sig"))
    phases = plan.get("public_phases")
    if not isinstance(phases, dict):
        raise ValueError("执行计划缺少 public_phases")
    values = phases.get(phase)
    if not isinstance(values, list) or not values or not all(isinstance(item, str) and item for item in values):
        raise ValueError(f"执行计划阶段不存在或题目列表无效：{phase}")
    if len(values) != len(set(values)):
        raise ValueError(f"执行计划阶段包含重复 question_id：{phase}")
    return set(values), {
        "mode": "frozen_plan_phase",
        "plan_uri": str(path.resolve()),
        "plan_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "phase": phase,
        "selected_count": len(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按难度注册表路由并执行豆包单模型 few-shot 打标")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--selection-plan", type=Path)
    parser.add_argument(
        "--selection-phase",
        choices=("calibration", "frozen_validation", "full_remainder"),
    )
    parser.add_argument("--use-model", action="store_true")
    parser.add_argument("--offline-results", type=Path)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()
    try:
        if args.selection_plan:
            if args.question_id:
                raise ValueError("--selection-plan 与 --question-id 不能同时使用")
            if not args.selection_phase:
                raise ValueError("--selection-plan 必须搭配 --selection-phase")
            selected_ids, selection_provenance = load_plan_selection(
                args.selection_plan.resolve(), args.selection_phase
            )
        else:
            if args.selection_phase:
                raise ValueError("--selection-phase 必须搭配 --selection-plan")
            selected_ids = set(args.question_id)
            selection_provenance = {
                "mode": "explicit_ids" if selected_ids else "all",
                "selected_count": len(selected_ids) if selected_ids else None,
            }
        summary = run_batch(
            input_path=args.input.resolve(),
            registry_path=args.registry.resolve(),
            output_dir=args.out_dir.resolve(),
            selected_ids=selected_ids,
            use_model=args.use_model,
            resume=not args.no_resume,
            offline_results=load_offline_results(args.offline_results.resolve() if args.offline_results else None),
            max_workers=args.max_workers,
            selection_provenance=selection_provenance,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error_code": "invalid_input_or_config", "error": str(exc)}, ensure_ascii=False))
        return 78
    print(json.dumps(summary, ensure_ascii=False))
    if summary["status_counts"].get("failed", 0):
        failed = [
            json.loads(line)
            for line in (Path(summary["output_uri"]) / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return 70 if any(item.get("status") == "failed" and item.get("retryable") for item in failed) else 65
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
