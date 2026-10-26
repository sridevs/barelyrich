import streamlit as st
from streamlit.typing import UploadedFile

from src import config
from src.documents.images import (
    IncorrectStatementPasswordError, StatementPasswordRequiredError,
)
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.service.entry import EntryServices
from src.service.portfolio import PortfolioActions
from src.ui.feedback import show_saved
from src.ui import ui_text
from src.ui.models.statement_batch_item import StatementBatchItem
from src.ui.state import StatementReviewSession
from src.ui.statement_batch import StatementBatchSession
from src.ui.statement_review import render_statement_review
from src.ui.valuations import render_manual_valuation


_SELECTED_CARD = "wealth_card_selected"
_SELECTION_KEY = "wealth_entry"
_SELECTED_CARD_STYLE = f"""
    <style>
    .st-key-{_SELECTED_CARD} {{
        background: rgba(34, 197, 94, 0.10);
        border: 2px solid #15803d;
        border-radius: 0.75rem;
    }}
    .st-key-{_SELECTED_CARD} button {{
        background: #15803d;
        color: #ffffff;
        border-color: #15803d;
    }}
    </style>
"""


def render_statement_import(actions: PortfolioActions, services: EntryServices) -> None:
    review_session = StatementReviewSession(st.session_state)
    with st.container(border=True):
        _render_statement_guidance()
        kind, uploads, log_model_output = _render_statement_inputs(review_session)
        batch = StatementBatchSession(st.session_state)
        _invalidate_changed_batch(batch, uploads, kind)
        _handle_statement_extraction(uploads, kind, log_model_output, services, batch)
        if batch.items:
            _render_batch_navigation(batch)
            _render_current_statement(
                batch, actions, uploads, kind, log_model_output, services,
            )
            _render_batch_save(batch, actions)


def _invalidate_changed_batch(
    batch: StatementBatchSession, uploads: list[UploadedFile], kind: str,
) -> None:
    files = [(item.name, item.getvalue()) for item in uploads]
    if batch.items and not batch.matches(files, kind):
        batch.clear()
        st.warning(ui_text.BATCH_CHANGED)


def _render_current_statement(
    batch: StatementBatchSession, actions: PortfolioActions,
    uploads: list[UploadedFile], kind: str, log_model_output: bool,
    services: EntryServices,
) -> None:
    item = batch.items[batch.index]
    if item.error:
        st.error(item.error)
        return
    if item.saved:
        st.info(ui_text.STATEMENT_SAVED)
        return
    _render_password_if_needed(
        item, batch, uploads, kind, log_model_output, services,
    )
    session = batch.review_session(batch.index)
    preview = session.preview
    if preview:
        render_statement_review(preview, actions, session, batch)


def _render_password_if_needed(
    item: StatementBatchItem, batch: StatementBatchSession, uploads: list[UploadedFile],
    kind: str, log_model_output: bool, services: EntryServices,
) -> None:
    if not item.password_required:
        return
    st.info(ui_text.ENTER_STATEMENT_PASSWORD)
    if item.password_error:
        st.error(item.password_error)
    _render_password_form(batch, uploads[batch.index], kind, log_model_output, services)


def _render_password_form(
    batch: StatementBatchSession, upload: UploadedFile, kind: str,
    log_model_output: bool, services: EntryServices,
) -> None:
    password_key = f"statement_password_{batch.index}_{batch.review_session(batch.index).upload_revision}"
    with st.form(f"statement_password_form_{batch.index}"):
        st.text_input(
            ui_text.STATEMENT_PASSWORD, type="password", key=password_key,
            help=ui_text.STATEMENT_PASSWORD_HELP,
        )
        st.form_submit_button(
            ui_text.SUBMIT_STATEMENT_PASSWORD,
            type="primary",
            on_click=_retry_protected_statement,
            args=(
                batch, batch.index, upload.name, upload.getvalue(), kind,
                log_model_output, services, password_key,
            ),
        )


def _retry_protected_statement(
    batch: StatementBatchSession, index: int, filename: str, content: bytes,
    kind: str, log_model_output: bool, services: EntryServices, password_key: str,
) -> None:
    password = st.session_state.pop(password_key, "")
    try:
        if not password:
            batch.password_failed(index, ui_text.ENTER_STATEMENT_PASSWORD)
        else:
            extraction = services.preview(
                filename, content, log_model_output=log_model_output, password=password,
            )
            batch.review_session(index).start(content, kind, extraction)
            batch.password_succeeded(index)
    except IncorrectStatementPasswordError as error:
        batch.password_failed(index, str(error))
    except ValueError as error:
        batch.fail(index, str(error))


def _render_batch_navigation(batch: StatementBatchSession) -> None:
    with st.container(border=True):
        st.subheader(ui_text.REVIEW_STATEMENTS)
        _render_navigation_buttons(batch)
        st.text(batch.items[batch.index].name)
        saved = sum(item.saved for item in batch.items)
        failed = sum(bool(item.error) for item in batch.items)
        st.caption(ui_text.batch_status(saved, len(batch.pending_indices()), failed))


def _render_navigation_buttons(batch: StatementBatchSession) -> None:
    back, position, next_page = st.columns([1, 2, 1], vertical_alignment="center")
    back.button(
        ui_text.BACK, icon=":material/arrow_back:", width="stretch",
        key="statement_back", disabled=batch.index == 0,
        on_click=batch.move, args=(-1,),
    )
    position.markdown(ui_text.statement_position(batch.index + 1, len(batch.items)))
    next_page.button(
        ui_text.NEXT, icon=":material/arrow_forward:", width="stretch", type="primary",
        key="statement_next", disabled=batch.index == len(batch.items) - 1,
        on_click=batch.move, args=(1,),
    )


