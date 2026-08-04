from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import time
from typing import Any

from teachbase.core.errors import ConfigurationError
from teachbase.core.run_context import utc_now_iso
from teachbase.infrastructure.artifact_store import read_json, write_json

SCHEDULED_READY = "scheduled_ready"
SCHEDULED_BLOCKED = "scheduled_blocked"
REJECTED = "rejected"
DRY_RUN_STARTED = "dry_run_started"
DRY_RUN_PASSED = "dry_run_passed"
DRY_RUN_FAILED = "dry_run_failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({SCHEDULED_BLOCKED, REJECTED, DRY_RUN_PASSED, DRY_RUN_FAILED, CANCELLED})

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED_READY: (DRY_RUN_STARTED, CANCELLED),
    SCHEDULED_BLOCKED: (),
    REJECTED: (),
    DRY_RUN_STARTED: (DRY_RUN_PASSED, DRY_RUN_FAILED, CANCELLED),
    DRY_RUN_PASSED: (),
    DRY_RUN_FAILED: (),
    CANCELLED: (),
}


def build_job_lifecycle(status: str, *, created_at: str, reason: str = "scheduled") -> dict[str, Any]:
    _require_known_status(status)
    return {
        "schema_version": "final_chain_job_lifecycle.v0.1",
        "status": status,
        "state_version": 1,
        "terminal": status in TERMINAL_STATUSES,
        "allowed_next_statuses": list(ALLOWED_TRANSITIONS[status]),
        "updated_at": created_at,
        "history": [
            {
                "version": 1,
                "status": status,
                "at": created_at,
                "reason": reason,
                "checkpoint": None,
            }
        ],
    }


