from __future__ import annotations


from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from src.log_messages import error as error_messages
from src.models.portfolio.validation import currency_code
from src.models.portfolio.validation import decimal_value
from src.models.portfolio.validation import observation_date


@dataclass(frozen=True)
class ExchangeRateObservation:
    currency: str
    rate: Decimal
    as_of: date

    def __post_init__(self):
        currency_code(self.currency)
        decimal_value(self.rate, "FX rate")
        observation_date(self.as_of.isoformat())
        if self.rate <= 0 or (self.currency == "INR" and self.rate != 1):
            raise ValueError(error_messages.INVALID_FX_RATE)

    @classmethod
    def parse(cls, currency: str, rate: str, as_of: date) -> "ExchangeRateObservation":
        return cls(currency, decimal_value(rate, "FX rate"), as_of)
