from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class LoadedModel:
    processor: Any
    model: Any
    torch: Any
    generation_lock: Lock
