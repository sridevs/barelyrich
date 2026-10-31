"""Validated settings for local Ollama inference."""

import os
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import config
from src.log_messages import error as error_messages


def _environment_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


class OllamaRuntimeConfig(BaseModel):
    """Ollama model tag, context window and generation limits."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", validate_default=True)

    model_name: str = Field(default=config.DEFAULT_OLLAMA_MODEL, min_length=1, max_length=300)
    context_tokens: int = Field(default=config.DEFAULT_OLLAMA_CONTEXT_TOKENS, ge=1, le=131072)
    max_new_tokens: int = Field(default=config.DEFAULT_MAX_NEW_TOKENS, ge=1, le=32768)
    max_time_seconds: int = Field(default=config.DEFAULT_MAX_TIME_SECONDS, ge=1)

    @field_validator("model_name")
    @classmethod
    def require_model_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(error_messages.MODEL_NAME_MUST_NOT_BE_BLANK)
        return value

    @classmethod
    def from_environment(cls, *, model_name: str | None = None) -> Self:
        return cls(
            model_name=model_name or os.environ.get("WT_OLLAMA_MODEL", config.DEFAULT_OLLAMA_MODEL),
            context_tokens=_environment_int("WT_OLLAMA_CONTEXT_TOKENS", config.DEFAULT_OLLAMA_CONTEXT_TOKENS),
            max_new_tokens=_environment_int("WT_OLLAMA_MAX_NEW_TOKENS", config.DEFAULT_MAX_NEW_TOKENS),
            max_time_seconds=_environment_int("WT_OLLAMA_MAX_TIME_SECONDS", config.DEFAULT_MAX_TIME_SECONDS),
        )
