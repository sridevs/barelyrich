from __future__ import annotations


from datetime import date
from src.log_messages import error as error_messages


def required_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise ValueError(error_messages.REQUIRED_FIELD.format(label=label))
    return value.strip()


def required_date(value: object, label: str) -> date:
    if type(value) is not date:
        raise ValueError(error_messages.DATE_SELECTION_REQUIRED.format(label=label))
    return value
