from __future__ import annotations

from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = THIS_DIR.parent
DEFAULT_CONFIG_PATH = WORKSPACE_ROOT / "config" / "docx_native_ingest_v01.yaml"


def parse_scalar(value: str) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw[0:1] in {"'", '"'} and raw[-1:] == raw[0]:
        return raw[1:-1]
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def load_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        stripped = line_without_comment.strip()
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if raw_value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)
    return root


def resolve_config_path(raw_path: str | Path | None = None) -> Path:
    if raw_path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = WORKSPACE_ROOT / path
        return path
    return DEFAULT_CONFIG_PATH


def load_config(raw_path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    path = resolve_config_path(raw_path)
    return load_simple_yaml(path), path


def nested_get(config: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    cursor: Any = config
    for part in dotted_path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def workspace_path(raw_path: str | Path) -> Path:
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return path
    return WORKSPACE_ROOT / path
