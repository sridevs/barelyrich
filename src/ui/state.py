from collections.abc import Callable, MutableMapping
import hashlib
from typing import cast

from src.models.entry.statement_review import StatementReview
from src.models.portfolio.validation import account_number
from src.models.statements.statement_extraction import StatementExtraction


class StatementReviewSession:
    """Session-scoped review lifecycle, independent of Streamlit and storage."""

    def __init__(self, state: MutableMapping[str, object], key: Callable[[str], str] = str):
        self._state = state
        self._key = key

    @property
    def upload_revision(self) -> int:
        return cast(int, self._state.get(self._key("statement_upload_revision"), 0))

    @property
    def preview(self) -> StatementReview | None:
        return cast(StatementReview | None, self._state.get(self._key("statement_preview")))

    def alias_key(self, review: StatementReview) -> str:
        return self._key(f"statement_alias_{self.upload_revision}_{review.file_digest}")

    def account_alias_key(self, review: StatementReview, number: str) -> str:
        if len(review.extraction.accounts) == 1:
            return self.alias_key(review)
        normalized_number = account_number(number)
        account_digest = hashlib.sha256(normalized_number.encode("utf-8")).hexdigest()[:12]
        return self._key(
            f"statement_alias_{self.upload_revision}_{review.file_digest}_{account_digest}"
        )

    def account_type_key(self, review: StatementReview, number: str) -> str:
        return self.account_alias_key(review, number) + "_type"

    def update_suggested_alias(
        self, review: StatementReview, number: str, account_type: str,
    ) -> None:
        alias_key = self.account_alias_key(review, number)
        suggestion_key = alias_key + "_suggestion"
        previous = self._state.get(
            suggestion_key, review.suggested_aliases[account_number(number)],
        )
        suggested = review.suggest_account_alias(number, account_type)
        if self._state.get(alias_key, previous) == previous:
            self._state[alias_key] = suggested
        self._state[suggestion_key] = suggested

    @property
    def reviewed_preview(self) -> StatementReview | None:
        review = self.preview
        if review is None:
            return None
        for account in review.extraction.accounts:
            value = cast(str, self._state.get(
                self.account_type_key(review, account.number), account.account_type,
            ))
            review = review.with_account_type(account.number, value)
        return review

    def is_account_saved(self, number: str) -> bool:
        saved = cast(frozenset[str], self._state.get(self._key("statement_saved_accounts"), frozenset()))
        return account_number(number) in saved

    def mark_account_saved(self, number: str) -> None:
        saved = set(cast(
            frozenset[str],
            self._state.get(self._key("statement_saved_accounts"), frozenset()),
        ))
        saved.add(account_number(number))
        self._state[self._key("statement_saved_accounts")] = frozenset(saved)

    def widget_key(self, name: str) -> str:
        return self._key(name)

    def pending_aliases(self, review: StatementReview) -> dict[str, str]:
        return {
            number: cast(str, self._state.get(self.account_alias_key(review, number), suggested))
            for number, suggested in review.suggested_aliases.items()
            if not self.is_account_saved(number)
        }

    def start(self, content: bytes, kind: str, extraction: StatementExtraction) -> None:
        review = StatementReview.create(content, kind, extraction)
        for number, alias in review.suggested_aliases.items():
            self._state[self.account_alias_key(review, number)] = alias
            self._state[self.account_alias_key(review, number) + "_suggestion"] = alias
        for account in extraction.accounts:
            self._state[self.account_type_key(review, account.number)] = account.account_type
        self._state[self._key("statement_preview")] = review

    def clear(self) -> None:
        self._state.pop(self._key("statement_preview"), None)
        self._state.pop(self._key("statement_saved_accounts"), None)
        confirmation_prefix = self._key("statement_confirmation_")
        for state_key in list(self._state):
            if state_key.startswith(confirmation_prefix):
                self._state.pop(state_key, None)

    def finish(self) -> None:
        self.clear()
        self._state[self._key("statement_upload_revision")] = self.upload_revision + 1
