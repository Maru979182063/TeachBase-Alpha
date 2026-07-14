from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {"stable", "experimental", "shadow", "validation", "effective", "deprecated"}
REQUIRED_FIELDS = {
    "pipeline_id",
    "pipeline_name",
    "pipeline_version",
    "status",
    "owner",
    "description",
    "entrypoint",
    "config_path",
    "feature_flags",
    "input_contracts",
    "output_contracts",
    "owned_output_roots",
    "forbidden_write_roots",
    "stable_dependencies",
    "optional_dependencies",
    "model_provider",
    "default_model",
    "prompt_bundle",
    "prompt_version",
    "downstream_pipelines",
    "runtime_import_policy",
    "database_write_policy",
    "release_gate_policy",
    "fallback_pipeline",
    "rollback_method",
    "baseline_id",
    "last_validated_commit",
}


def _load_json_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be JSON-compatible YAML in this no-new-dependency validator: {exc}") from exc


def _norm_root(raw: str) -> str:
    value = str(raw or "").replace("\\", "/").strip().strip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def _roots_conflict(left: str, right: str) -> bool:
    a = _norm_root(left)
    b = _norm_root(right)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _find_cycle(graph: dict[str, list[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def walk(node: str) -> list[str]:
        if node in visiting:
            idx = stack.index(node) if node in stack else 0
            return stack[idx:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            cycle = walk(nxt)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in sorted(graph):
        cycle = walk(node)
        if cycle:
            return cycle
    return []


def validate_registry(registry_path: Path, flags_path: Path, workspace: Path | None = None) -> dict[str, Any]:
    workspace = workspace or Path.cwd()
    registry = _load_json_yaml(registry_path)
    flags = _load_json_yaml(flags_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    pipelines = registry.get("pipelines")
    if not isinstance(pipelines, list) or not pipelines:
        errors.append({"code": "missing_pipelines", "path": str(registry_path)})
        pipelines = []

    flag_defs = flags.get("flags") if isinstance(flags.get("flags"), dict) else {}
    for flag_id, flag in flag_defs.items():
        if not isinstance(flag, dict):
            errors.append({"code": "invalid_flag_entry", "flag": flag_id})
            continue
        if flag.get("default") is not False:
            errors.append({"code": "feature_flag_default_not_false", "flag": flag_id})

    ids: list[str] = []
    owned_roots: list[tuple[str, str]] = []
    graph: dict[str, list[str]] = {}
    known_ids = {str(p.get("pipeline_id")) for p in pipelines if isinstance(p, dict)}

    for idx, pipeline in enumerate(pipelines):
        if not isinstance(pipeline, dict):
            errors.append({"code": "invalid_pipeline_entry", "index": idx})
            continue
        pid = str(pipeline.get("pipeline_id") or "")
        ids.append(pid)
        missing = sorted(field for field in REQUIRED_FIELDS if field not in pipeline)
        if missing:
            errors.append({"code": "missing_required_fields", "pipeline_id": pid, "fields": missing})
        status = pipeline.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append({"code": "invalid_status", "pipeline_id": pid, "status": status})
        for field in ["entrypoint", "config_path"]:
            path_value = str(pipeline.get(field) or "")
            if not path_value:
                errors.append({"code": f"missing_{field}", "pipeline_id": pid})
            elif not (workspace / path_value).exists():
                errors.append({"code": f"{field}_not_found", "pipeline_id": pid, "path": path_value})
        for flag in pipeline.get("feature_flags") or []:
            if str(flag) not in flag_defs:
                errors.append({"code": "unknown_feature_flag", "pipeline_id": pid, "flag": str(flag)})
        for owned in pipeline.get("owned_output_roots") or []:
            owned_norm = _norm_root(str(owned))
            for other_pid, other_root in owned_roots:
                if _roots_conflict(owned_norm, other_root):
                    errors.append({
                        "code": "owned_output_root_conflict",
                        "pipeline_id": pid,
                        "root": owned_norm,
                        "other_pipeline_id": other_pid,
                        "other_root": other_root,
                    })
            owned_roots.append((pid, owned_norm))
        for owned in pipeline.get("owned_output_roots") or []:
            for forbidden in pipeline.get("forbidden_write_roots") or []:
                if _roots_conflict(str(owned), str(forbidden)):
                    errors.append({
                        "code": "owned_forbidden_root_conflict",
                        "pipeline_id": pid,
                        "owned_root": str(owned),
                        "forbidden_root": str(forbidden),
                    })
        downstream = [str(item) for item in (pipeline.get("downstream_pipelines") or [])]
        unknown_downstream = [item for item in downstream if item not in known_ids]
        if unknown_downstream:
            errors.append({"code": "unknown_downstream_pipeline", "pipeline_id": pid, "downstream": unknown_downstream})
        graph[pid] = downstream

        runtime_policy = pipeline.get("runtime_import_policy") or {}
        db_policy = pipeline.get("database_write_policy") or {}
        if status != "effective" and runtime_policy.get("default_enabled") is not False:
            errors.append({"code": "non_effective_runtime_import_default_enabled", "pipeline_id": pid, "status": status})
        if status in {"experimental", "shadow"} and db_policy.get("default_enabled") is not False:
            errors.append({"code": "experimental_or_shadow_database_write_default_enabled", "pipeline_id": pid, "status": status})
        if status == "validation" and db_policy.get("default_enabled") is not False:
            warnings.append({"code": "validation_database_write_not_default_false", "pipeline_id": pid})

    duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
    for pid in duplicates:
        errors.append({"code": "duplicate_pipeline_id", "pipeline_id": pid})

    cycle = _find_cycle(graph)
    if cycle:
        errors.append({"code": "downstream_cycle", "cycle": cycle})

    return {
        "schema_version": "pipeline_registry_validation_result.v0.1",
        "registry_path": str(registry_path),
        "flags_path": str(flags_path),
        "pipeline_count": len(pipelines),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "ok": len(errors) == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the TeachBase pipeline registry skeleton.")
    parser.add_argument("--registry", default="config/pipeline_registry.yaml")
    parser.add_argument("--flags", default="config/pipeline_feature_flags.yaml")
    parser.add_argument("--json", action="store_true", help="Print the full validation result as JSON.")
    args = parser.parse_args()
    result = validate_registry(Path(args.registry), Path(args.flags), Path.cwd())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(f"pipeline_registry_valid pipelines={result['pipeline_count']} warnings={result['warning_count']}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
