from __future__ import annotations

from dataclasses import dataclass, replace

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
        if not 1 <= len(self.balances) <= 10000:
            raise ValueError(error_messages.STATEMENT_TRANSACTION_LIMIT)
        if not all(isinstance(balance, StatementBalance) for balance in self.balances):
            raise ValueError(error_messages.STATEMENT_BALANCES_MUST_BE_VALIDATED_BALANCE_OBJECTS)

    @property
    def has_conflicting_summaries(self) -> bool:
        summaries = [(row.currency, row.as_of) for row in self.balances if not row.is_transaction]
        return len(summaries) != len(set(summaries))

    def with_balances(self, balances: tuple[StatementBalance, ...]) -> "StatementAccount":
        # Session rows can outlive their class definitions during Streamlit hot reloads.
        validated = tuple(
            StatementBalance(
                row.balance, row.currency, row.as_of, row.withdrawal, row.deposit, row.description,
            )
            for row in balances
        )
        return StatementAccount(self.number, validated, self.account_type)

    def followed_by(self, later: StatementAccount) -> StatementAccount:
        """Append a later chunk's rows; drop the product type when the chunks disagree."""
        product = self.account_type if self.account_type == later.account_type else ""
        return replace(self, balances=self.balances + later.balances, account_type=product)

    def to_snapshots(self, institution: str, alias: str, kind: str) -> list[BalanceSnapshot]:
        if self.has_conflicting_summaries:
            raise DuplicateStatementCurrency(error_messages.RESOLVE_STATEMENT_SUMMARIES)
        if not alias.strip():
            raise ValueError(error_messages.ACCOUNT_ALIAS_IS_REQUIRED)
        occurrences: dict[str, int] = {}
        ordered = sorted(self.balances, key=lambda balance: balance.as_of)
        return [self._snapshot(balance, institution, alias, kind, occurrences) for balance in ordered]

    def _snapshot(
        self, balance: StatementBalance, institution: str, alias: str, kind: str,
        occurrences: dict[str, int],
    ) -> BalanceSnapshot:
        identity = balance.transaction_key()
        occurrences[identity] = occurrences.get(identity, 0) + 1
        order_key = f"{balance.currency}:{balance.as_of}"
        occurrences[order_key] = occurrences.get(order_key, 0) + int(balance.is_transaction)
        return replace(
            balance.to_snapshot(institution, f"{alias} {balance.currency}", kind),
            account_number=account_number(self.number),
            product_type=account_product_type(self.account_type),
            transaction_key=balance.transaction_key(occurrences[identity]),
            row_number=occurrences[order_key] if balance.is_transaction else 0,
        )
