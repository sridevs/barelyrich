"""Cooperative cancellation shared by the UI and request-local model work."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Lock


class ExtractionCancelled(Exception):
    """The user stopped extraction; partial results must not be used."""


class Cancellation:
    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._interrupt: Callable[[], None] | None = None

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            interrupt = self._interrupt
        if interrupt:
            interrupt()

    def check(self) -> None:
        if self._event.is_set():
            raise ExtractionCancelled("Extraction stopped. No partial output was saved.")

    @contextmanager
    def interrupt_with(self, interrupt: Callable[[], None]) -> Iterator[None]:
        with self._lock:
            self._interrupt = interrupt
        try:
            self.check()
            yield
        finally:
            with self._lock:
                self._interrupt = None
