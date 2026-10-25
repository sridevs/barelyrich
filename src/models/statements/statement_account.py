from __future__ import annotations


from dataclasses import dataclass
from src.log_messages import error as error_messages
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import account_number, account_product_type
from src.models.statements.errors import DuplicateStatementCurrency
from src.models.statements.statement_balance import StatementBalance


@dataclass(frozen=True)
class StatementAccount:
    number: str
    balances: tuple[StatementBalance, ...]
    account_type: str = ""

    def __post_init__(self):
        account_number(self.number)
        account_product_type(self.account_type)
        if not 1 <= len(self.balances) <= 30:
            raise ValueError(error_messages.STATEMENT_ACCOUNT_BALANCE_COUNT)
        if not all(isinstance(balance, StatementBalance) for balance in self.balances):
            raise ValueError(error_messages.STATEMENT_BALANCES_MUST_BE_VALIDATED_BALANCE_OBJECTS)
        currencies = [balance.currency for balance in self.balances]
        if len(currencies) != len(set(currencies)):
            raise DuplicateStatementCurrency(
                error_messages.AMBIGUOUS_STATEMENT_CURRENCY
            )
        if len({balance.as_of for balance in self.balances}) != 1:
            raise ValueError(error_messages.INCONSISTENT_STATEMENT_ACCOUNT_DATE)

    def to_snapshots(self, institution: str, alias: str, kind: str) -> list[BalanceSnapshot]:
        if not alias.strip():
            raise ValueError(error_messages.ACCOUNT_ALIAS_IS_REQUIRED)
        number = account_number(self.number)
        return [
            BalanceSnapshot(
                institution, f"{alias} {balance.currency}", balance.currency, balance.balance,
                kind, balance.as_of, "statement", number,
                product_type=account_product_type(self.account_type),
            )
            for balance in self.balances
        ]
