"""Editable statement rows validated before replacing an account's review."""

from collections.abc import Callable
from decimal import Decimal

import streamlit as st
from streamlit.typing import DataEditorState

from src.log_messages import error as error_messages
from src.models.portfolio.validation import (
    account_number,
    decimal_value,
    observation_date,
)
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.transaction_draft import TransactionDraft
from src.ui import ui_text
from src.ui.state import StatementReviewSession

_COLUMNS = (
    ui_text.DATE, ui_text.CURRENCY, ui_text.BALANCE,
    ui_text.WITHDRAWAL, ui_text.DEPOSIT, ui_text.DESCRIPTION,
)


def statement_row(
    balance: StatementBalance | TransactionDraft, amount: Callable[[Decimal], str] = str,
) -> dict[str, str]:
    def shown(value: Decimal | None) -> str:
        return "" if value is None else amount(value)

    return {
        ui_text.DATE: balance.as_of.isoformat(), ui_text.CURRENCY: balance.currency,
        ui_text.BALANCE: shown(balance.balance), ui_text.WITHDRAWAL: shown(balance.withdrawal),
        ui_text.DEPOSIT: shown(balance.deposit), ui_text.DESCRIPTION: balance.description,
    }


def _parse_row(row: dict[str, str | None]) -> StatementBalance:
    values = {column: row.get(column) or "" for column in _COLUMNS}
    if any(not values[key].strip() for key in (ui_text.DATE, ui_text.CURRENCY)):
        raise ValueError(error_messages.STATEMENT_EDIT_REQUIRED_FIELDS)
    return TransactionDraft(
        _optional_decimal(values[ui_text.BALANCE], "Balance"), values[ui_text.CURRENCY],
        observation_date(values[ui_text.DATE]),
        _optional_decimal(values[ui_text.WITHDRAWAL], "Withdrawal"),
        _optional_decimal(values[ui_text.DEPOSIT], "Deposit"), values[ui_text.DESCRIPTION],
    ).to_balance()


def _optional_decimal(value: str, label: str) -> Decimal | None:
    return decimal_value(value, label) if value.strip() else None


def _pending_rows(
    source: list[dict[str, str]], edits: DataEditorState,
) -> list[dict[str, str | None]]:
    rows = [
        {**row, **edits["edited_rows"].get(index, {})}
        for index, row in enumerate(source) if index not in edits["deleted_rows"]
    ]
    return [*rows, *edits["added_rows"]]


def _apply_corrections(session: StatementReviewSession, number: str, key: str) -> None:
    try:
        rows = _pending_rows(
            st.session_state[key + "_data"], st.session_state[key + "_native"],
        )
        if not rows:
            raise ValueError(error_messages.STATEMENT_EDIT_EMPTY_ACCOUNT)
        session.apply_balances(number, tuple(_parse_row(row) for row in rows))
    except ValueError as error:
        st.session_state[key + "_error"] = str(error)


def render_account_editor(
    account: StatementAccount, session: StatementReviewSession,
) -> bool:
    """Return whether this account is currently being edited."""
    if session.is_account_saved(account.number):
        return False
    key = session.editor_key(account.number)
    if session.editing_account != account_number(account.number):
        _render_editor_open_button(account, session, key)
        return False
    _render_editor_form(account, session, key)
    return True


def _render_editor_open_button(
    account: StatementAccount, session: StatementReviewSession, key: str,
) -> None:
    st.button(
        ui_text.EDIT_EXTRACTED_ROWS, key=key + "_open", type="primary",
        disabled=bool(session.editing_account),
        on_click=session.begin_edit, args=(account.number,),
    )


def _render_editor_form(
    account: StatementAccount, session: StatementReviewSession, key: str,
) -> None:
    st.caption(ui_text.STATEMENT_EDIT_HELP)
    _initialize_editor_rows(account, session, key + "_data")
    st.caption(ui_text.row_count(_edited_row_count(
        st.session_state[key + "_data"], key + "_native",
    )))
    st.data_editor(
        st.session_state[key + "_data"],
        key=key + "_native", num_rows="dynamic", hide_index=True,
        width="stretch", column_order=_COLUMNS,
        alt=ui_text.EDITABLE_TRANSACTIONS_ALT,
    )
    _render_editor_controls(account, session, key)


def _initialize_editor_rows(
    account: StatementAccount, session: StatementReviewSession, state_key: str,
) -> None:
    if state_key not in st.session_state:
        source = session.editor_draft
        st.session_state[state_key] = [
            statement_row(row) for row in (source if source is not None else account.balances)
        ]
    elif not isinstance(st.session_state[state_key], list):
        st.session_state[state_key] = [
            dict(row.values) for row in st.session_state[state_key].rows
        ]


def _render_editor_controls(
    account: StatementAccount, session: StatementReviewSession, key: str,
) -> None:
    st.caption(ui_text.REVIEW_SORT_HELP)
    with st.container(horizontal=True):
        st.button(
            ui_text.APPLY_CORRECTIONS, key=key + "_apply", type="primary",
            on_click=_apply_corrections, args=(session, account.number, key),
        )
        st.button(
            ui_text.CANCEL_CORRECTIONS, key=key + "_cancel", type="primary",
            on_click=session.cancel_edit,
        )
    if error := st.session_state.get(key + "_error"):
        st.error(error)


def _edited_row_count(rows: list, editor_key: str) -> int:
    changes = st.session_state.get(editor_key) or {}
    return len(rows) + len(changes.get("added_rows", ())) - len(changes.get("deleted_rows", ()))
