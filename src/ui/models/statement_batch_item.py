from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatementBatchItem:
    name: str
    error: str = ""
    saved: bool = False