def inspect_job_record(record: dict[str, Any]) -> dict[str, Any]:
    status = str(record.get("status") or "")
    _require_known_status(status)
    lifecycle = record.get("lifecycle")
    lifecycle_status = lifecycle.get("status") if isinstance(lifecycle, dict) else ""
    return {
        "schema_version": "final_chain_job_inspection.v0.1",
        "job_id": _redact_absolute_path_evidence(str(record.get("job_id") or "")),
        "chain_id": _redact_absolute_path_evidence(str(record.get("chain_id") or "")),
        "status": _redact_absolute_path_evidence(status),
        "lifecycle_status": lifecycle_status,
        "status_consistent": lifecycle_status in {"", status},
        "terminal": status in TERMINAL_STATUSES,
        "allowed_next_statuses": list(ALLOWED_TRANSITIONS[status]),
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def validate_job_record(record: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    def add_error(code: str, **extra: Any) -> None:
        errors.append({"code": code, **{key: _redact_absolute_path_evidence(value) for key, value in extra.items()}})

    status = str(record.get("status") or "")
    if record.get("schema_version") != "final_chain_job_record.v0.1":
        add_error("schema_version_mismatch", value=record.get("schema_version"))
    if status not in ALLOWED_TRANSITIONS:
        add_error("unknown_status", value=status)

    for key in ("plan", "request_snapshot", "environment_snapshot", "lifecycle", "execution_contract"):
        if not isinstance(record.get(key), dict):
            add_error("missing_required_section", section=key)

    execution_contract = record.get("execution_contract")
    if execution_contract != _no_side_effect_contract():
        add_error("execution_contract_not_no_side_effects", value=execution_contract)

    lifecycle = record.get("lifecycle")
    if isinstance(lifecycle, dict) and status in ALLOWED_TRANSITIONS:
        expected_next = list(ALLOWED_TRANSITIONS[status])
        history = lifecycle.get("history")
        latest = history[-1] if isinstance(history, list) and history else {}
        if lifecycle.get("schema_version") != "final_chain_job_lifecycle.v0.1":
            add_error("lifecycle_schema_version_mismatch", value=lifecycle.get("schema_version"))
        if lifecycle.get("status") != status:
            add_error("lifecycle_status_mismatch", status=status, lifecycle_status=lifecycle.get("status"))
        if lifecycle.get("terminal") is not (status in TERMINAL_STATUSES):
            add_error("lifecycle_terminal_mismatch", value=lifecycle.get("terminal"))
        if lifecycle.get("allowed_next_statuses") != expected_next:
            add_error("lifecycle_allowed_next_statuses_mismatch", value=lifecycle.get("allowed_next_statuses"))
        if not isinstance(history, list) or not history:
            add_error("lifecycle_history_missing")
        elif latest.get("status") != status:
            add_error("lifecycle_latest_history_status_mismatch", value=latest.get("status"))

    request_snapshot = record.get("request_snapshot")
    if isinstance(request_snapshot, dict):
        if request_snapshot.get("workspace_contract") != "relative_git_paths_only":
            add_error("request_snapshot_workspace_contract_mismatch")
        if request_snapshot.get("absolute_paths_as_inputs") is not False:
            add_error("request_snapshot_allows_absolute_paths")

    plan = record.get("plan")
    if isinstance(plan, dict):
        if plan.get("workspace_contract") != "relative_git_paths_only":
            add_error("plan_workspace_contract_mismatch")
        if plan.get("absolute_paths_as_inputs") is not False:
            add_error("plan_allows_absolute_paths")

    record_path = str(record.get("record_path") or "")
    if record_path and _looks_absolute_path(record_path):
        add_error("record_path_not_portable")

    leak_paths = sorted(set(_find_absolute_path_strings(record)))
    if leak_paths:
        add_error("absolute_path_leak", count=len(leak_paths))

    return {
        "schema_version": "final_chain_job_validation.v0.1",
        "ok": not errors,
        "job_id": _redact_absolute_path_evidence(str(record.get("job_id") or "")),
        "chain_id": _redact_absolute_path_evidence(str(record.get("chain_id") or "")),
        "status": _redact_absolute_path_evidence(status),
        "error_count": len(errors),
        "errors": errors,
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def attach_job_record_validation(record: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(record)
    updated.pop("record_validation", None)
    validation = validate_job_record(updated)
    updated["record_validation"] = {
        "schema_version": validation["schema_version"],
        "ok": validation["ok"],
        "error_count": validation["error_count"],
    }
    return updated


def transition_job_record(
    record: dict[str, Any],
    target_status: str,
    *,
    reason: str,
    checkpoint: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    expected_status: str | None = None,
    expected_state_version: int | None = None,
) -> dict[str, Any]:
    _require_known_status(target_status)
    current_status = str(record.get("status") or "")
    _require_known_status(current_status)
    if expected_status is not None:
        _require_known_status(expected_status)
        if current_status != expected_status:
            raise ConfigurationError(
                "final_chain_job_stale_transition",
                f"Expected final-chain job status {expected_status}, found {current_status}",
                evidence={"expected_status": expected_status, "actual_status": current_status},
            )
    current_state_version = _record_state_version(record)
    if expected_state_version is not None and current_state_version != expected_state_version:
        raise ConfigurationError(
            "final_chain_job_stale_transition",
            f"Expected final-chain job state version {expected_state_version}, found {current_state_version}",
            evidence={"expected_state_version": expected_state_version, "actual_state_version": current_state_version},
        )
    allowed = ALLOWED_TRANSITIONS[current_status]
    if target_status not in allowed:
        raise ConfigurationError(
            "final_chain_job_invalid_transition",
            f"Cannot transition final-chain job from {current_status} to {target_status}",
        )

    now = utc_now_iso()
    updated = deepcopy(record)
    lifecycle = updated.get("lifecycle")
    if not isinstance(lifecycle, dict):
        lifecycle = build_job_lifecycle(current_status, created_at=str(updated.get("created_at") or now))
    history = lifecycle.get("history")
    if not isinstance(history, list):
        history = []
    version = int(lifecycle.get("state_version") or len(history) or 1) + 1
    event = {
        "version": version,
        "status": target_status,
        "at": now,
        "reason": reason,
        "checkpoint": _portable_checkpoint(checkpoint, workspace_root=workspace_root),
    }
    history.append(event)
    lifecycle.update(
        {
            "status": target_status,
            "state_version": version,
            "terminal": target_status in TERMINAL_STATUSES,
            "allowed_next_statuses": list(ALLOWED_TRANSITIONS[target_status]),
            "updated_at": now,
            "history": history,
        }
    )
    updated["status"] = target_status
    updated["updated_at"] = now
    updated["lifecycle"] = lifecycle
    updated["execution_contract"] = {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }
    return attach_job_record_validation(updated)


def load_job_record(path: Path) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except FileNotFoundError as exc:
        raise ConfigurationError("final_chain_job_record_missing", "Job record does not exist") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("final_chain_job_record_not_object", "Job record is not an object")
    return payload


def inspect_job_record_path(path: Path) -> dict[str, Any]:
    return inspect_job_record(load_job_record(path))


def validate_job_record_path(path: Path) -> dict[str, Any]:
    return validate_job_record(load_job_record(path))


def transition_job_record_path(
    path: Path,
    target_status: str,
    *,
    reason: str,
    checkpoint: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    expected_status: str | None = None,
    expected_state_version: int | None = None,
    lock_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    with _job_record_lock(path, timeout_seconds=lock_timeout_seconds):
        updated = transition_job_record(
            load_job_record(path),
            target_status,
            reason=reason,
            checkpoint=checkpoint,
            workspace_root=workspace_root,
            expected_status=expected_status,
            expected_state_version=expected_state_version,
        )
        write_json(path, updated)
        return updated


class _JobRecordLock:
    def __init__(self, record_path: Path, *, timeout_seconds: float, delay_seconds: float = 0.01) -> None:
        self._lock_dir = record_path.with_name(f".{record_path.name}.lock")
        self._timeout_seconds = timeout_seconds
        self._delay_seconds = delay_seconds
        self._acquired = False

    def __enter__(self) -> "_JobRecordLock":
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                self._lock_dir.mkdir()
                self._acquired = True
                return self
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise ConfigurationError(
                        "final_chain_job_transition_lock_timeout",
                        "Timed out waiting for final-chain job transition lock",
                        evidence={"lock_name": self._lock_dir.name},
                    ) from exc
                time.sleep(self._delay_seconds)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._acquired:
            try:
                self._lock_dir.rmdir()
            except FileNotFoundError:
                pass


def _job_record_lock(path: Path, *, timeout_seconds: float) -> _JobRecordLock:
    if timeout_seconds < 0:
        raise ValueError("lock_timeout_seconds must be >= 0")
    path.parent.mkdir(parents=True, exist_ok=True)
    return _JobRecordLock(path, timeout_seconds=timeout_seconds)


def _require_known_status(status: str) -> None:
    if status not in ALLOWED_TRANSITIONS:
        raise ConfigurationError("final_chain_job_unknown_status", f"Unknown final-chain job status: {status}")


def _record_state_version(record: dict[str, Any]) -> int:
    lifecycle = record.get("lifecycle")
    if isinstance(lifecycle, dict):
        try:
            return int(lifecycle.get("state_version") or 1)
        except (TypeError, ValueError):
            return 1
    return 1


def _no_side_effect_contract() -> dict[str, bool]:
    return {
        "model_invoked": False,
        "database_written": False,
        "runtime_imported": False,
        "business_secrets_read": False,
    }


def _find_absolute_path_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for item in value.values():
            found.extend(_find_absolute_path_strings(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_find_absolute_path_strings(item))
        return found
    if isinstance(value, str) and _looks_absolute_path(value):
        return [value]
    return []


def _redact_absolute_path_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_absolute_path_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_absolute_path_evidence(item) for item in value]
    if isinstance(value, str) and _looks_absolute_path(value):
        return "<absolute-path>"
    return value


def _looks_absolute_path(value: str) -> bool:
    return bool(
        Path(value).is_absolute()
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or value.startswith("/Users/")
        or value.startswith("/home/")
        or value.startswith("/tmp/")
    )


def _portable_checkpoint(checkpoint: dict[str, Any] | None, *, workspace_root: Path | None = None) -> dict[str, Any] | None:
    if checkpoint is None:
        return None
    portable: dict[str, Any] = {}
    for key, value in checkpoint.items():
        if isinstance(value, Path):
            portable[key] = _portable_path(value, workspace_root=workspace_root)
        elif isinstance(value, str) and Path(value).is_absolute():
            portable[key] = _portable_path(Path(value), workspace_root=workspace_root)
        else:
            portable[key] = value
    return portable


def _portable_path(path: Path, *, workspace_root: Path | None = None) -> str:
    if workspace_root is None:
        return path.as_posix()
    try:
        resolved = path.resolve()
        root = workspace_root.resolve()
        if resolved == root or root in resolved.parents:
            return resolved.relative_to(root).as_posix()
    except OSError:
        pass
    return "<outside-workspace>"
