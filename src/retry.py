"""Bounded retries for synchronous operations with caller-defined transient errors."""


import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import ParamSpec, TypeVar

from src.log_messages import error as error_messages
from src.log_messages import warning

LOGGER = logging.getLogger(__name__)
Parameters = ParamSpec("Parameters")
Result = TypeVar("Result")


@dataclass(frozen=True)
class _RetryPolicy:
    _exceptions: tuple[type[Exception], ...]
    _should_retry: Callable[[Exception], bool]
    _attempts: int
    _delay_seconds: float

    def __post_init__(self) -> None:
        if self._attempts < 1 or self._delay_seconds < 0:
            raise ValueError(error_messages.INVALID_RETRY_POLICY)

    def decorate(self, operation: Callable[Parameters, Result]) -> Callable[Parameters, Result]:
        @wraps(operation)
        def wrapped(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
            for attempt in range(1, self._attempts + 1):
                try:
                    return operation(*args, **kwargs)
                except self._exceptions as error:
                    if attempt == self._attempts or not self._should_retry(error):
                        raise
                    self._wait(operation.__qualname__, error, attempt)
            raise AssertionError(error_messages.RETRY_ATTEMPTS_EXHAUSTED_WITHOUT_A_RESULT_OR_EXCEPTION)

        return wrapped

    def _wait(self, operation_name: str, error: Exception, attempt: int) -> None:
        delay = self._delay_seconds * 2 ** (attempt - 1)
        LOGGER.warning(
            warning.OPERATION_RETRY,
            operation_name, type(error).__name__, attempt + 1, self._attempts, delay,
        )
        time.sleep(delay)


def retry(
    exceptions: tuple[type[Exception], ...],
    *,
    should_retry: Callable[[Exception], bool],
    attempts: int = 3,
    delay_seconds: float = 1,
) -> Callable[[Callable[Parameters, Result]], Callable[Parameters, Result]]:
    """Retry selected failures with exponential backoff; re-raise the final error."""
    return _RetryPolicy(exceptions, should_retry, attempts, delay_seconds).decorate
