from __future__ import annotations


from dataclasses import dataclass, replace
import hashlib
import re
from src.log_messages import error as error_messages
from src.models.entry.validation import required_text
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.validation import account_number
from src.models.statements.statement_extraction import StatementExtraction


def _require_file_digest(value: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError(error_messages.A_STATEMENT_REVIEW_MUST_IDENTIFY_ITS_UPLOADED_FILE)


@dataclass(frozen=True)
class StatementReview:
    """Bind an extraction to the exact upload and balance kind being reviewed."""

    file_digest: str
    kind: str
    extraction: StatementExtraction

    def __post_init__(self):
        _require_file_digest(self.file_digest)
        self.snapshots(self.suggested_aliases)

    @classmethod
    def create(cls, content: bytes, kind: str, extraction: StatementExtraction) -> "StatementReview":
        return cls(hashlib.sha256(content).hexdigest(), kind, extraction)

    @property
    def institution(self) -> str:
        identity = self.extraction.institution
        if identity is None:
            raise ValueError(error_messages.AI_COULD_NOT_IDENTIFY_THE_STATEMENT_INSTITUTION)
        return identity.name

    @property
    def suggested_alias(self) -> str:
        identity = self.extraction.institution
        if identity is None:
            raise ValueError(error_messages.AI_COULD_NOT_IDENTIFY_THE_STATEMENT_INSTITUTION)
        return identity.alias

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
        normalized = account_number(number)
        if normalized not in self.suggested_aliases:
            raise ValueError(error_messages.STATEMENT_ACCOUNT_WAS_NOT_FOUND_IN_THE_EXTRACTION)
        return replace(self, extraction=replace(
            self.extraction,
            accounts=tuple(
                replace(item, account_type=value) if account_number(item.number) == normalized
                else item
                for item in self.extraction.accounts
            ),
        ))

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
        name = self.institution if institution is None else institution
        if isinstance(alias, dict):
            return [
                snapshot
                for number, value in alias.items()
                for snapshot in self.snapshots_for_account(number, value, name)
            ]
        return self.extraction.to_snapshots(
            name,
            required_text(alias, "Statement account alias"),
            self.kind,
        )

    def snapshots_for_account(
            self, number: str, alias: str, institution: str | None = None,
    ) -> list[BalanceSnapshot]:
        return self.extraction.to_snapshots_for_account(
            number,
            self.institution if institution is None else institution,
            required_text(alias, "Statement account alias"),
            self.kind,
        )
