from decimal import Decimal

from src import config
from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.portfolio import Portfolio
from src.models.portfolio.precious_metal_holding import PreciousMetalHolding
from src.models.portfolio.precious_metal_price import PreciousMetalPrice
from src.ui import ui_text

TableRow = dict[str, object]


def money(value: Decimal | None, currency: str = "") -> str | None:
    if value is None:
        return None
    formatted = f"{value:,.{config.MONEY_DECIMAL_PLACES}f}"
    if currency != "INR":
        return formatted
    integer, separator, fraction = formatted.replace(",", "").partition(".")
    sign = "-" if integer.startswith("-") else ""
    digits = integer.removeprefix("-")
    groups = [digits[-3:]]
    remaining = digits[:-3]
    while remaining:
        groups.append(remaining[-2:])
        remaining = remaining[:-2]
    return sign + ",".join(reversed(groups)) + separator + fraction


def metal_rate(price: PreciousMetalPrice) -> str:
    return f"{price.currency} {money(price.price, price.currency)} / {price.unit}"


def _detail_row(account: AccountValue) -> TableRow:
    row: TableRow = {}
    if account.account_number:
        row[ui_text.ACCOUNT_NUMBER] = account.account_number
        row[ui_text.ACCOUNT_TYPE] = account.product_type
    if account.precious_metal:
        row.update(_metal_row(account.precious_metal))
    return row


def _metal_row(holding: PreciousMetalHolding) -> dict[str, str]:
    price = holding.price
    return {
        ui_text.PRECIOUS_METAL: price.metal.capitalize(),
        ui_text.PURITY: price.purity,
        ui_text.WEIGHT: f"{holding.quantity.normalize():f} {price.unit}",
        ui_text.PRECIOUS_METAL_RATE: metal_rate(price),
        ui_text.PRECIOUS_METAL_RATE_SOURCE: price.source,
        ui_text.PRECIOUS_METAL_RATE_OBSERVED: price.observation_time,
    }

class PortfolioPresenter:
    """Build display data without database access or a Streamlit runtime."""

    def __init__(self, portfolio: Portfolio):
        self._portfolio = portfolio

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    def stale_accounts(self, days: int | None = None) -> tuple[str, ...]:
        days = config.STALE_AFTER_DAYS if days is None else days
        return tuple(account.account for account in self._portfolio.stale_accounts(days))

    def stale_currencies(self, days: int | None = None) -> tuple[str, ...]:
        days = config.STALE_AFTER_DAYS if days is None else days
        return self._portfolio.stale_currencies(days)

    def account_rows(self) -> list[TableRow]:
        return [self._account_row(account) for account in self._portfolio.accounts]

    def _account_row(self, account: AccountValue) -> TableRow:
        row: TableRow = {
            ui_text.INSTITUTION: account.institution_record().name,
            ui_text.ACCOUNT: account.account,
            ui_text.KIND: account.kind,
            ui_text.CURRENCY: account.currency,
            ui_text.BALANCE_DATE: account.as_of,
            ui_text.net_value(self._portfolio.base_currency): money(
                account.net_value, self._portfolio.base_currency,
            ),
        }
        row.update(_detail_row(account))
        row.update(self._provenance_row(account))
        return row

    def _provenance_row(self, account: AccountValue) -> TableRow:
        return {
            ui_text.BALANCE: money(account.balance, "INR") if account.currency == "INR" else str(account.balance),
            ui_text.SOURCE: account.source,
            ui_text.RECORDED_AT: account.recorded_at,
            ui_text.fx_to(self._portfolio.base_currency): (
                str(account.rate) if account.rate is not None else None
            ),
            ui_text.FX_DATE: (
                account.rate_date if account.currency != self._portfolio.base_currency else None
            ),
        }
