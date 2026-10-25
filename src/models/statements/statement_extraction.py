from __future__ import annotations


from dataclasses import dataclass
from src.log_messages import error as error_messages
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import account_number
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_institution import StatementInstitution


@dataclass(frozen=True)
class StatementExtraction:
    """Currency pockets grouped by their independently identified account numbers."""

    accounts: tuple[StatementAccount, ...]
    institution: StatementInstitution | None = None

    def __post_init__(self):
        if not 1 <= len(self.accounts) <= 30:
            raise ValueError(error_messages.STATEMENT_ACCOUNT_COUNT)
        if not all(isinstance(account, StatementAccount) for account in self.accounts):
            raise ValueError(error_messages.STATEMENT_ACCOUNTS_MUST_BE_VALIDATED_ACCOUNT_OBJECTS)
        numbers = [account_number(item.number) for item in self.accounts]
        if len(numbers) != len(set(numbers)):
            raise ValueError(error_messages.STATEMENT_OUTPUT_CONTAINS_A_REPEATED_ACCOUNT_NUMBER)
        if sum(len(item.balances) for item in self.accounts) > 30:
            raise ValueError(error_messages.A_STATEMENT_MUST_CONTAIN_AT_MOST_30_CURRENCY_BALANCES)

    @property
    def balances(self) -> tuple[StatementBalance, ...]:
        return tuple(balance for account in self.accounts for balance in account.balances)

    @property
    def account_number(self) -> str | None:
        return self.accounts[0].number if len(self.accounts) == 1 else None

    def to_snapshots(
            self, institution: str, alias: str | dict[str, str], kind: str,
    ) -> list[BalanceSnapshot]:
        aliases = self._account_aliases(alias)
        return [
            snapshot for item in self.accounts
            for snapshot in item.to_snapshots(
                institution, aliases[account_number(item.number)], kind,
            )
        ]

    def _account_aliases(self, alias: str | dict[str, str]) -> dict[str, str]:
        aliases = (
            {account_number(item.number): alias for item in self.accounts}
            if isinstance(alias, str) else
            {account_number(key): value for key, value in alias.items()}
        )
        missing = {
                      account_number(item.number) for item in self.accounts
                  } - aliases.keys()
        if missing:
            raise ValueError(error_messages.AN_ACCOUNT_ALIAS_IS_REQUIRED_FOR_EVERY_STATEMENT_ACCOUNT)
        return aliases

    def to_snapshots_for_account(
            self, number: str, institution: str, alias: str, kind: str,
    ) -> list[BalanceSnapshot]:
        normalized_number = account_number(number)
        account = next(
            (item for item in self.accounts if account_number(item.number) == normalized_number),
            None,
        )
        if account is None:
            raise ValueError(error_messages.STATEMENT_ACCOUNT_WAS_NOT_FOUND_IN_THE_EXTRACTION)
        return account.to_snapshots(institution, alias, kind)
