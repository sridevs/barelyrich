"""Request-local inference diagnostics, independent of the UI and model cache."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from threading import Lock
from time import perf_counter
from typing import Iterator

from src.inference.cancellation import Cancellation
from src.inference.dto.progress_snapshot import ProgressSnapshot
from src.inference.generation_progress import GenerationProgress


class InferenceProgress:
    def __init__(self) -> None:
        self._cancellation = Cancellation()
        self._lock = Lock()
        self._snapshot = ProgressSnapshot("Preparing extraction", perf_counter())

    @property
    def cancellation(self) -> Cancellation:
        return self._cancellation

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            return self._snapshot

    def stage(self, label: str) -> None:
        now = perf_counter()
        with self._lock:
            previous = self._snapshot
            self._snapshot = replace(
                previous, stage=label, stage_started_at=now,
                timings=previous.timings + ((previous.stage, now - previous.stage_started_at),),
            )

    def generation(self, update: GenerationProgress) -> None:
        with self._lock:
            self._snapshot = replace(self._snapshot, generation=update)


_CURRENT: ContextVar[InferenceProgress | None] = ContextVar("inference_progress", default=None)


@contextmanager
def observe(progress: InferenceProgress) -> Iterator[None]:
    token = _CURRENT.set(progress)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_progress() -> InferenceProgress | None:
    return _CURRENT.get()


def report_stage(label: str) -> None:
    progress = current_progress()
    if progress:
        progress.cancellation.check()
        progress.stage(label)
