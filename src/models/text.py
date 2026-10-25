"""Shared text-presence predicates independent of application layers."""


def is_missing_text(value: object) -> bool:
    """Recognize absent or blank text without treating other falsy values as missing."""
    return value is None or (isinstance(value, str) and not value.strip())
