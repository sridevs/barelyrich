"""Immutable timings and counters for one model generation."""

import logging
from dataclasses import dataclass, replace
from time import perf_counter

from src.log_messages import info

LOGGER = logging.getLogger(__name__)
LIVE_OUTPUT_CHARACTERS = 16_000


@dataclass(frozen=True)
class GenerationProgress:
    started_at: float
    input_tokens: int | None
    generated_tokens: int | None = 0
    first_token_seconds: float | None = None
    elapsed_seconds: float = 0
    text: str = ""
    finished: bool = False
    eos: bool = False
    generated_characters: int = 0
    first_chunk_characters: int = 0

    @property
    def characters_per_second(self) -> float:
        if self.first_token_seconds is None:
            return 0
        decoding_seconds = self.elapsed_seconds - self.first_token_seconds
        characters = max(0, self.generated_characters - self.first_chunk_characters)
        return characters / decoding_seconds if decoding_seconds > 0 else 0

    @property
    def tokens_per_second(self) -> float:
        if self.first_token_seconds is None or self.generated_tokens is None:
            return 0
        decoding_seconds = self.elapsed_seconds - self.first_token_seconds
        return max(0, self.generated_tokens - 1) / decoding_seconds if decoding_seconds > 0 else 0

    def with_chunk(self, text: str) -> "GenerationProgress":
        elapsed = perf_counter() - self.started_at
        is_first = bool(text) and self.first_token_seconds is None
        return replace(
            self, elapsed_seconds=elapsed,
            first_token_seconds=elapsed if is_first else self.first_token_seconds,
            generated_characters=self.generated_characters + len(text),
            first_chunk_characters=len(text) if is_first else self.first_chunk_characters,
            text=(self.text + text)[-LIVE_OUTPUT_CHARACTERS:],
        )

    def finish(self, *, eos: bool | None = None) -> "GenerationProgress":
        finished = replace(
            self, finished=True, eos=self.eos if eos is None else eos,
            elapsed_seconds=perf_counter() - self.started_at,
        )
        LOGGER.info(
            info.GENERATION_DIAGNOSTICS, finished.input_tokens, finished.generated_tokens,
            finished.elapsed_seconds,
            None if finished.first_token_seconds is None else round(finished.first_token_seconds, 2),
            finished.tokens_per_second, finished.eos,
        )
        return finished