def _render_batch_save(batch: StatementBatchSession, actions: PortfolioActions) -> None:
    if len(batch.items) < 2 or any(item.password_required for item in batch.items):
        return
    with st.container(border=True):
        _render_batch_save_guidance(batch)
        try:
            snapshots = batch.pending_snapshots()
        except ValueError as error:
            st.error(str(error))
            return
        if _render_batch_save_approval(batch, snapshots):
            _save_batch(batch, actions, snapshots)


def _render_batch_save_guidance(batch: StatementBatchSession) -> None:
    st.subheader(ui_text.SAVE_ALL_BALANCES)
    st.caption(ui_text.batch_save_guidance(len(batch.pending_indices())))


def _render_batch_save_approval(
    batch: StatementBatchSession, snapshots: list[BalanceSnapshot],
) -> bool:
    confirmed = st.checkbox(
        ui_text.BATCH_CONFIRMATION,
        key=batch.confirmation_key(snapshots),
    )
    return st.button(
        ui_text.SAVE_ALL_BALANCES, icon=":material/save:", type="primary", width="stretch",
        key="save_all_statements", disabled=not confirmed or not snapshots,
    )


def _save_batch(
    batch: StatementBatchSession, actions: PortfolioActions, snapshots: list[BalanceSnapshot],
) -> None:
    pending = len(batch.pending_indices())
    try:
        count = actions.save_statement_balances(snapshots)
    except ValueError as error:
        st.error(str(error))
    else:
        batch.finish()
        show_saved(ui_text.batch_saved(count, pending))


def _render_statement_guidance() -> None:
    st.subheader(ui_text.PARSE_WITH_AI)
    st.caption(ui_text.statement_guidance())


def _render_statement_inputs(
    review_session: StatementReviewSession,
) -> tuple[str, list[UploadedFile], bool]:
    kind = st.selectbox(
        ui_text.ASSET_TYPE, ["asset", "liability"], key="statement_kind",
        help=ui_text.ASSET_TYPE_HELP,
    )
    upload = st.file_uploader(
        ui_text.statement_upload_label(),
        type=["pdf"], accept_multiple_files=True,
        key=f"statement_upload_{review_session.upload_revision}",
        max_upload_size=config.STATEMENT_UPLOAD_MB,
    )
    uploads = upload if isinstance(upload, list) else [upload] if upload else []
    return kind, uploads, _render_debug_option()


def _render_debug_option() -> bool:
    return st.checkbox(
        ui_text.DEBUG_OUTPUT,
        value=False, key="statement_debug_output",
        help=ui_text.DEBUG_OUTPUT_HELP,
    )


def _handle_statement_extraction(
    uploads: list[UploadedFile], kind: str, log_model_output: bool,
    services: EntryServices, batch: StatementBatchSession,
) -> None:
    if not st.button(ui_text.EXTRACT_BALANCES, disabled=not uploads, key="extract_statement"):
        return
    batch.begin([(upload.name, upload.getvalue()) for upload in uploads], kind)
    for index, upload in enumerate(uploads):
        try:
            with st.spinner(ui_text.parsing_statement(index + 1, len(uploads), upload.name)):
                _extract_statement(upload, index, kind, log_model_output, services, batch)
        except StatementPasswordRequiredError:
            batch.require_password(index)
        except ValueError as error:
            batch.fail(index, str(error))


def _extract_statement(
    upload: UploadedFile, index: int, kind: str, log_model_output: bool,
    services: EntryServices, batch: StatementBatchSession,
) -> None:
    content = upload.getvalue()
    extraction = services.preview(upload.name, content, log_model_output=log_model_output)
    batch.review_session(index).start(content, kind, extraction)


def render_account_forms(actions: PortfolioActions, services: EntryServices | None = None) -> None:
    services = services or EntryServices()
    st.subheader(ui_text.DATA_ENTRY)
    selected = st.session_state.setdefault(_SELECTION_KEY, "Parse statement")
    st.html(_SELECTED_CARD_STYLE)
    for column, workflow in zip(st.columns(2), _workflows()):
        with column:
            _render_workflow_card(workflow, selected)
    if selected == "Manual valuation":
        render_manual_valuation(actions)
    else:
        render_statement_import(actions, services)


def _workflows() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("Parse statement", ui_text.PARSE_STATEMENT, ui_text.ACCOUNT_BALANCES, ui_text.STATEMENT_DESCRIPTION),
        ("Manual valuation", ui_text.MANUAL_VALUATION, ui_text.OTHER_ASSETS, ui_text.VALUATION_DESCRIPTION),
    )


def _render_workflow_card(workflow: tuple[str, str, str, str], selected: str) -> None:
    identity, label, caption, description = workflow
    with st.container(
        border=True, height="stretch",
        key=_SELECTED_CARD if selected == identity else f"wealth_card_{identity}",
    ):
        st.caption(caption)
        st.markdown(f"### {label}")
        st.write(description)
        st.caption(ui_text.SELECTED if selected == identity else ui_text.CHOOSE_WORKFLOW)
        st.button(
            label, key=f"choose_{identity}", width="stretch",
            type="primary" if selected == identity else "secondary",
            on_click=st.session_state.update, args=({_SELECTION_KEY: identity},),
        )
