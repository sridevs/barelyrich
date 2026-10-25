from __future__ import annotations

from dataclasses import dataclass
from src.models.portfolio.validation import institution_name


@dataclass(frozen=True)
class StatementInstitution:
    name: str

    def __post_init__(self):
        institution_name(self.name)

    @property
    def alias(self) -> str:
        # Leave room for the currency suffix within the 100-character account alias.
        return institution_name(self.name).split()[0][:96]
