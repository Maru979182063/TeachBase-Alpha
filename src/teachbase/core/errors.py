from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TeachBaseError(Exception):
    error_code: str
    message: str
    retryable: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


class ContractError(TeachBaseError):
    pass


class InputArtifactError(TeachBaseError):
    pass


class ConfigurationError(TeachBaseError):
    pass


class QualityGateError(TeachBaseError):
    pass
