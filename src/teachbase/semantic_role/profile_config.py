from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_PROFILE_CONFIGS = [
    "common.yaml",
    "content_blocks.yaml",
    "document_types.yaml",
    "route_availability.yaml",
    "thresholds.yaml",
    "math.yaml",
    "english.yaml",
    "biology.yaml",
]


class SemanticProfileConfigError(ValueError):
    pass


def _read_json_yaml(path: Path, *, wrap_json_errors: bool) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        if not wrap_json_errors:
            raise
        raise SemanticProfileConfigError(f"config_must_be_json_compatible_yaml:{path}") from exc


def load_semantic_profile_configs(config_dir: Path, *, wrap_json_errors: bool = True) -> dict[str, Any]:
    configs: dict[str, Any] = {}
    for name in REQUIRED_PROFILE_CONFIGS:
        path = config_dir / name
        if not path.exists():
            raise SemanticProfileConfigError(f"missing_semantic_profile_config:{path}")
        configs[name] = _read_json_yaml(path, wrap_json_errors=wrap_json_errors)
    return configs


def load_workspace_semantic_profile_configs(workspace_root: Path, *, wrap_json_errors: bool = True) -> dict[str, Any]:
    return load_semantic_profile_configs(
        workspace_root / "config" / "semantic_profiles",
        wrap_json_errors=wrap_json_errors,
    )


def semantic_enums(configs: dict[str, Any]) -> dict[str, set[str]]:
    content = configs["content_blocks.yaml"]
    return {
        "semantic_roles": set((content.get("semantic_roles") or {}).keys()),
        "presentation_kinds": set((content.get("presentation_kinds") or {}).keys()),
        "dispositions": set((content.get("dispositions") or {}).keys()),
        "relation_types": set((content.get("relation_types") or {}).keys()),
        "routes": set((content.get("routes") or {}).keys()),
    }


def route_availability(configs: dict[str, Any], route: str) -> str:
    routes = configs["route_availability.yaml"].get("routes") or {}
    entry = routes.get(route) or {}
    return str(entry.get("availability") or "unavailable")


def default_route_for_role(configs: dict[str, Any], semantic_role: str) -> str:
    roles = configs["content_blocks.yaml"].get("semantic_roles") or {}
    entry = roles.get(semantic_role) or roles.get("unknown") or {}
    return str(entry.get("default_route") or "review_only")


def eligible_for_question_bank(configs: dict[str, Any], semantic_role: str) -> bool:
    roles = configs["content_blocks.yaml"].get("semantic_roles") or {}
    value = (roles.get(semantic_role) or {}).get("eligible_for_question_bank", False)
    return value is True


def threshold_version(configs: dict[str, Any]) -> str:
    return str(configs["thresholds.yaml"].get("threshold_version") or "uncalibrated_v0.2")
