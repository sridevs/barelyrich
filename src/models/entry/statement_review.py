from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from src.log_messages import error as error_messages
from src.models.entry.validation import required_text
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import account_number
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution


def _require_file_digest(value: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(error_messages.A_STATEMENT_REVIEW_MUST_IDENTIFY_ITS_UPLOADED_FILE)


@dataclass(frozen=True)
class StatementReview:
    """Bind an extraction to the exact upload and balance kind being reviewed."""

    file_digest: str
    kind: str
    extraction: StatementExtraction

    @classmethod
    def restore(cls, review: "StatementReview") -> "StatementReview":
        extraction = StatementExtraction(
            tuple(StatementAccount.with_balances(item, item.balances) for item in review.extraction.accounts),
            review.extraction.institution,
        )
        return cls(review.file_digest, review.kind, extraction)

    def __post_init__(self):
        _require_file_digest(self.file_digest)
        aliases = self.suggested_aliases
        for account in self.extraction.accounts:
            for row in account.balances:
                row.to_snapshot(self.institution, aliases[account_number(account.number)], self.kind)

    @classmethod
    def create(cls, content: bytes, kind: str, extraction: StatementExtraction) -> "StatementReview":
        return cls(hashlib.sha256(content).hexdigest(), kind, extraction)

    @property
    def _identity(self) -> StatementInstitution:
        if self.extraction.institution is None:
            raise ValueError(error_messages.AI_COULD_NOT_IDENTIFY_THE_STATEMENT_INSTITUTION)
        return self.extraction.institution

    @property
    def institution(self) -> str:
        return self._identity.name

    def _institution_named(self, institution: str | None) -> str:
        return self.institution if institution is None else institution

    @property
    def suggested_alias(self) -> str:
        return self._identity.alias

    @property
    def suggested_aliases(self) -> dict[str, str]:
        return {
            account_number(item.number): self.suggest_account_alias(item.number, item.account_type)
            for item in self.extraction.accounts
        }

    def suggest_account_alias(self, number: str, account_type: str) -> str:
        normalized = account_number(number)
        index = next(
            index for index, item in enumerate(self.extraction.accounts, start=1)
            if account_number(item.number) == normalized
        )
        label = " ".join(account_type.split())
        suffix = f" {index}" if label or len(self.extraction.accounts) > 1 else ""
        base = f"{self.suggested_alias} {label}".strip()
        return base[:96 - len(suffix)].rstrip() + suffix

    def matches(self, content: bytes, kind: str) -> bool:
        return self.file_digest == hashlib.sha256(content).hexdigest() and self.kind == kind

    def with_account_type(self, number: str, value: str) -> "StatementReview":
        return self._with_account(number, lambda account: replace(account, account_type=value))

    def with_account_balances(
        self, number: str, balances: tuple[StatementBalance, ...],
    ) -> "StatementReview":
        return self._with_account(number, lambda account: account.with_balances(balances))

    def _with_account(
        self, number: str, change: Callable[[StatementAccount], StatementAccount],
    ) -> "StatementReview":
        normalized = account_number(number)
        if normalized not in self.suggested_aliases:
            raise ValueError(error_messages.STATEMENT_ACCOUNT_WAS_NOT_FOUND_IN_THE_EXTRACTION)
        accounts = tuple(
            change(item) if account_number(item.number) == normalized else item
            for item in self.extraction.accounts
        )
        return replace(self, extraction=replace(self.extraction, accounts=accounts))

    def confirmation_key(
            self, alias: str | dict[str, str], institution: str | None = None,
    ) -> str:
        aliases = tuple(sorted(alias.items())) if isinstance(alias, dict) else alias.strip()
        signature = repr((
            self.file_digest, self.institution if institution is None else institution,
            aliases, self.kind, self.extraction,
        ))
        confirmation_digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        return f"statement_confirmation_{confirmation_digest}"

    def snapshots(
            self, alias: str | dict[str, str], institution: str | None = None,
    ) -> list[BalanceSnapshot]:
        if isinstance(alias, dict):
            return [
                snapshot for number, value in alias.items()
                for snapshot in self.snapshots_for_account(number, value, institution)
            ]
        return self.extraction.to_snapshots(self._institution_named(institution), _account_name(alias), self.kind)

    def snapshots_for_account(
            self, number: str, alias: str, institution: str | None = None,
    ) -> list[BalanceSnapshot]:
        return self.extraction.to_snapshots_for_account(
            number, self._institution_named(institution), _account_name(alias), self.kind,
        )


def _account_name(alias: str) -> str:
    return required_text(alias, "Statement account name")
