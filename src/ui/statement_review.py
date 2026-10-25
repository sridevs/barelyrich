"""Account review widgets and save actions for a single extracted statement."""

from dataclasses import dataclass

import streamlit as st

from src.models.entry.statement_review import StatementReview
from src.models.portfolio.validation import account_number, institution_name
from src.models.statements.statement_account import StatementAccount
from src.service.portfolio import PortfolioActions
from src.ui.feedback import show_saved
from src.ui import ui_text
from src.ui.presentation import money
from src.ui.state import StatementReviewSession
from src.ui.statement_batch import StatementBatchSession


def render_statement_review(
    preview: StatementReview, actions: PortfolioActions,
    session: StatementReviewSession, batch: StatementBatchSession,
) -> None:
    st.subheader(ui_text.REVIEW_BALANCES)
    institution = _render_institution(preview, actions, session)
    _render_review_guidance()
    cards = _AccountReviewCards(preview, institution, actions, session, batch)
    for index, account in enumerate(preview.extraction.accounts, start=1):
        cards.render(index, account)


def _render_review_guidance() -> None:
    st.warning(ui_text.REVIEW_WARNING)
    with st.expander(ui_text.ACCOUNT_UPDATES):
        st.caption(ui_text.ACCOUNT_UPDATES_HELP)


def _institution_options(preview: StatementReview, actions: PortfolioActions) -> tuple[list[str], int]:
    names = [record.name for record in actions.institutions()]
    detected_name = institution_name(preview.institution)
    if detected_name.casefold() not in {institution_name(name).casefold() for name in names}:
        names.insert(0, detected_name)
    selected_index = next(
        index for index, name in enumerate(names)
        if institution_name(name).casefold() == detected_name.casefold()
    )
    return names, selected_index


def _render_institution(
    preview: StatementReview, actions: PortfolioActions, session: StatementReviewSession,
) -> str:
    names, selected_index = _institution_options(preview, actions)
    return st.selectbox(
        ui_text.STATEMENT_INSTITUTION, names, index=selected_index, accept_new_options=True,
        key=session.widget_key(
            f"statement_institution_{session.upload_revision}_{preview.file_digest}",
        ),
        persist_state="session",
        help=ui_text.INSTITUTION_HELP,
    ) or ""


@dataclass
class _AccountReviewCards:
    _preview: StatementReview
    _institution: str
    _actions: PortfolioActions
    _session: StatementReviewSession
    _batch: StatementBatchSession

    def render(self, index: int, account: StatementAccount) -> None:
        number = account_number(account.number)
        with st.container(border=True, gap="xsmall", key=f"statement_review_account_{index}"):
            st.markdown(ui_text.account_heading(index, account.number))
            st.caption(ui_text.statement_date(account.balances[0].as_of))
            product_type = self._render_type(number)
            alias = self._render_alias(number)
            _render_balances(account)
            if self._session.is_account_saved(number):
                st.caption(ui_text.SAVED)
            else:
                self._render_approval(number, product_type, alias, index)

    def _render_type(self, number: str) -> str:
        product_type = st.text_input(
            ui_text.ACCOUNT_TYPE, max_chars=100,
            key=self._session.account_type_key(self._preview, number),
            persist_state="session",
            help=ui_text.ACCOUNT_TYPE_HELP,
            disabled=self._session.is_account_saved(number),
        ) or ""
        if not self._session.is_account_saved(number):
            self._session.update_suggested_alias(self._preview, number, product_type)
        return product_type

    def _render_alias(self, number: str) -> str:
        alias = st.text_input(
            ui_text.ACCOUNT_ALIAS, max_chars=100,
            key=self._session.account_alias_key(self._preview, number),
            persist_state="session",
            help=ui_text.ACCOUNT_ALIAS_HELP,
            disabled=self._session.is_account_saved(number),
        )
        return alias.strip() if alias else ""

    def _render_approval(self, number: str, product_type: str, alias: str, index: int) -> None:
        try:
            reviewed = self._preview.with_account_type(number, product_type)
        except ValueError as error:
            st.error(str(error))
            return
        confirmed = self._render_confirmation(reviewed, number, alias, index)
        if self._render_save_button(confirmed, alias, index):
            self._save(reviewed, number, alias, index)

    def _render_confirmation(
        self, review: StatementReview, number: str, alias: str, index: int,
    ) -> bool:
        return st.checkbox(
            ui_text.account_confirmation(self._single_account, index),
            key=self._session.widget_key(review.confirmation_key({number: alias}, self._institution)),
            persist_state="session",
        )

    @property
    def _single_account(self) -> bool:
        return len(self._preview.extraction.accounts) == 1

    def _render_save_button(self, confirmed: bool, alias: str, index: int) -> bool:
        return st.button(
            ui_text.save_account_label(self._single_account, index), icon=":material/save:", type="primary",
            disabled=not confirmed or not self._institution.strip() or not alias,
            key="save_statement" if self._single_account else f"save_statement_account_{index}",
        )

    def _save(self, review: StatementReview, number: str, alias: str, index: int) -> None:
        try:
            count = self._actions.save_statement_review(review, {number: alias}, self._institution)
        except ValueError as error:
            st.error(str(error))
        else:
            self._batch.mark_account_saved(number)
            if not self._batch.pending_indices():
                self._batch.finish()
            show_saved(ui_text.account_saved(count, self._single_account, index))


def _render_balances(account: StatementAccount) -> None:
    st.table(
        [
            {ui_text.CURRENCY: balance.currency, ui_text.BALANCE: money(balance.balance, balance.currency)}
            for balance in account.balances
        ],
        hide_index=True, hide_header=False, border="horizontal",
        alt=ui_text.BALANCES_ALT,
    )
    for balance in account.balances:
        for warning in balance.review_warnings():
            st.warning(ui_text.currency_warning(balance.currency, warning))
    _render_classifications(account)


def _render_classifications(account: StatementAccount) -> None:
    with st.expander(ui_text.AI_INTERPRETATION):
        st.table(
            [
                {
                    ui_text.CURRENCY: balance.currency,
                    ui_text.BALANCE_TYPE: balance.balance_role.replace("_", " "),
                    ui_text.SCOPE: balance.account_scope.replace("_", " "),
                    ui_text.DATE_TYPE: balance.date_role.replace("_", " "),
                }
                for balance in account.balances
            ],
            hide_index=True, hide_header=False, border="horizontal",
            alt=ui_text.CLASSIFICATIONS_ALT,
        )
