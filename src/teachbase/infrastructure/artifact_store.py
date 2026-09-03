from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


_REPLACE_LOCK = threading.Lock()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def write_text(path: Path, content: str) -> None:
    _atomic_write_text(path, content)


def _atomic_write_text(path: Path, content: str, *, replace: Callable[[Path, Path], None] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_fn = replace or os.replace
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_path = Path(temp_file.name)
        # Windows 上防病毒或索引器可能短暂占用目标文件；进程内串行替换并保留有限重试。
        with _REPLACE_LOCK:
            _replace_with_transient_retry(temp_path, path, replace=replace_fn)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _replace_with_transient_retry(
    source: Path,
    target: Path,
    *,
    replace: Callable[[Path, Path], None],
    attempts: int = 20,
    delay_seconds: float = 0.01,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            replace(source, target)
            return
        except PermissionError:
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds)
