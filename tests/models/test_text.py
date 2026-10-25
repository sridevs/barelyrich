import pytest

from src.models.text import is_missing_text


@pytest.mark.parametrize("value", [None, "", " ", "\t\n", "\u2003"])
def test_missing_text(value):
    assert is_missing_text(value)


@pytest.mark.parametrize("value", ["0", " text ", 0, False, [], {}, b""])
def test_present_text_and_non_text_values_are_not_missing_text(value):
    assert not is_missing_text(value)
