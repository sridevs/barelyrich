from src.ui.models.valuation_selection import ValuationSelection
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from src import config
from src.models.portfolio.portfolio import Portfolio
from src.models.history.history_point import HistoryPoint
from src.ui.presentation import money, PortfolioPresenter
from src.ui.history_chart import build_history_chart
from src.ui import ui_text


def render_valuation_selection() -> ValuationSelection | None:
    today = date.today()
    currency = st.sidebar.selectbox(
        ui_text.DISPLAY_CURRENCY, config.DISPLAY_CURRENCIES, key="display_currency",
        index=config.DISPLAY_CURRENCIES.index(config.DEFAULT_DISPLAY_CURRENCY),
    )
    as_of = st.sidebar.date_input(
        ui_text.VALUATION_DATE, value=today, max_value=today, key="valuation_date",
    )
    if not isinstance(as_of, date):
        st.error(ui_text.SELECT_VALUATION_DATE)
        return None
    st.sidebar.caption(ui_text.DATED_OBSERVATIONS_HELP)
    return ValuationSelection(currency, as_of)


def render_portfolio_header() -> None:
    st.title(config.APP_TITLE)
    st.caption(ui_text.PORTFOLIO_TAGLINE)
    st.sidebar.warning(ui_text.STORAGE_WARNING)
    message = st.session_state.pop("portfolio_message", None)
    if message:
        st.success(message)


def render_staleness(presenter: PortfolioPresenter) -> None:
    accounts = presenter.stale_accounts()
    if accounts:
        st.warning(ui_text.stale_accounts(accounts))
    currencies = presenter.stale_currencies()
    if currencies:
        st.warning(ui_text.stale_currencies(currencies))


def render_wealth_summary(portfolio: Portfolio) -> None:
    st.caption(ui_text.valuation_summary(portfolio.as_of))
    if portfolio.missing_currencies:
        st.error(ui_text.missing_fx(portfolio.missing_currencies, portfolio.base_currency))
    else:
        st.metric(
            ui_text.recorded_net_worth(portfolio.base_currency),
            money(portfolio.net_worth, portfolio.base_currency),
        )


def render_recorded_wealth(presenter: PortfolioPresenter) -> None:
    st.subheader(ui_text.RECORDED_WEALTH)
    if not presenter.portfolio.accounts:
        st.info(ui_text.NO_WEALTH)
        return
    render_wealth_summary(presenter.portfolio)
    render_staleness(presenter)
    st.dataframe(pd.DataFrame(presenter.account_rows()), hide_index=True, width="stretch")


def render_balance_history(rows: list[dict[str, str]]) -> None:
    with st.expander(ui_text.BALANCE_HISTORY):
        displayed_rows = [
            {**row, "balance": money(Decimal(row["balance"]), "INR")}
            if row["currency"] == "INR" else row
            for row in rows
        ]
        st.dataframe(pd.DataFrame(displayed_rows), hide_index=True, width="stretch")


def render_net_worth_history(points: tuple[HistoryPoint, ...], currency: str) -> None:
    st.subheader(ui_text.NET_WORTH_HISTORY)
    if not points:
        st.info(ui_text.NO_HISTORY)
        return
    st.caption(ui_text.HISTORY_GUIDANCE)
    st.altair_chart(
        build_history_chart(points, currency), width="stretch",
        alt=ui_text.HISTORY_ALT,
    )
