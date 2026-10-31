from datetime import date
from pathlib import Path

import streamlit as st

from src.models.portfolio.portfolio import Portfolio
from src.providers.exchange_rates import (
    ExchangeRateFetchError,
    FrankfurterExchangeRateProvider,
)
from src.repo.portfolio import PortfolioStore
from src.service.exchange_rates import ExchangeRateRefresh
from src.service.portfolio import PortfolioActions, PortfolioHistory
from src.ui import ui_text
from src.ui.dto.valuation_selection import ValuationSelection
from src.ui.forms import render_account_forms
from src.ui.presentation import PortfolioPresenter
from src.ui.sections import (
    render_balance_history,
    render_net_worth_history,
    render_portfolio_header,
    render_recorded_wealth,
    render_valuation_selection,
)


def render_portfolio(db_path: Path) -> None:
    render_portfolio_header()
    valuation_selection = render_valuation_selection()
    if valuation_selection:
        render_portfolio_layout(
            PortfolioStore(db_path), valuation_selection,
        )


def render_portfolio_layout(
        store: PortfolioStore,
        selection: ValuationSelection,
) -> None:
    entry_tab, overview_tab = st.tabs([
        ui_text.DATA_ENTRY, ui_text.PORTFOLIO_OVERVIEW,
    ])
    with entry_tab:
        render_account_forms(PortfolioActions(store))
    portfolio = store.portfolio(selection.as_of, selection.currency)
    with overview_tab:
        portfolio = render_live_overview(store, portfolio)
        if portfolio.accounts:
            render_balance_history(store.balance_history(selection.as_of))


def render_live_overview(store: PortfolioStore, portfolio: Portfolio) -> Portfolio:
    render_automatic_fx(store, portfolio)
    refreshed = store.portfolio(portfolio.as_of, portfolio.base_currency)
    render_recorded_wealth(PortfolioPresenter(refreshed))
    if refreshed.accounts:
        _render_historical_overview(store, portfolio)
    return refreshed


def _render_historical_overview(store: PortfolioStore, portfolio: Portfolio) -> None:
    dates = {date.fromisoformat(row["as_of"]) for row in store.balance_history(portfolio.as_of)}
    dates.add(portfolio.as_of)
    try:
        _refresh_historical_fx(store, portfolio, dates)
        points = PortfolioHistory(store).at_dates(dates, portfolio.base_currency)
    except ExchangeRateFetchError as error:
        st.warning(ui_text.historical_chart_error(error))
    except ValueError as error:
        st.warning(str(error))
    else:
        render_net_worth_history(points, portfolio.base_currency)


def _fx_refresh(store: PortfolioStore) -> ExchangeRateRefresh:
    return ExchangeRateRefresh(FrankfurterExchangeRateProvider(), store)


def _refresh_historical_fx(store: PortfolioStore, portfolio: Portfolio, dates: set[date]) -> None:
    refresh = _fx_refresh(store)
    for day in sorted(dates - {portfolio.as_of}):
        refresh.refresh_historical(store.portfolio(day, portfolio.base_currency))


def render_automatic_fx(store: PortfolioStore, portfolio: Portfolio) -> None:
    try:
        observations = _fx_refresh(store).refresh(portfolio)
    except ExchangeRateFetchError as error:
        st.warning(ui_text.fx_refresh_error(error))
    else:
        if observations:
            published_dates = ", ".join(sorted({item.as_of.isoformat() for item in observations}))
            st.caption(ui_text.fx_refreshed(published_dates))
