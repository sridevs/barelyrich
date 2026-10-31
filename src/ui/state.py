import hashlib
from typing import cast

from src.log_messages import error as error_messages
from src.models.entry.statement_review import StatementReview
from src.models.portfolio.validation import account_number
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.transaction_draft import TransactionDraft
from src.ui.session_scope import SessionScope


class StatementReviewSession(SessionScope):
    """Session-scoped review lifecycle, independent of Streamlit and storage."""

    @property
    def upload_revision(self) -> int:
        return cast(int, self._get("statement_upload_revision", 0))

    @property
    def preview(self) -> StatementReview | None:
        review = cast(StatementReview | None, self._get("statement_preview"))
        if review is not None and type(review) is not StatementReview:
            review = StatementReview.restore(review)
            self._set("statement_preview", review)
        return review

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
        if self.editing_account:
            raise ValueError(error_messages.STATEMENT_EDIT_PENDING)
        review = self.preview
        if review is None:
            return None
        for account in review.extraction.accounts:
            value = cast(str, self._state.get(
                self.account_type_key(review, account.number), account.account_type,
            ))
            review = review.with_account_type(account.number, value)
        return review

    @property
    def editing_account(self) -> str | None:
        return cast(str | None, self._get("statement_editing_account"))

    def begin_edit(self, number: str) -> None:
        if self.is_account_saved(number):
            raise ValueError(error_messages.STATEMENT_EDIT_SAVED)
        self._set("statement_editing_account", account_number(number))

    def cancel_edit(self) -> None:
        editing_account = self.editing_account
        if editing_account:
            self._state.pop(self.editor_key(editing_account) + "_data", None)
            self._state.pop(self.editor_key(editing_account) + "_error", None)
        self._drop("statement_editing_account", "statement_editor_draft")
        self._set("statement_edit_revision", cast(int, self._get("statement_edit_revision", 0)) + 1)

    def editor_key(self, number: str) -> str:
        revision = self._get("statement_edit_revision", 0)
        return self._key(f"statement_editor_{account_number(number)}_{revision}")

    @property
    def editor_draft(self) -> tuple[TransactionDraft, ...] | None:
        return cast(
            tuple[TransactionDraft, ...] | None,
            self._get("statement_editor_draft"),
        )

    def reorder_draft(self, number: str, rows: tuple[TransactionDraft, ...]) -> None:
        if self.editing_account != account_number(number) or self.is_account_saved(number):
            raise ValueError(error_messages.STATEMENT_EDIT_NOT_STARTED)
        self.cancel_edit()
        self.begin_edit(number)
        self._set("statement_editor_draft", rows)

    def apply_balances(self, number: str, balances: tuple[StatementBalance, ...]) -> None:
        if self.preview is None or self.editing_account != account_number(number):
            raise ValueError(error_messages.STATEMENT_EDIT_NOT_STARTED)
        self._set("statement_preview", self.preview.with_account_balances(number, balances))
        self.cancel_edit()

    def is_account_saved(self, number: str) -> bool:
        saved = cast(frozenset[str], self._get("statement_saved_accounts", frozenset()))
        return account_number(number) in saved

    def mark_account_saved(self, number: str) -> None:
        saved = set(cast(
            frozenset[str],
            self._get("statement_saved_accounts", frozenset()),
        ))
        saved.add(account_number(number))
        self._set("statement_saved_accounts", frozenset(saved))

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
        self._set("statement_preview", review)

    def clear(self) -> None:
        self.cancel_edit()
        self._drop("statement_preview", "statement_saved_accounts")
        self._drop_prefixed("statement_confirmation_")

    def finish(self) -> None:
        self.clear()
        self._set("statement_upload_revision", self.upload_revision + 1)
