"""Schema-validated structured calls: validate with Pydantic, retry once with the error,
then give up (callers fall back to the rule system). SPEC §8.4–8.5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from polymech_ai.providers import Provider, RawCompletion


class AIValidationError(Exception):
    """The provider's answer failed schema validation twice."""


@dataclass(frozen=True)
class AIResult[T]:
    value: T
    provider: str
    model: str
    elapsed_s: float
    attempts: int
    usage: dict[str, Any]


def run_structured[M: BaseModel](
    provider: Provider, prompt: str, schema: dict[str, Any], model: type[M], timeout_s: float = 180
) -> AIResult[M]:
    total = 0.0
    last_error = ""
    raw: RawCompletion | None = None
    for attempt in (1, 2):
        p = (
            prompt
            if attempt == 1
            else (
                f"{prompt}\n\n上一次的输出没有通过 JSON Schema 校验，错误为：{last_error[:800]}\n请严格按 Schema 重新输出。"
            )
        )
        raw = provider.complete(p, schema, timeout_s)
        total += raw.elapsed_s
        try:
            value = model.model_validate(raw.data)
            return AIResult(value, raw.provider, raw.model, total, attempt, raw.usage)
        except ValidationError as e:
            last_error = str(e)
    raise AIValidationError(f"AI 输出两次未通过校验：{last_error[:300]}")


def strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    """Object schema accepted by both OpenAI strict mode and Claude: every property required,
    no additional properties (nullable fields use ["type","null"])."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
