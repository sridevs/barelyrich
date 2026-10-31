from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.models.dto.history_point import HistoryPoint
from src.ui.sections import render_net_worth_history


@pytest.mark.parametrize("currency,units,thresholds", [
    ("INR", ("'L'", "'cr'"), ("100000", "10000000")),
    ("SGD", ("'K'", "'M'"), ("1000", "1000000")),
])
def test_chart_uses_year_ticks_and_currency_specific_units(currency, units, thresholds):
    points = (
        HistoryPoint(date(2022, 6, 15), Decimal("1234567.89")),
        HistoryPoint(date(2024, 10, 1), Decimal("-23456789")),
    )
    with patch("src.ui.sections.st.altair_chart") as render:
        render_net_worth_history(points, currency)
    specification = render.call_args.args[0].to_dict()
    encoding = specification["layer"][0]["encoding"]
    horizontal = encoding["x"]
    assert horizontal["axis"]["format"] == "%Y"
    assert horizontal["axis"]["values"] == ["2022-01-01", "2023-01-01", "2024-01-01"]
    assert horizontal["scale"]["domain"] == ["2022-01-01", "2024-10-01"]
    expression = encoding["y"]["axis"]["labelExpr"]
    assert ".2f" not in expression
    assert "~f" in expression
    for unit, threshold in zip(units, thresholds):
        assert unit in expression
        assert f"abs(datum.value) >= {threshold}" in expression
    tooltip = encoding["tooltip"]
    assert tooltip[0]["format"] == "%d %b %Y"
    records = next(iter(specification["datasets"].values()))
    assert records[0]["Formatted value"] == (
        "12,34,567.89" if currency == "INR" else "1,234,567.89"
    )
    assert records[1][f"Net worth ({currency})"] == -23456789


def test_single_point_chart_keeps_a_nonzero_date_domain():
    with patch("src.ui.sections.st.altair_chart") as render:
        render_net_worth_history((HistoryPoint(date(2022, 1, 1), Decimal("0")),), "INR")
    specification = render.call_args.args[0].to_dict()
    assert specification["layer"][0]["encoding"]["x"]["scale"]["domain"] == [
        "2022-01-01", "2022-01-02",
    ]
    assert specification["layer"][0]["mark"]["point"] is True
    selection = specification["params"][0]["select"]
    assert selection["nearest"] is True
    assert selection["on"] == "pointerover"
    assert selection["fields"] == ["Date"]
    for layer in specification["layer"]:
        assert layer["encoding"]["tooltip"][1]["field"] == "Formatted value"
    details = specification["layer"][-1]
    assert details["mark"]["type"] == "text"
    assert details["encoding"]["text"]["field"] == "Hover details"
    assert details["transform"][0]["filter"]["param"] == "history_hover"
    records = next(iter(specification["datasets"].values()))
    assert records[0]["Hover details"] == "01 Jan 2022 | INR 0.00"


def test_empty_history_is_explicitly_reported():
    with (
        patch("src.ui.sections.st.altair_chart") as render,
        patch("src.ui.sections.st.info") as info,
    ):
        render_net_worth_history((), "INR")
    render.assert_not_called()
    info.assert_called_once_with("No recorded wealth history yet.")
