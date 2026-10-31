from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import create_autospec

import pytest

from src.models.entry.manual_balance import ManualBalance
from src.models.entry.validation import required_date, required_text
from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.portfolio import Portfolio
from src.repo.portfolio import PortfolioStore
from src.service.portfolio import PortfolioActions, PortfolioHistory

DAY = date(2026, 1, 1)


@pytest.fixture
def writer():
    return create_autospec(PortfolioStore, instance=True)


def command(**changes):
    values = dict(
        institution="dbs_sg", alias=" Savings ", currency=" SGD ",
        amount=" 123.45 ", kind="asset", as_of=DAY,
    )
    values.update(changes)
    return ManualBalance(**values)


def test_manual_command_builds_validated_snapshot():
    assert command().snapshot() == BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("123.45"), "asset", DAY, "manual",
    )


@pytest.mark.parametrize("changes", [
    {"alias": None}, {"alias": " "}, {"currency": None}, {"currency": "sgd"},
    {"amount": None}, {"amount": "not money"}, {"amount": "NaN"},
    {"as_of": None}, {"as_of": ()}, {"as_of": datetime(2026, 1, 1)},
    {"as_of": date.today() + timedelta(days=1)},
    {"institution": ""}, {"kind": "liability", "amount": "-1"},
])
def test_invalid_command_never_writes(writer, changes):
    with pytest.raises(ValueError):
        PortfolioActions(writer).save_manual(command(**changes))
    writer.save.assert_not_called()


def test_save_manual_delegates_one_snapshot(writer):
    PortfolioActions(writer).save_manual(command())
    writer.save.assert_called_once_with([command().snapshot()])


def test_save_statement_persists_a_statement_sourced_snapshot(writer):
    statement_snapshot = BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("123.45"), "asset", DAY, "statement",
    )
    PortfolioActions(writer).save_statement_balances([statement_snapshot])
    writer.save.assert_called_once_with([statement_snapshot])


def test_save_statement_rejects_other_sources_without_writing(writer):
    csv_snapshot = BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("123.45"), "asset", DAY, "csv",
    )
    with pytest.raises(ValueError, match="statement-sourced"):
        PortfolioActions(writer).save_statement_balances([csv_snapshot])
    writer.save.assert_not_called()


def test_repository_errors_are_not_converted_to_success(writer):
    writer.save.side_effect = OSError("Database unavailable")
    with pytest.raises(OSError, match="Database unavailable"):
        PortfolioActions(writer).save_manual(command())


def test_rate_command_normalizes_and_delegates(writer):
    PortfolioActions(writer).save_rate(" SGD ", " 60.25 ", DAY)
    writer.save_rate.assert_called_once_with("SGD", "60.25", DAY)


@pytest.mark.parametrize("currency,rate,as_of", [
    (None, "60", DAY), (" ", "60", DAY), ("SGD", None, DAY),
    ("SGD", "", DAY), ("SGD", "60", None), ("SGD", "60", (DAY,)),
])
def test_invalid_rate_command_never_writes(writer, currency, rate, as_of):
    with pytest.raises(ValueError):
        PortfolioActions(writer).save_rate(currency, rate, as_of)
    writer.save_rate.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "  "])
def test_required_text_rejects_missing_input(value):
    with pytest.raises(ValueError, match="Alias is required"):
        required_text(value, "Alias")


def test_required_date_accepts_dates_only():
    assert required_date(DAY, "a date") == DAY
    with pytest.raises(ValueError, match="Select a date"):
        required_date("2026-01-01", "a date")


def valued_portfolio(day):
    return Portfolio((AccountValue(
        "Savings", "dbs_sg", "SGD", Decimal("100"), "asset", day,
        "manual", "2026-01-01", Decimal("60"), day,
    ),), "INR", day)


def test_history_uses_each_days_valuation_and_keeps_decimal_precision():
    reader = create_autospec(PortfolioStore, instance=True)
    reader.portfolio.side_effect = lambda day, currency: valued_portfolio(day)
    points = PortfolioHistory(reader).at_dates(
        (DAY + timedelta(days=offset) for offset in range(3)), "INR",
    )
    assert tuple(point.as_of for point in points) == tuple(DAY + timedelta(days=day_offset) for day_offset in range(3))
    assert all(point.net_worth == Decimal("6000") for point in points)
    assert all(isinstance(point.net_worth, Decimal) for point in points)
    assert reader.portfolio.call_count == 3
    assert all(call.args[1] == "INR" for call in reader.portfolio.call_args_list)
    assert [call.args[0] for call in reader.portfolio.call_args_list] == [
        DAY + timedelta(days=day_offset) for day_offset in range(3)
    ]


def test_history_missing_valuation_raises_instead_of_omitting_point():
    reader = create_autospec(PortfolioStore, instance=True)
    reader.portfolio.return_value = Portfolio((), "INR", DAY)
    with pytest.raises(ValueError, match="unavailable for 2026-01-01"):
        PortfolioHistory(reader).at_dates((DAY,), "INR")
