from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_REPLACE_LOCK = threading.Lock()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _unique_temp_path(path: Path) -> Path:
    suffix = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    return path.with_name(f".{path.name}.{suffix}")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _unique_temp_path(path)
    try:
        temp_path.write_text(content, encoding="utf-8")
        with _REPLACE_LOCK:
            for attempt in range(10):
                try:
                    os.replace(temp_path, path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.01 * (attempt + 1))
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def write_text(path: Path, content: str) -> None:
    _atomic_write_text(path, content)
