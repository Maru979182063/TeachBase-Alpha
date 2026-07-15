from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from teachbase.semantic_role.profile_config import (
    SemanticProfileConfigError,
    default_route_for_role,
    eligible_for_question_bank,
    load_semantic_profile_configs as _load_semantic_profile_configs,
    route_availability,
    semantic_enums,
    threshold_version,
)


CONFIG_DIR = ROOT / "config" / "semantic_profiles"


def load_semantic_profile_configs(config_dir: Path | None = None) -> dict:
    return _load_semantic_profile_configs(config_dir or CONFIG_DIR)
