"""Build historical wealth charts independently of the Streamlit runtime."""

from datetime import date

import altair as alt
import pandas as pd

from src.models.dto.history_point import HistoryPoint
from src.ui import ui_text
from src.ui.presentation import money


def build_history_chart(
    points: tuple[HistoryPoint, ...], currency: str,
) -> alt.LayerChart | alt.FacetChart:
    base = _base_chart(points, currency)
    hover = alt.selection_point(
        name="history_hover", fields=["Date"], nearest=True,
        on="pointerover", clear="pointerout", empty=False,
    )
    targets = base.mark_point(opacity=0, size=100).encode(y=alt.value(0)).add_params(hover)
    highlighted = base.mark_point(size=90).transform_filter(hover)
    rule = base.mark_rule(color="gray").encode(y=alt.Undefined).transform_filter(hover)
    details = _hover_details(base, hover)
    return alt.layer(base.mark_line(point=True), highlighted, rule, targets, details)


def _base_chart(points: tuple[HistoryPoint, ...], currency: str) -> alt.Chart:
    label = ui_text.net_worth(currency)
    return alt.Chart(_history_frame(points, currency)).encode(
        x=_time_axis(points),
        y=alt.Y(f"{label}:Q", title=label, axis=alt.Axis(labelExpr=_value_labels(currency))),
        tooltip=[
            alt.Tooltip("Date:T", title=ui_text.DATE, format="%d %b %Y"),
            alt.Tooltip("Formatted value:N", title=label),
        ],
    )


def _history_frame(points: tuple[HistoryPoint, ...], currency: str) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Date": point.as_of, ui_text.net_worth(currency): float(point.net_worth),
            "Formatted value": money(point.net_worth, currency),
            "Hover details": ui_text.history_hover(point.as_of, currency, money(point.net_worth, currency)),
        } for point in points
    ])


def _time_axis(points: tuple[HistoryPoint, ...]) -> alt.X:
    years = sorted({point.as_of.year for point in points})
    ticks = [date(year, 1, 1).isoformat() for year in range(years[0], years[-1] + 1)]
    return alt.X(
        "Date:T", title=ui_text.YEAR,
        axis=alt.Axis(format="%Y", values=ticks, labelAngle=0),
        scale=alt.Scale(domain=[
            date(years[0], 1, 1).isoformat(),
            max(max(point.as_of for point in points), date(years[-1], 1, 2)).isoformat(),
        ]),
    )


def _value_labels(currency: str) -> str:
    if currency == "INR":
        return (
            "abs(datum.value) >= 10000000 ? format(datum.value / 10000000, '~f') + 'cr' : "
            "abs(datum.value) >= 100000 ? format(datum.value / 100000, '~f') + 'L' : "
            "format(datum.value, ',~f')"
        )
    return (
        "abs(datum.value) >= 1000000 ? format(datum.value / 1000000, '~f') + 'M' : "
        "abs(datum.value) >= 1000 ? format(datum.value / 1000, '~f') + 'K' : "
        "format(datum.value, ',~f')"
    )


def _hover_details(base: alt.Chart, hover: alt.Parameter) -> alt.Chart:
    return base.mark_text(align="left", baseline="top", fontSize=13).encode(
        x=alt.value(12), y=alt.value(12), text="Hover details:N",
    ).transform_filter(hover)
