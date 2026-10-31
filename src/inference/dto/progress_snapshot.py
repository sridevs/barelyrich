"""Immutable snapshot of request-local inference progress."""

from dataclasses import dataclass

from src.inference.generation_progress import GenerationProgress


@dataclass(frozen=True)
class ProgressSnapshot:
    stage: str
    stage_started_at: float
    timings: tuple[tuple[str, float], ...] = ()
    generation: GenerationProgress | None = None
