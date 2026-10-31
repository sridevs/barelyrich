"""One statement-import request: uploads, options and the batch it drives."""

from dataclasses import dataclass
from functools import partial

import streamlit as st
from streamlit.typing import UploadedFile

from src.inference.cancellation import ExtractionCancelled
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.readers.statement_pdf import (
    IncorrectStatementPasswordError,
    StatementPasswordRequiredError,
)
from src.service.entry_services import EntryServices
from src.service.portfolio import PortfolioActions
from src.ui import ui_text
from src.ui.dto.statement_batch_item import StatementBatchItem
from src.ui.feedback import show_saved
from src.ui.inference_progress import preview_with_progress
from src.ui.statement_batch import StatementBatchSession
from src.ui.statement_review import render_statement_review


@dataclass(frozen=True)
class StatementImport:
    actions: PortfolioActions
    services: EntryServices
    kind: str
    uploads: list[UploadedFile]
    log_model_output: bool
    batch: StatementBatchSession

    def render(self, *, ready: bool) -> None:
        self._invalidate_if_changed()
        if ready and st.button(
            ui_text.EXTRACT_BALANCES, type="primary", disabled=not self.uploads, key="extract_statement",
        ):
            self._extract_all()
        if self.batch.items:
            _render_batch_navigation(self.batch)
            self._render_current()
            _render_batch_save(self.batch, self.actions)

    def _invalidate_if_changed(self) -> None:
        if self.batch.items and not self.batch.matches(self._files(), self.kind):
            self.batch.clear()
            st.warning(ui_text.BATCH_CHANGED)

    def _files(self) -> list[tuple[str, bytes]]:
        return [(upload.name, upload.getvalue()) for upload in self.uploads]

    def _extract_all(self) -> None:
        self.batch.begin(self._files(), self.kind)
        st.caption(ui_text.STATEMENT_PROCESSING_HELP)
        for index in range(len(self.uploads)):
            try:
                self._extract(index)
            except StatementPasswordRequiredError:
                self.batch.require_password(index)
            except ExtractionCancelled:
                self._cancel()
                break
            except ValueError as error:
                self.batch.fail(index, str(error))

    def _extract(self, index: int, password: str | None = None) -> None:
        upload = self.uploads[index]
        content = upload.getvalue()
        label = ui_text.parsing_statement(index + 1, len(self.batch.items), upload.name)
        options = {"log_model_output": self.log_model_output} | ({"password": password} if password else {})
        with st.spinner(label, show_time=True):
            extraction = preview_with_progress(
                lambda: self.services.preview(upload.name, content, **options),
                label,
                on_cancel=partial(self.batch.cancel_extraction, ui_text.EXTRACTION_CANCELLED),
            )
        self.batch.review_session(index).start(content, self.kind, extraction)

    def _cancel(self) -> None:
        self.batch.cancel_extraction(ui_text.EXTRACTION_CANCELLED)
        st.warning(ui_text.EXTRACTION_CANCELLED)

    def _render_current(self) -> None:
        item = self.batch.items[self.batch.index]
        if item.error:
            st.error(item.error)
        elif item.saved:
            st.info(ui_text.STATEMENT_SAVED)
        else:
            self._render_pending(item)

    def _render_pending(self, item: StatementBatchItem) -> None:
        if item.password_required:
            st.info(ui_text.ENTER_STATEMENT_PASSWORD)
            if item.password_error:
                st.error(item.password_error)
            self._render_password_form()
        session = self.batch.review_session(self.batch.index)
        if session.preview:
            render_statement_review(session.preview, self.actions, session, self.batch)

    def _render_password_form(self) -> None:
        index = self.batch.index
        password_key = f"statement_password_{index}_{self.batch.review_session(index).upload_revision}"
        password = st.session_state.pop(f"{password_key}_submitted", None)
        with st.form(f"statement_password_form_{index}"):
            st.text_input(
                ui_text.STATEMENT_PASSWORD, type="password", key=password_key,
                help=ui_text.STATEMENT_PASSWORD_HELP,
            )
            st.form_submit_button(
                ui_text.SUBMIT_STATEMENT_PASSWORD, type="primary",
                on_click=_submit_statement_password, args=(password_key,),
            )
        if password is not None:
            self._retry_with_password(index, password)

    def _retry_with_password(self, index: int, password: str) -> None:
        try:
            if not password:
                self.batch.password_failed(index, ui_text.ENTER_STATEMENT_PASSWORD)
                return
            st.caption(ui_text.STATEMENT_PROCESSING_HELP)
            self._extract(index, password)
            self.batch.password_succeeded(index)
        except ExtractionCancelled:
            self._cancel()
        except IncorrectStatementPasswordError as error:
            self.batch.password_failed(index, str(error))
            st.error(str(error))
        except ValueError as error:
            self.batch.fail(index, str(error))
            st.error(str(error))


def _submit_statement_password(password_key: str) -> None:
    # Clear the widget in its callback; run inference after the panel has rendered.
    st.session_state[f"{password_key}_submitted"] = st.session_state.pop(password_key, "")


def _render_batch_navigation(batch: StatementBatchSession) -> None:
    with st.container(border=True):
        st.subheader(ui_text.REVIEW_STATEMENTS)
        back, position, next_page = st.columns([1, 2, 1], vertical_alignment="center")
        back.button(
            ui_text.BACK, icon=":material/arrow_back:", width="stretch", type="primary",
            key="statement_back", disabled=batch.index == 0, on_click=batch.move, args=(-1,),
        )
        position.markdown(ui_text.statement_position(batch.index + 1, len(batch.items)))
        next_page.button(
            ui_text.NEXT, icon=":material/arrow_forward:", width="stretch", type="primary",
            key="statement_next", disabled=batch.index == len(batch.items) - 1,
            on_click=batch.move, args=(1,),
        )
        st.text(batch.items[batch.index].name)
        st.caption(_batch_status(batch))


def _batch_status(batch: StatementBatchSession) -> str:
    saved = sum(item.saved for item in batch.items)
    failed = sum(bool(item.error) for item in batch.items)
    return ui_text.batch_status(saved, len(batch.pending_indices()), failed)


def _render_batch_save(batch: StatementBatchSession, actions: PortfolioActions) -> None:
    if len(batch.items) < 2 or any(item.password_required for item in batch.items):
        return
    with st.container(border=True):
        st.subheader(ui_text.SAVE_ALL_BALANCES)
        st.caption(ui_text.batch_save_guidance(len(batch.pending_indices())))
        try:
            snapshots = batch.pending_snapshots()
        except ValueError as error:
            st.error(str(error))
            return
        _render_batch_save_approval(batch, actions, snapshots)


def _render_batch_save_approval(
    batch: StatementBatchSession, actions: PortfolioActions, snapshots: list[BalanceSnapshot],
) -> None:
    confirmed = st.checkbox(ui_text.BATCH_CONFIRMATION, key=batch.confirmation_key(snapshots))
    if not st.button(
        ui_text.SAVE_ALL_BALANCES, icon=":material/save:", type="primary", width="stretch",
        key="save_all_statements", disabled=not confirmed or not snapshots,
    ):
        return
    pending = len(batch.pending_indices())
    try:
        count = actions.save_statement_balances(snapshots)
    except ValueError as error:
        st.error(str(error))
    else:
        batch.finish()
        show_saved(ui_text.batch_saved(count, pending))
