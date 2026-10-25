from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config
from src.documents.reader import StatementDocumentReader
from src.documents.images import StatementPdf
from src.inference.transformers_runtime import TransformersRuntimeConfig
from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.portfolio import Portfolio
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.repo.db import initialise
from src.repo.portfolio import PortfolioStore
from src.ui.presentation import money, PortfolioPresenter


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_app_branding():
    assert config.PAGE_TITLE == "BarelyRich"
    assert config.APP_TITLE == "BarelyRich"


def test_data_directory_resolves_defaults_and_environment_each_time(tmp_path, monkeypatch):
    monkeypatch.delenv("WT_DATA_DIR", raising=False)
    assert config.data_directory() == APP.parent / "data"
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    assert config.data_directory() == tmp_path
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path / "another"))
    assert config.data_directory() == tmp_path / "another"


def test_configured_display_currency_is_supported_by_repository(tmp_path, monkeypatch):
    path = tmp_path / config.PORTFOLIO_DATABASE
    initialise(path)
    store = PortfolioStore(path)
    today = date.today()
    store.save([BalanceSnapshot(
        "dbs_sg", "Savings", "SGD", Decimal("100"), "asset", today, "manual",
    )])
    store.save_rate("SGD", "60", today)
    store.save_rate("USD", "80", today)
    with pytest.raises(ValueError, match="Display currency"):
        store.portfolio(today, "USD")

    monkeypatch.setattr(config, "DISPLAY_CURRENCIES", ("INR", "SGD", "USD"))
    monkeypatch.setattr(config, "DEFAULT_DISPLAY_CURRENCY", "USD")
    portfolio = store.portfolio(today)
    assert portfolio.base_currency == "USD"
    assert portfolio.net_worth == Decimal("75")
    assert store.portfolio(today, "INR").net_worth == Decimal("6000")
    with pytest.raises(ValueError, match="INR or SGD or USD"):
        store.portfolio(today, "EUR")


def test_ui_uses_configured_currencies_and_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DISPLAY_CURRENCIES", ("INR", "SGD", "USD"))
    monkeypatch.setattr(config, "DEFAULT_DISPLAY_CURRENCY", "SGD")
    monkeypatch.setattr(config, "PORTFOLIO_DATABASE", "custom.sqlite3")
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "BarelyRich"
    assert app.sidebar.selectbox[0].options == ["INR", "SGD", "USD"]
    assert app.sidebar.selectbox[0].value == "SGD"
    app.sidebar.selectbox[0].set_value("USD").run()
    assert not app.exception
    assert app.sidebar.selectbox[0].value == "USD"
    assert (tmp_path / "custom.sqlite3").exists()
    assert len(list(tmp_path.glob("*.sqlite3"))) == 1


def test_staleness_and_money_use_shared_settings(monkeypatch):
    monkeypatch.setattr(config, "STALE_AFTER_DAYS", 2)
    monkeypatch.setattr(config, "MONEY_DECIMAL_PLACES", 3)
    today = date.today()
    account = AccountValue(
        "Savings", "dbs_sg", "SGD", Decimal("100"), "asset",
        today - timedelta(days=3), "manual", "", Decimal("60"),
        today - timedelta(days=3),
    )
    presenter = PortfolioPresenter(Portfolio((account,), "INR", today))
    assert account.is_stale(today)
    assert presenter.stale_accounts() == ("Savings",)
    assert presenter.stale_currencies() == ("SGD",)
    assert presenter.stale_accounts(days=3) == ()
    assert money(Decimal("1234.5678")) == "1,234.568"
    assert money(None) is None


def test_statement_size_limit_uses_config(monkeypatch):
    monkeypatch.setattr(config, "MAX_STATEMENT_BYTES", 3)
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"page image",))
    assert StatementDocumentReader().read("statement.pdf", b"abc").page(1).image == b"page image"
    with pytest.raises(ValueError, match="3e-06 MB"):
        StatementDocumentReader().read("statement.pdf", b"abcd")


def test_image_limit_is_shared_with_domain_validation(monkeypatch):
    monkeypatch.setattr(config, "MAX_RENDERED_IMAGE_BYTES", 3)
    page = StatementPage(1, b"abc")
    assert StatementDocument((page,))
    with pytest.raises(ValueError, match="image bytes"):
        StatementPage(1, b"abcd")


def test_runtime_defaults_and_upload_limit_come_from_config():
    runtime = TransformersRuntimeConfig()
    assert runtime.model_name == config.DEFAULT_TRANSFORMERS_MODEL
    assert runtime.device == config.DEFAULT_TRANSFORMERS_DEVICE
    assert runtime.max_new_tokens == config.DEFAULT_MAX_NEW_TOKENS
    assert runtime.max_input_tokens == config.DEFAULT_MAX_INPUT_TOKENS
    assert runtime.max_image_pixels == config.DEFAULT_MAX_IMAGE_PIXELS
    assert runtime.max_time_seconds == config.DEFAULT_MAX_TIME_SECONDS
    assert config.STATEMENT_UPLOAD_MB == 10
    assert config.STATEMENT_UPLOAD_MB * 1024**2 >= config.MAX_STATEMENT_BYTES
