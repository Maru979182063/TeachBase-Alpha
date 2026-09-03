from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from teachbase.infrastructure import artifact_store
from teachbase.infrastructure.artifact_store import write_json, write_text


def temp_files_for(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f".{path.name}.*.tmp"))


def test_write_json_preserves_existing_encoding_and_format(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "payload.json"
    payload = {"z": 1, "cn": "题目", "items": [{"a": True}]}

    result = write_json(target, payload)

    assert result is None
    assert target.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, indent=2)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert temp_files_for(target) == []


def test_write_text_preserves_existing_contract(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    content = "alpha\nbeta"

    result = write_text(target, content)

    assert result is None
    assert target.read_text(encoding="utf-8") == content
    assert temp_files_for(target) == []


def test_concurrent_json_writes_leave_complete_payload_and_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "shared.json"
    payloads = [
        {"writer": index, "body": f"value-{index}", "values": list(range(index, index + 5))}
        for index in range(40)
    ]

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda payload: write_json(target, payload), payloads))

    final_payload = json.loads(target.read_text(encoding="utf-8"))
    assert final_payload in payloads
    assert temp_files_for(target) == []


def test_replace_failure_cleans_temp_file_and_preserves_existing_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "payload.json"
    original = {"status": "old"}
    write_json(target, original)

    def fail_replace(src: Path, dst: Path) -> None:
        assert src.parent == target.parent
        assert src.name.startswith(f".{target.name}.")
        assert src.name.endswith(".tmp")
        assert dst == target
        raise OSError("simulated replace failure")

    monkeypatch.setattr(artifact_store.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_json(target, {"status": "new"})

    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert temp_files_for(target) == []
