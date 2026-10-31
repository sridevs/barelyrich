from datetime import date
from decimal import Decimal

import streamlit as st

from src import config
from src.models.entry.precious_metal_valuation import PreciousMetalValuation
from src.models.portfolio.precious_metal import PreciousMetal
from src.models.portfolio.precious_metal_holding import PreciousMetalHolding
from src.models.portfolio.precious_metal_price import PreciousMetalPrice
from src.models.precious_metals import PRECIOUS_METALS
from src.providers.exchange_rates import ExchangeRateFetchError
from src.providers.spot_prices import SpotPriceFetchError
from src.service.portfolio import PortfolioActions
from src.service.precious_metals import PreciousMetalPricing
from src.ui import ui_text
from src.ui.feedback import show_saved
from src.ui.presentation import metal_rate, money

_WEIGHT_PRECISION = Decimal("0.001")


@st.cache_data(ttl=config.SPOT_PRICE_CACHE_SECONDS, show_spinner=False)
def _current_prices(
    _pricing: PreciousMetalPricing, metal_name: str, database: str,
) -> tuple[PreciousMetalPrice, ...]:
    del database
    return _pricing.current_prices(PRECIOUS_METALS[metal_name])


def render_precious_metal_valuation(
    actions: PortfolioActions, pricing: PreciousMetalPricing,
) -> None:
    metal, purity, weight = _render_holding_inputs()
    price = _price(pricing, metal, purity)
    if price is None:
        return
    holding = PreciousMetalHolding(weight, price)
    _render_estimate(holding)
    _render_save_form(actions, holding)


def _render_holding_inputs() -> tuple[PreciousMetal, str, Decimal]:
    metal = PRECIOUS_METALS[st.selectbox(
        ui_text.METAL, tuple(PRECIOUS_METALS), format_func=str.capitalize, key="metal_name",
    )]
    purity = st.segmented_control(
        ui_text.PURITY, metal.purity_labels, default=metal.purity_labels[0],
        required=True, key="metal_purity",
    )
    weight = st.number_input(
        ui_text.METAL_WEIGHT, min_value=0.001, value=1.0, step=0.1,
        format="%.3f", key="metal_weight",
    )
    return metal, purity, Decimal(str(weight)).quantize(_WEIGHT_PRECISION)


def _price(
    pricing: PreciousMetalPricing, metal: PreciousMetal, purity: str,
) -> PreciousMetalPrice | None:
    try:
        prices = _current_prices(pricing, metal.name, str(pricing.database_path))
    except (SpotPriceFetchError, ExchangeRateFetchError) as error:
        st.error(ui_text.metal_price_error(error))
        return None
    return next(price for price in prices if price.purity == purity)


def _render_estimate(holding: PreciousMetalHolding) -> None:
    price = holding.price
    with st.container(horizontal=True):
        st.metric(ui_text.METAL_RATE, metal_rate(price), border=True)
        st.metric(
            ui_text.ESTIMATED_METAL_VALUE,
            f"{price.currency} {money(holding.value(), price.currency)}", border=True,
        )
    st.caption(ui_text.metal_rate_provenance(price))
    st.caption(ui_text.METAL_VALUATION_CAVEAT)


def _render_save_form(actions: PortfolioActions, holding: PreciousMetalHolding) -> None:
    with st.form("precious_metal_valuation"):
        name = st.text_input(
            ui_text.ASSET_NAME, value=holding.price.metal.capitalize(),
            max_chars=100, key="metal_asset_name",
        )
        save = st.form_submit_button(
            ui_text.SAVE_METAL_HOLDING, type="primary", key="save_metal_holding",
        )
    if save:
        _save(actions, name, holding)


def _save(actions: PortfolioActions, name: str, holding: PreciousMetalHolding) -> None:
    try:
        actions.save_precious_metal(PreciousMetalValuation(
            ui_text.PRECIOUS_METALS_GROUP, name, holding, date.today(),
        ))
    except ValueError as error:
        st.error(str(error))
    else:
        show_saved(ui_text.METAL_HOLDING_SAVED)
