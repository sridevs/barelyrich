"""Strict AI wire models, independent of inference and persistence."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from src.log_messages import error as error_messages
from src.log_messages import info, warning
from src.models.currencies import ISO_CURRENCY_CODES, iso_currency_code
from src.models.portfolio.validation import account_number, observation_date
from src.models.statements.errors import DuplicateStatementCurrency
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
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
            and field_name != "description"
            and cls.model_fields[field_name].is_required()
        ):
            raise ValueError(error_messages.MISSING_REQUIRED_FIELDS)
        return value


class InstitutionOutput(OutputModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]

    def to_domain(self) -> StatementInstitution:
        return StatementInstitution(self.name)


class AccountOutput(OutputModel):
    _conflicting_type: bool = PrivateAttr(default=False)
    number: Annotated[str, Field(min_length=1, max_length=100)]
    account_type: Annotated[str, Field(max_length=100)] | None = None
    balances: Annotated[list["BalanceOutput"], Field(min_length=1, max_length=10000)]

    def merge_currency_section(self, section: "AccountOutput") -> "AccountOutput":
        if account_number(self.number) != account_number(section.number):
            raise ValueError(error_messages.STATEMENT_OUTPUT_CONTAINS_A_REPEATED_ACCOUNT_NUMBER)
        account_type, conflicting = self._merged_product_type(section)
        if conflicting:
            LOGGER.warning(warning.CONFLICTING_STATEMENT_ACCOUNT_TYPES)
        merged = AccountOutput(
            number=self.number, account_type=account_type,
            balances=[*self.balances, *section.balances],
        )
        merged._conflicting_type = conflicting
        return merged

    def _merged_product_type(self, section: "AccountOutput") -> tuple[str | None, bool]:
        product = self._product_label()
        other_product = section._product_label()
        conflicting = self._conflicting_type or section._conflicting_type
        conflicting |= bool(product and other_product and product != other_product)
        if conflicting:
            return None, True
        account_type = self.account_type if product else section.account_type if other_product else None
        return account_type, False

    def _product_label(self) -> str:
        label = " ".join((self.account_type or "").replace("_", " ").casefold().split())
        currency_labels = {row.currency.casefold() for row in self.balances}
        return "" if label in currency_labels | {"currency breakdown"} else label

    def to_domain(self) -> StatementAccount:
        balances = {}
        for index, balance in enumerate(self.balances):
            try:
                converted = balance.to_domain()
            except ValueError as failure:
                message = error_messages.STATEMENT_BALANCE_FIELD_INVALID.format(
                    index=index, failure=failure,
                )
                raise ValueError(message) from failure
            identity = (balance.financial_identity(), index if converted.is_transaction else None)
            balances.setdefault(identity, converted)
        return StatementAccount(self.number, tuple(balances.values()), self.account_type or "")


class BalanceOutput(OutputModel):
    COLUMNS: ClassVar[tuple[str, ...]] = (
        "as_of", "balance", "currency", "withdrawal", "deposit", "description",
    )
    balance: Annotated[str, Field(pattern=r"^-?[0-9]+(?:\.[0-9]{1,8})?$")]
    currency: Annotated[str, Field(
        pattern=r"^[A-Z]{3}$", json_schema_extra={"enum": list(ISO_CURRENCY_CODES)},
    )]
    as_of: str
    withdrawal: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,8})?$")] | None
    deposit: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,8})?$")] | None
    description: Annotated[str, Field(max_length=2000)]

    @model_validator(mode="after")
    def require_transaction_movement(self) -> "BalanceOutput":
        if self.withdrawal is None and self.deposit is None:
            raise ValueError(error_messages.STATEMENT_TRANSACTION_MOVEMENT_REQUIRED)
        return self

    @model_validator(mode="before")
    @classmethod
    def unpack_row(cls, value: object) -> object:
        if isinstance(value, list):
            if len(value) > len(cls.COLUMNS):
                raise ValueError(error_messages.INVALID_POSITIONAL_ROW)
            return dict(zip(cls.COLUMNS[:len(value)], value, strict=True))
        return value

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: CoreSchema, handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        named = handler(schema)
        row_schema = _positional_row_schema(cls.COLUMNS, cls.__name__, named)
        return {**row_schema, "anyOf": _movement_schema_alternatives(row_schema)}

    def to_wire_row(self) -> list[str | None]:
        return [self.as_of, self.balance, self.currency,
                self.withdrawal, self.deposit, self.description]

    @field_validator("currency")
    @classmethod
    def require_iso_currency(cls, value: str) -> str:
        return iso_currency_code(value)

    def to_domain(self) -> StatementBalance:
        return StatementBalance(
            Decimal(self.balance), self.currency, observation_date(self.as_of),
            None if self.withdrawal is None else Decimal(self.withdrawal),
            None if self.deposit is None else Decimal(self.deposit),
            self.description,
        )

    def financial_identity(self) -> tuple:
        return (
            Decimal(self.balance), self.currency, self.as_of,
            None if self.withdrawal is None else Decimal(self.withdrawal),
            None if self.deposit is None else Decimal(self.deposit), self.description,
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
        grouped = self._grouped_accounts()
        accounts = self._validated_accounts(grouped)
        _log_collapsed_rows(self.accounts, accounts)
        return StatementExtraction(tuple(accounts), self.institution.to_domain())

    def _grouped_accounts(self) -> dict[str, AccountOutput]:
        grouped: dict[str, AccountOutput] = {}
        for account in self.accounts:
            number = account_number(account.number)
            grouped[number] = (
                grouped[number].merge_currency_section(account) if number in grouped else account
            )
        if len(grouped) < len(self.accounts):
            LOGGER.info(info.CURRENCY_ACCOUNT_SECTIONS_MERGED, len(self.accounts), len(grouped))
        return grouped

    @staticmethod
    def _validated_accounts(grouped: dict[str, AccountOutput]) -> list[StatementAccount]:
        accounts = []
        for index, account in enumerate(grouped.values()):
            try:
                accounts.append(account.to_domain())
            except DuplicateStatementCurrency:
                raise
            except ValueError as failure:
                message = error_messages.MERGED_STATEMENT_ACCOUNT_INVALID.format(
                    index=index, failure=failure,
                )
                raise ValueError(message) from failure
        return accounts


def _positional_row_schema(columns: tuple[str, ...], title: str, named: dict) -> dict:
    return {
        "title": title, "type": "array",
        "prefixItems": [named["properties"][field] for field in columns],
        "minItems": len(columns), "maxItems": len(columns),
    }


def _movement_schema_alternatives(row_schema: dict) -> list[dict]:
    alternatives = []
    for position in (3, 4):
        items = list(row_schema["prefixItems"])
        items[position] = next(
            option for option in items[position]["anyOf"] if option.get("type") == "string"
        )
        alternatives.append({**row_schema, "prefixItems": items})
    return alternatives


def _log_collapsed_rows(
    source_accounts: list[AccountOutput], accounts: list[StatementAccount],
) -> None:
    total_rows = sum(len(account.balances) for account in source_accounts)
    total_unique = sum(len(account.balances) for account in accounts)
    if total_unique < total_rows:
        LOGGER.info(info.EQUIVALENT_BALANCES_COLLAPSED, total_rows, total_unique)
