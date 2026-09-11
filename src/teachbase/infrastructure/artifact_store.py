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
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if _matches_existing_json_text(path, content):
        # 受版本控制的 manifest 可能带 LF/CRLF 或末尾换行；内容未变时保留原始字节，
        # 避免只因运行平台不同就把安全门禁误报为业务配置变更。
        return
    _atomic_write_text(path, content)


def write_text(path: Path, content: str) -> None:
    _atomic_write_text(path, content)


def _matches_existing_json_text(path: Path, content: str) -> bool:
    if not path.is_file():
        return False
    try:
        existing = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except (OSError, UnicodeError):
        return False
    return existing == content or existing == f"{content}\n"


def _atomic_write_text(path: Path, content: str, *, replace: Callable[[Path, Path], None] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_fn = replace or os.replace
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
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
