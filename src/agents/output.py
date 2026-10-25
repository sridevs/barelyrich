"""Strict AI wire models, independent of inference and persistence."""

from __future__ import annotations


from decimal import Decimal
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from src.log_messages import error as error_messages
from src.log_messages import info
from src.models.currencies import ISO_CURRENCY_CODES, iso_currency_code
from src.models.portfolio.validation import observation_date
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_institution import StatementInstitution
from src.models.text import is_missing_text


LOGGER = logging.getLogger(__name__)


class OutputModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def require_nonblank_text(cls, value: object, validation_info: ValidationInfo) -> object:
        field_name = validation_info.field_name
        if (
            isinstance(value, str) and is_missing_text(value)
            and field_name
            and cls.model_fields[field_name].is_required()
        ):
            raise ValueError(error_messages.MISSING_REQUIRED_FIELDS)
        return value


class InstitutionOutput(OutputModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]

    def to_domain(self) -> StatementInstitution:
        return StatementInstitution(self.name)


class AccountOutput(OutputModel):
    number: Annotated[str, Field(min_length=1, max_length=100)]
    account_type: Annotated[str, Field(max_length=100)] | None = None
    balances: Annotated[list["BalanceOutput"], Field(min_length=1, max_length=30)]

    def to_domain(self) -> StatementAccount:
        balances = {}
        for balance in self.balances:
            converted = balance.to_domain()
            balances.setdefault(balance.financial_identity(), converted)
        return StatementAccount(self.number, tuple(balances.values()), self.account_type or "")


class BalanceOutput(OutputModel):
    balance: Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]{1,8})?$")]
    currency: Annotated[str, Field(
        pattern=r"^[A-Z]{3}$", json_schema_extra={"enum": list(ISO_CURRENCY_CODES)},
    )]
    as_of: str
    balance_role: Literal[
        "closing_balance", "current_balance", "opening_balance", "transaction_amount",
        "available_balance", "credit_limit", "interest", "converted_equivalent", "other",
    ]
    account_scope: Literal["single_account", "aggregate", "unknown"]
    date_role: Literal[
        "statement_date", "period_end", "balance_date", "period_start",
        "transaction_date", "other",
    ]

    @field_validator("currency")
    @classmethod
    def require_iso_currency(cls, value: str) -> str:
        return iso_currency_code(value)

    def to_domain(self) -> StatementBalance:
        return StatementBalance(
            Decimal(self.balance), self.currency, observation_date(self.as_of),
            self.balance_role, self.account_scope, self.date_role,
        )

    def financial_identity(self) -> tuple[Decimal, str, str, str, str, str]:
        return (
            Decimal(self.balance), self.currency, self.as_of,
            self.balance_role, self.account_scope, self.date_role,
        )


AccountOutput.model_rebuild()


class StatementOutput(OutputModel):
    institution: InstitutionOutput
    accounts: Annotated[list[AccountOutput], Field(min_length=1, max_length=30)]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_single_account(cls, value: object) -> object:
        if (
            isinstance(value, dict) and "accounts" not in value
            and isinstance(value.get("account"), dict)
        ):
            account = dict(value["account"])
            account["balances"] = value.get("balances")
            return {
                **{key: item for key, item in value.items() if key not in {"account", "balances"}},
                "accounts": [account],
            }
        return value

    def to_domain(self) -> StatementExtraction:
        accounts = tuple(account.to_domain() for account in self.accounts)
        total_rows = sum(len(account.balances) for account in self.accounts)
        total_unique = sum(len(account.balances) for account in accounts)
        if total_unique < total_rows:
            LOGGER.info(
                info.EQUIVALENT_BALANCES_COLLAPSED,
                total_rows, total_unique,
            )
        return StatementExtraction(accounts, self.institution.to_domain())
