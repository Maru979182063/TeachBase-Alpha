from __future__ import annotations

from pathlib import Path

import pytest

from teachbase.infrastructure.artifact_store import read_json, write_json
from teachbase.infrastructure.model_call_guard import (
    ModelRetryPolicy,
    is_retryable_model_error,
    run_model_call_with_retry,
)


def test_model_call_without_checkpoint_returns_result() -> None:
    calls = 0

    def operation() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": "ok"}

    result = run_model_call_with_retry(operation, operation_id="case-1")

    assert result == {"status": "ok"}
    assert calls == 1


def test_model_call_retries_transient_error_then_persists_success(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoints" / "case-2.json"
    calls = 0
    sleeps: list[float] = []

    def operation() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("model timed out")
        return {"status": "ok", "call": calls}

    result = run_model_call_with_retry(
        operation,
        operation_id="case-2",
        checkpoint_path=checkpoint_path,
        policy=ModelRetryPolicy(max_attempts=3, initial_delay_seconds=0.25),
        sleep=sleeps.append,
        metadata={"node": "unit-test"},
    )

    checkpoint = read_json(checkpoint_path)
    assert result == {"status": "ok", "call": 2}
    assert calls == 2
    assert sleeps == [0.25]
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["result"] == result
    assert [attempt["status"] for attempt in checkpoint["attempts"]] == ["failed", "succeeded"]
    assert checkpoint["attempts"][0]["retryable"] is True
    assert checkpoint["metadata"] == {"node": "unit-test"}


def test_success_checkpoint_short_circuits_operation(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "case-3.json"
    expected = {"status": "cached", "raw_content": "{}"}
    write_json(
        checkpoint_path,
        {
            "schema_version": "teachbase.model_call_checkpoint.v1",
            "operation_id": "case-3",
            "status": "succeeded",
            "result": expected,
            "attempts": [],
        },
    )

    def operation() -> object:
        raise AssertionError("operation should not be called when success checkpoint exists")

    assert run_model_call_with_retry(operation, operation_id="case-3", checkpoint_path=checkpoint_path) == expected


def test_non_retryable_error_is_persisted_and_raised(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "case-4.json"
    calls = 0

    def operation() -> object:
        nonlocal calls
        calls += 1
        raise ValueError("schema is invalid")

    with pytest.raises(ValueError, match="schema is invalid"):
        run_model_call_with_retry(
            operation,
            operation_id="case-4",
            checkpoint_path=checkpoint_path,
            policy=ModelRetryPolicy(max_attempts=3, initial_delay_seconds=0),
            sleep=lambda _: None,
        )

    checkpoint = read_json(checkpoint_path)
    assert calls == 1
    assert checkpoint["status"] == "failed"
    assert len(checkpoint["attempts"]) == 1
    assert checkpoint["attempts"][0]["retryable"] is False


def test_retry_exhaustion_raises_last_error_and_marks_failed(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "case-5.json"
    sleeps: list[float] = []

    def operation() -> object:
        raise ConnectionError("remote end closed connection without response")

    with pytest.raises(ConnectionError, match="remote end closed"):
        run_model_call_with_retry(
            operation,
            operation_id="case-5",
            checkpoint_path=checkpoint_path,
            policy=ModelRetryPolicy(max_attempts=3, initial_delay_seconds=0.1, backoff_multiplier=3),
            sleep=sleeps.append,
        )

    checkpoint = read_json(checkpoint_path)
    assert sleeps == [0.1, 0.30000000000000004]
    assert checkpoint["status"] == "failed"
    assert len(checkpoint["attempts"]) == 3
    assert all(attempt["retryable"] is True for attempt in checkpoint["attempts"])


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        ConnectionError("connection reset"),
        OSError("EOF occurred in violation of protocol"),
        ValueError("empty_model_response"),
    ],
)
def test_default_retryable_model_error_markers(exc: BaseException) -> None:
    assert is_retryable_model_error(exc) is True
