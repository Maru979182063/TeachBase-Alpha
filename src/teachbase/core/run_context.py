from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id(prefix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in prefix).strip("_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe or 'pipeline'}_{stamp}_{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    pipeline_id: str
    pipeline_version: str
    workspace_root: Path
    input_root: Path
    output_root: Path
    started_at: str = field(default_factory=utc_now_iso)
    feature_flags: dict[str, bool] = field(default_factory=dict)
    model_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
