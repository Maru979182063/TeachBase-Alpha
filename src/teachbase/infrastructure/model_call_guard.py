from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from teachbase.infrastructure.artifact_store import read_json, write_json
from teachbase.infrastructure.clock import utc_now_iso


ModelOperation = Callable[[], Any]
RetryPredicate = Callable[[BaseException], bool]
SleepFn = Callable[[float], None]

TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "eof",
    "remote end closed",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporarily unavailable",
    "try again",
    "rate limit",
    "empty_model_response",
    "429",
    "500",
    "502",
    "503",
    "504",
)


@dataclass(frozen=True)
class ModelRetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be >= 0")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be >= 0")


def is_retryable_model_error(exc: BaseException) -> bool:
    if bool(getattr(exc, "retryable", False)):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, BrokenPipeError)):
        return True
    if isinstance(exc, OSError):
        message = str(exc).lower()
        return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)
    message = str(exc).lower()
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def run_model_call_with_retry(
    operation: ModelOperation,
    *,
    operation_id: str,
    checkpoint_path: Path | None = None,
    policy: ModelRetryPolicy | None = None,
    is_retryable: RetryPredicate = is_retryable_model_error,
    sleep: SleepFn = time.sleep,
    metadata: dict[str, Any] | None = None,
) -> Any:
    active_policy = policy or ModelRetryPolicy()
    checkpoint = _read_success_checkpoint(checkpoint_path, operation_id)
    if checkpoint is not None:
        return checkpoint["result"]

    attempts: list[dict[str, Any]] = []
    delay = active_policy.initial_delay_seconds
    last_error: BaseException | None = None
    for attempt_index in range(1, active_policy.max_attempts + 1):
        started_at = utc_now_iso()
        try:
            result = operation()
        except Exception as exc:  # noqa: BLE001 - the guard records and re-raises caller exceptions.
            retryable = bool(is_retryable(exc))
            last_error = exc
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": utc_now_iso(),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "retryable": retryable,
                }
            )
            will_retry = retryable and attempt_index < active_policy.max_attempts
            _write_checkpoint(
                checkpoint_path,
                operation_id=operation_id,
                status="retrying" if will_retry else "failed",
                attempts=attempts,
                policy=active_policy,
                metadata=metadata,
            )
            if not will_retry:
                raise
            sleep(delay)
            delay = min(active_policy.max_delay_seconds, delay * active_policy.backoff_multiplier)
        else:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "succeeded",
                    "started_at": started_at,
                    "finished_at": utc_now_iso(),
                    "retryable": False,
                }
            )
            _write_checkpoint(
                checkpoint_path,
                operation_id=operation_id,
                status="succeeded",
                attempts=attempts,
                policy=active_policy,
                metadata=metadata,
                result=result,
            )
            return result

    if last_error is not None:
        raise last_error
    raise RuntimeError("model_call_guard_unreachable")


def _read_success_checkpoint(checkpoint_path: Path | None, operation_id: str) -> dict[str, Any] | None:
    if checkpoint_path is None or not checkpoint_path.exists():
        return None
    checkpoint = read_json(checkpoint_path)
    if not isinstance(checkpoint, dict):
        return None
    if checkpoint.get("schema_version") != "teachbase.model_call_checkpoint.v1":
        return None
    if checkpoint.get("operation_id") != operation_id:
        return None
    if checkpoint.get("status") != "succeeded":
        return None
    if "result" not in checkpoint:
        return None
    return checkpoint


def _write_checkpoint(
    checkpoint_path: Path | None,
    *,
    operation_id: str,
    status: str,
    attempts: list[dict[str, Any]],
    policy: ModelRetryPolicy,
    metadata: dict[str, Any] | None,
    result: Any = None,
) -> None:
    if checkpoint_path is None:
        return
    payload: dict[str, Any] = {
        "schema_version": "teachbase.model_call_checkpoint.v1",
        "operation_id": operation_id,
        "status": status,
        "updated_at": utc_now_iso(),
        "policy": {
            "max_attempts": policy.max_attempts,
            "initial_delay_seconds": policy.initial_delay_seconds,
            "backoff_multiplier": policy.backoff_multiplier,
            "max_delay_seconds": policy.max_delay_seconds,
        },
        "metadata": metadata or {},
        "attempts": attempts,
    }
    if status == "succeeded":
        payload["result"] = result
    write_json(checkpoint_path, payload)
