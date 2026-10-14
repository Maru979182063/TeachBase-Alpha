from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FewShotExample(StrictModel):
    example_id: str = Field(min_length=1)
    input: dict[str, Any]
    output: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)


class PromptBundle(StrictModel):
    prompt_schema: Literal["difficulty_prompt_bundle_v1"] = Field(alias="schema")
    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["draft", "trial", "active", "deprecated"]
    system_prompt: str = Field(min_length=1)
    few_shots: list[FewShotExample] = Field(default_factory=list, max_length=20)

    def few_shot_pairs(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(item.input, item.output) for item in self.few_shots]

    def model_messages(self, user_payload: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        for example in self.few_shots:
            messages.extend(
                [
                    {
                        "role": "user",
                        "content": json.dumps(example.input, ensure_ascii=False, separators=(",", ":")),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(example.output, ensure_ascii=False, separators=(",", ":")),
                    },
                ]
            )
        messages.append(
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
            }
        )
        return messages


@dataclass(frozen=True)
class LoadedPromptBundle:
    path: Path
    sha256: str
    value: PromptBundle


def load_prompt_bundle(path: Path) -> LoadedPromptBundle:
    payload_bytes = path.read_bytes()
    raw = yaml.safe_load(payload_bytes.decode("utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError(f"提示词包必须为 YAML 对象：{path}")
    return LoadedPromptBundle(
        path=path.resolve(),
        sha256=hashlib.sha256(payload_bytes).hexdigest(),
        value=PromptBundle.model_validate(raw),
    )
