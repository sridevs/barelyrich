"""Validated settings for local text and vision inference."""


import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.log_messages import error as error_messages
from src import config
from src.config import DEFAULT_TRANSFORMERS_MODEL


class TransformersRuntimeConfig(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", validate_default=True)

    model_name: str = Field(default=DEFAULT_TRANSFORMERS_MODEL, min_length=1, max_length=300)
    model_kind: Literal["vision", "text"] = "vision"
    device: Literal["auto", "cpu", "mps", "cuda"] = config.DEFAULT_TRANSFORMERS_DEVICE
    max_new_tokens: int = Field(default=config.DEFAULT_MAX_NEW_TOKENS, ge=1, le=32768)
    max_input_tokens: int = Field(default=config.DEFAULT_MAX_INPUT_TOKENS, ge=1, le=131072)
    max_image_pixels: int = Field(default=config.DEFAULT_MAX_IMAGE_PIXELS, ge=1, le=4_000_000)
    max_time_seconds: int = Field(default=config.DEFAULT_MAX_TIME_SECONDS, ge=1, le=180)

    @field_validator("model_name")
    @classmethod
    def require_model_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(error_messages.MODEL_NAME_MUST_NOT_BE_BLANK)
        return value

    @classmethod
    def from_environment(
        cls, *, model_name: str | None = None, model_kind: Literal["vision", "text"] = "vision",
    ) -> "TransformersRuntimeConfig":
        return cls(
            model_name=(
                os.environ.get(
                    "WT_TEXT_MODEL" if model_kind == "text" else "WT_TRANSFORMERS_MODEL",
                    config.DEFAULT_TEXT_MODEL if model_kind == "text" else DEFAULT_TRANSFORMERS_MODEL,
                )
                if model_name is None else model_name
            ),
            model_kind=model_kind,
            device=os.environ.get("WT_TRANSFORMERS_DEVICE", config.DEFAULT_TRANSFORMERS_DEVICE).lower(),
            max_new_tokens=int(os.environ.get(
                "WT_TRANSFORMERS_MAX_NEW_TOKENS", str(config.DEFAULT_MAX_NEW_TOKENS),
            )),
        )
