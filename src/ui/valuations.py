from datetime import date

import streamlit as st

from src import config
from src.models.currencies import ISO_CURRENCY_CODES
from src.models.entry.manual_balance import ManualBalance
from src.models.entry.validation import required_text
from src.service.portfolio import PortfolioActions
from src.service.precious_metals import PreciousMetalPricing
from src.ui import ui_text
from src.ui.feedback import show_saved
from src.ui.precious_metals import render_precious_metal_valuation


def render_manual_valuation(
    actions: PortfolioActions, pricing: PreciousMetalPricing | None = None,
) -> None:
    _render_valuation_guidance()
    if pricing is not None and _entry_type() == ui_text.PRECIOUS_METAL_ENTRY:
        render_precious_metal_valuation(actions, pricing)
    else:
        _render_value_form(actions)


def _entry_type() -> str:
    return st.segmented_control(
        ui_text.MANUAL_ENTRY_TYPE, (ui_text.VALUE_ENTRY, ui_text.PRECIOUS_METAL_ENTRY),
        default=ui_text.VALUE_ENTRY, required=True, key="manual_entry_type",
    )


def _render_value_form(actions: PortfolioActions) -> None:
    with st.form("manual_valuation"):
        group, name, kind = _render_identity_inputs()
        currency, amount, as_of = _render_value_inputs()
        save = st.form_submit_button(ui_text.SAVE_VALUATION, type="primary", key="save_valuation")
    if save:
        _save_valuation(actions, group, name, kind, currency, amount, as_of)


def _render_valuation_guidance() -> None:
    st.subheader(ui_text.MANUAL_VALUATION)
    st.caption(ui_text.VALUATION_GUIDANCE)
    st.info(ui_text.VALUATION_UPDATES)


def _render_identity_inputs() -> tuple[str | None, str | None, str | None]:
    group = st.text_input(ui_text.ASSET_GROUP, value=ui_text.PERSONAL_ASSETS, max_chars=100, key="valuation_group")
    name = st.text_input(
        ui_text.ASSET_NAME, max_chars=100, placeholder=ui_text.ASSET_NAME_PLACEHOLDER, key="valuation_name",
    )
    kind = st.selectbox(ui_text.VALUATION_KIND, ["asset", "liability"], key="valuation_kind")
    return group, name, kind


def _render_value_inputs() -> tuple[str | None, str | None, date | tuple[date, ...] | None]:
    currency = st.selectbox(
        ui_text.VALUATION_CURRENCY, ISO_CURRENCY_CODES, key="valuation_currency",
        index=ISO_CURRENCY_CODES.index(config.DEFAULT_DISPLAY_CURRENCY),
    )
    amount = st.text_input(ui_text.TOTAL_VALUE, placeholder=ui_text.AMOUNT_PLACEHOLDER, key="valuation_amount")
    as_of = st.date_input(ui_text.VALUE_AS_OF, value=date.today(), max_value=date.today(), key="valuation_as_of")
    return currency, amount, as_of


def _save_valuation(
    actions: PortfolioActions, group: str | None, name: str | None, kind: str | None,
    currency: str | None, amount: str | None, as_of: date | tuple[date, ...] | None,
) -> None:
    try:
        actions.save_manual(ManualBalance(
            required_text(group, ui_text.ASSET_GROUP),
            name, currency, amount, required_text(kind, ui_text.VALUATION_KIND), as_of,
        ))
    except ValueError as error:
        st.error(str(error))
    else:
        show_saved(ui_text.VALUATION_SAVED)
