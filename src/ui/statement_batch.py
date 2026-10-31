"""Session-scoped navigation and outcomes for independently reviewed statements."""

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

from src.log_messages import error as error_messages
from src.models.entry.statement_review import StatementReview
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.ui.dto.statement_batch_item import StatementBatchItem
from src.ui.session_scope import SessionScope
from src.ui.state import StatementReviewSession


class StatementBatchSession(SessionScope):
    @property
    def items(self) -> tuple[StatementBatchItem, ...]:
        return cast(tuple[StatementBatchItem, ...], self._get("statement_batch", ()))

    @property
    def index(self) -> int:
        return cast(int, self._get("statement_batch_index", 0))

    def matches(self, files: Sequence[tuple[str, bytes]], kind: str) -> bool:
        return self._get("statement_batch_signature") == self._signature(files, kind)

    def begin(self, files: Sequence[tuple[str, bytes]], kind: str) -> None:
        self.clear()
        self._set("statement_batch_signature", self._signature(files, kind))
        self._set("statement_batch", tuple(StatementBatchItem(name) for name, _ in files))

    def review_session(self, index: int) -> StatementReviewSession:
        revision = StatementReviewSession(self._state, self._key).upload_revision
        prefix = f"statement_batch_{revision}_{index}_"
        return StatementReviewSession(self._state, lambda name: self._key(prefix + name))

    def move(self, offset: int) -> None:
        self._set("statement_batch_index", max(0, min(len(self.items) - 1, self.index + offset)))

    def fail(self, index: int, error: str) -> None:
        self._replace(index, replace(self.items[index], error=error))

    def cancel_extraction(self, message: str) -> None:
        for index, item in enumerate(self.items):
            if not item.saved and not item.error and self.review_session(index).preview is None:
                self._replace(index, replace(
                    item, error=message, password_required=False, password_error="",
                ))

    def require_password(self, index: int) -> None:
        self._replace(index, replace(self.items[index], password_required=True))

    def password_failed(self, index: int, error: str) -> None:
        self._replace(
            index,
            replace(self.items[index], password_required=True, password_error=error),
        )

    def password_succeeded(self, index: int) -> None:
        self._replace(
            index,
            replace(
                self.items[index], error="", password_required=False, password_error="",
            ),
        )

    def mark_saved(self) -> None:
        self._replace(self.index, replace(self.items[self.index], saved=True))

    def mark_account_saved(self, number: str) -> None:
        session = self.review_session(self.index)
        review = session.preview
        if review is None:
            raise ValueError(error_messages.MISSING_STATEMENT_PREVIEW)
        session.mark_account_saved(number)
        if all(session.is_account_saved(item.number) for item in review.extraction.accounts):
            self.mark_saved()

    def institution_key(self, index: int, review: StatementReview) -> str:
        session = self.review_session(index)
        return session.widget_key(
            f"statement_institution_{session.upload_revision}_{review.file_digest}",
        )

    def pending_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index, item in enumerate(self.items) if not item.saved and not item.error
        )

    def pending_snapshots(self) -> list[BalanceSnapshot]:
        return [
            snapshot for index in self.pending_indices()
            for snapshot in self._statement_snapshots(index)
        ]

    def _statement_snapshots(self, index: int) -> list[BalanceSnapshot]:
        session = self.review_session(index)
        review = session.reviewed_preview
        if review is None:
            raise ValueError(error_messages.MISSING_STATEMENT_PREVIEW)
        institution = cast(str, self._state.get(self.institution_key(index, review), review.institution))
        return [
            snapshot
            for number, alias in session.pending_aliases(review).items()
            for snapshot in review.snapshots_for_account(number, alias, institution)
        ]

    def confirmation_key(self, snapshots: list[BalanceSnapshot]) -> str:
        signature = repr((self._get("statement_batch_signature"), snapshots))
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        return self._key(f"statement_batch_confirmation_{digest}")

    def mark_pending_saved(self) -> None:
        for index in self.pending_indices():
            self._replace(index, replace(self.items[index], saved=True))

    def finish(self) -> None:
        self.clear()
        StatementReviewSession(self._state, self._key).finish()

    def clear(self) -> None:
        for index in range(len(self.items)):
            self.review_session(index).clear()
        self._drop_prefixed("statement_batch", "statement_password")

    def _replace(self, index: int, item: StatementBatchItem) -> None:
        items = list(self.items)
        items[index] = item
        self._set("statement_batch", tuple(items))

    @staticmethod
    def _signature(
            files: Sequence[tuple[str, bytes]], kind: str,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        return kind, tuple((name, hashlib.sha256(content).hexdigest()) for name, content in files)
