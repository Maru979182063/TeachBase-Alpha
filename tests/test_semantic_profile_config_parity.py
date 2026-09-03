from __future__ import annotations

import json
from pathlib import Path

import pytest

from teachbase.semantic_role import evaluator
from teachbase.semantic_role import profile_config as package_config
from tools import semantic_profile_config as legacy_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config" / "semantic_profiles"


def test_package_and_legacy_load_real_versioned_config_with_identical_result() -> None:
    package_loaded = package_config.load_semantic_profile_configs(CONFIG_DIR)
    legacy_loaded = legacy_config.load_semantic_profile_configs(CONFIG_DIR)
    evaluator_loaded = evaluator.load_semantic_profile_configs(ROOT)

    assert package_loaded == legacy_loaded == evaluator_loaded


def test_package_and_legacy_helpers_match_for_real_config_values() -> None:
    configs = package_config.load_semantic_profile_configs(CONFIG_DIR)

    assert package_config.semantic_enums(configs) == legacy_config.semantic_enums(configs)
    assert package_config.threshold_version(configs) == legacy_config.threshold_version(configs)

    for route in ["question_bank", "review_only", "missing_route"]:
        assert package_config.route_availability(configs, route) == legacy_config.route_availability(configs, route)

    for role in ["question", "answer_block", "unknown", "missing_role"]:
        assert package_config.default_route_for_role(configs, role) == legacy_config.default_route_for_role(configs, role)
        assert package_config.eligible_for_question_bank(configs, role) == legacy_config.eligible_for_question_bank(configs, role)


def test_legacy_default_loader_still_points_to_repo_config() -> None:
    assert legacy_config.load_semantic_profile_configs() == package_config.load_semantic_profile_configs(CONFIG_DIR)


def test_legacy_and_evaluator_keep_json_error_compatibility(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "semantic_profiles"
    config_dir.mkdir(parents=True)
    (config_dir / "common.yaml").write_text("{", encoding="utf-8")

    with pytest.raises(legacy_config.SemanticProfileConfigError):
        legacy_config.load_semantic_profile_configs(config_dir)

    with pytest.raises(json.JSONDecodeError):
        evaluator.load_semantic_profile_configs(tmp_path)
