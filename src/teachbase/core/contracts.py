from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StageStatus = Literal["READY", "REVIEW_REQUIRED", "BLOCKED", "FAILED"]


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str = ""
    kind: str = "file"


@dataclass(frozen=True)
class StageResult:
    status: StageStatus
    artifacts: list[ArtifactRef] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    retryable: bool = False
    review_required: bool = False
