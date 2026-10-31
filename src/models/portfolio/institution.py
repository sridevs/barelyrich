from __future__ import annotations

from dataclasses import dataclass

from src.log_messages import error as error_messages
from src.models.portfolio.validation import country_code, institution_name


@dataclass(frozen=True)
class Institution:
    key: str
    name: str
    country: str = ""
    account_type: str = "other"

    def __post_init__(self):
        # Case folding can expand a 100-character name into a longer identity key.
        institution_name(self.key, max_length=300)
        institution_name(self.name)
        country_code(self.country)
        if self.account_type not in {"bank", "brokerage", "other"}:
            raise ValueError(error_messages.INSTITUTION_ACCOUNT_TYPE_MUST_BE_BANK_BROKERAGE_OR_OTHER)

    @property
    def normalized_name(self) -> str:
        return institution_name(self.name).casefold()

    @classmethod
    def from_name(cls, name: str) -> "Institution":
        name = institution_name(name)
        return cls(name.casefold(), name)
