from unittest.mock import Mock, call

import pytest

from src.retry import retry


def test_retry_preserves_arguments_metadata_and_returns_success(monkeypatch, caplog):
    sleep = Mock()
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    outcomes = Mock(side_effect=[TimeoutError("private details"), TimeoutError(), "success"])

    @retry((TimeoutError,), should_retry=lambda error: True)
    def operation(value: str, *, option: bool) -> str:
        """An operation."""
        return outcomes(value, option=option)

    assert operation("argument", option=True) == "success"
    assert outcomes.call_args_list == [call("argument", option=True)] * 3
    assert sleep.call_args_list == [call(1), call(2)]
    assert operation.__name__ == "operation"
    assert operation.__doc__ == "An operation."
    assert "private details" not in caplog.text
    assert "attempt 3/3" in caplog.text


@pytest.mark.parametrize("transient,attempts,count", [(True, 3, 3), (False, 3, 1), (True, 1, 1)])
def test_retry_re_raises_original_error_with_bounded_attempts(monkeypatch, transient, attempts, count):
    sleep = Mock()
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    error = TimeoutError("failure")
    operation = Mock(side_effect=error)
    operation.__qualname__ = "operation"
    wrapped = retry(
        (TimeoutError,), should_retry=lambda failure: transient, attempts=attempts,
    )(operation)
    with pytest.raises(TimeoutError) as caught:
        wrapped()
    assert caught.value is error
    assert operation.call_count == count
    assert sleep.call_count == count - 1


def test_retry_does_not_catch_unselected_errors():
    @retry((TimeoutError,), should_retry=lambda error: True)
    def operation():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        operation()


def test_reusing_decorated_operation_restarts_attempts_and_backoff(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("src.retry.time.sleep", sleep)
    operation = Mock(side_effect=[TimeoutError(), "first", TimeoutError(), "second"])
    operation.__qualname__ = "operation"
    wrapped = retry((TimeoutError,), should_retry=lambda error: True, attempts=2)(operation)
    assert wrapped() == "first"
    assert wrapped() == "second"
    assert operation.call_count == 4
    assert sleep.call_args_list == [call(1), call(1)]


@pytest.mark.parametrize("attempts,delay", [(0, 1), (-1, 1), (3, -1)])
def test_retry_rejects_invalid_policy(attempts, delay):
    with pytest.raises(ValueError, match="Retry attempts"):
        retry((TimeoutError,), should_retry=lambda error: True, attempts=attempts, delay_seconds=delay)
