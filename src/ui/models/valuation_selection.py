from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ValuationSelection:
    currency: str
    as_of: date
