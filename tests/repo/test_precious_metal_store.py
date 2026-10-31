from datetime import date
from decimal import Decimal

from src.models.entry.precious_metal_valuation import PreciousMetalValuation
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.repo.db import connect
from tests.metal_fixtures import gold_holding, gold_price

DAY = date(2026, 1, 10)
GROUP = "Precious metals"


def valuation(quantity="10.5", **changes):
    return PreciousMetalValuation(GROUP, "Gold", gold_holding(quantity, **changes), DAY)


def table_count(db_path, table):
    with connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def account(store):
    return store.portfolio(DAY, "INR").accounts[0]


def test_saved_holding_is_read_back_with_its_rate(store):
    store.save_precious_metal_valuation(valuation())
    saved = account(store)
    assert saved.balance == Decimal("126000.00")
    assert saved.precious_metal == gold_holding("10.5")


def test_resaving_the_same_day_updates_the_holding_and_reuses_the_price(store, db_path):
    store.save_precious_metal_valuation(valuation())
    store.save_precious_metal_valuation(valuation("2"))
    assert account(store).precious_metal.quantity == Decimal("2")
    assert table_count(db_path, "precious_metal_prices") == 1
    assert table_count(db_path, "precious_metal_valuations") == 1


def test_plain_value_overwrite_drops_the_stale_metal_link(store, db_path):
    store.save_precious_metal_valuation(valuation())
    store.save([BalanceSnapshot(GROUP, "Gold", "INR", Decimal("5000"), "asset", DAY, "manual")])
    saved = account(store)
    assert saved.balance == Decimal("5000")
    assert saved.precious_metal is None
    assert table_count(db_path, "precious_metal_valuations") == 0


def test_price_observations_are_stored_once_per_source_and_time(store, db_path):
    prices = (gold_price("24K"), gold_price("22K"))
    store.save_precious_metal_prices(prices)
    store.save_precious_metal_prices(prices)
    assert table_count(db_path, "precious_metal_prices") == 2
