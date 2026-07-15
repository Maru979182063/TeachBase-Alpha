from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from teachbase.infrastructure import artifact_store


def temp_files_for(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_write_json_single_write_contract_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    payload = {"alpha": "中文", "items": [1, 2, 3]}

    artifact_store.write_json(path, payload)

    assert path.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, indent=2)
    assert artifact_store.read_json(path) == payload
    assert temp_files_for(path) == []


def test_concurrent_writes_leave_complete_json_and_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    payloads = [{"writer": idx, "values": list(range(idx, idx + 5))} for idx in range(32)]
    errors: list[BaseException] = []

    def write_payload(payload: dict) -> None:
        try:
            artifact_store.write_json(path, payload)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write_payload, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert artifact_store.read_json(path) in payloads
    assert temp_files_for(path) == []


def test_write_text_uses_same_atomic_cleanup_contract(tmp_path: Path) -> None:
    path = tmp_path / "artifact.txt"

    artifact_store.write_text(path, "hello\nworld")

    assert path.read_text(encoding="utf-8") == "hello\nworld"
    assert temp_files_for(path) == []


def test_replace_failure_removes_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "artifact.json"

    def fail_replace(src: Path, dst: Path) -> None:
        raise PermissionError(f"replace blocked: {src} -> {dst}")

    monkeypatch.setattr(artifact_store.os, "replace", fail_replace)

    with pytest.raises(PermissionError):
        artifact_store.write_json(path, {"blocked": True})

    assert not path.exists()
    assert temp_files_for(path) == []
