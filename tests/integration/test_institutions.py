from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.statement_agent import TransformersStatementAgent
from src.documents.images import StatementPdf
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.institution import Institution
from src.models.portfolio.validation import institution_name
from src.repo.db import database_session, initialise
from src.repo.portfolio import PortfolioStore
from src.ui.presentation import PortfolioPresenter


APP = Path(__file__).resolve().parents[2] / "app.py"


def balance(institution, amount="100", alias="Savings"):
    return BalanceSnapshot(
        institution, alias, "INR", Decimal(amount), "asset", date.today(), "manual",
    )


@pytest.mark.parametrize("name", ["Example Credit Union", "Regional Broker", "新銀行"])
def test_any_institution_can_be_saved_and_displayed(tmp_path, name):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    assert store.institutions() == ()
    store.save([balance(name)])
    portfolio = PortfolioStore(path).portfolio(date.today())
    assert portfolio.net_worth == Decimal("100")
    assert portfolio.institutions() == (Institution.from_name(name),)
    presenter = PortfolioPresenter(portfolio)
    assert presenter.account_rows()[0]["Institution"] == name
    assert len(presenter.account_rows()) == 1
    assert portfolio.institutions()[0].country == ""


@pytest.mark.parametrize("name", [None, "", " ", "x" * 101, "bank\nname", "bank\x00"])
def test_invalid_institution_names_are_explicit_errors(name):
    with pytest.raises(ValueError, match="Institution name"):
        institution_name(name)


def test_names_normalize_without_losing_punctuation_or_unicode_identity(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    for name, amount in [("Example   Bank", "100"), ("  EXAMPLE Bank  ", "200"), ("Ｅxample Bank", "300")]:
        store.save([balance(name, amount)])
    assert len(store.institutions()) == 1
    assert store.institutions()[0].name == "Example Bank"
    assert len(store.balance_history(date.today())) == 1
    assert store.portfolio(date.today()).net_worth == Decimal("300")
    store.save([balance("Example-Bank", "50")])
    assert len(store.institutions()) == 2
    assert store.portfolio(date.today()).net_worth == Decimal("350")


def test_valid_names_with_expanding_casefold_keep_a_stable_identity(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    name = "ß" * 100
    store.save([balance(name)])
    assert store.institutions()[0].key == "ss" * 100
    assert store.institutions()[0].name == name
    assert store.portfolio(date.today()).net_worth == Decimal("100")
    initialise(path)
    store.save([balance(store.institutions()[0].key, "200")])
    assert store.portfolio(date.today()).net_worth == Decimal("200")


def test_names_and_legacy_identifiers_resolve_to_same_stable_account(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([balance("dbs_sg", "100")])
    store.save([
        balance("DBS Singapore", "200"),
        balance("Example Credit Union", "300", alias="Other"),
    ])
    portfolio = store.portfolio(date.today())
    assert portfolio.net_worth == Decimal("500")
    assert len(portfolio.accounts) == 2
    dbs = next(account for account in portfolio.accounts if account.account == "Savings")
    assert dbs.institution == "dbs_sg"
    assert dbs.institution_name == "DBS Singapore"
    assert dbs.country == "SG"
    assert dbs.balance == Decimal("200")


def test_duplicate_normalized_institutions_and_failed_imports_are_atomic(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    with pytest.raises(ValueError, match="Duplicate account/date"):
        store.save([balance("New Bank"), balance("NEW  BANK")])
    assert store.institutions() == ()
    assert store.balance_history(date.today()) == []
    with database_session(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM institutions WHERE normalized_name='new bank'"
        ).fetchone()[0] == 0


def test_late_account_conflict_rolls_back_new_institution_and_account(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([balance("Existing Bank")])
    conflicting = BalanceSnapshot(
        "Existing Bank", "Savings", "SGD", Decimal("20"), "asset", date.today(), "csv",
    )
    with pytest.raises(ValueError, match="currency or kind cannot change"):
        store.save([balance("New Institution"), conflicting])
    assert [record.name for record in store.institutions()] == ["Existing Bank"]
    assert len(store.balance_history(date.today())) == 1
    with database_session(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM institutions WHERE normalized_name='new institution'"
        ).fetchone()[0] == 0


def test_legacy_database_migration_preserves_account_and_observation_identity(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([balance("dbs_sg"), balance("Legacy Mutual", "200")])
    original_history = store.balance_history(date.today())
    with database_session(path) as connection:
        original_accounts = [tuple(row) for row in connection.execute("SELECT * FROM accounts")]
        connection.execute("DROP TABLE institutions")
    initialise(path)
    initialise(path)
    assert store.balance_history(date.today()) == original_history
    assert store.portfolio(date.today()).net_worth == Decimal("300")
    with database_session(path) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM accounts")] == original_accounts
    store.save([balance("DBS Singapore", "150"), balance("LEGACY MUTUAL", "250")])
    assert len(store.balance_history(date.today())) == 2
    assert store.portfolio(date.today()).net_worth == Decimal("400")


def test_migration_reports_legacy_name_collision_instead_of_hiding_accounts(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([balance("Example Bank")])
    with database_session(path) as connection:
        connection.execute("DROP TABLE institutions")
        connection.execute("UPDATE accounts SET institution='EXAMPLE BANK'")
        connection.execute(
            "INSERT INTO accounts (name,institution,country_code,account_type,currency,is_liability) "
            "VALUES ('Other','example bank','','other','INR',0)"
        )
    with pytest.raises(ValueError, match="normalized name conflicts"):
        initialise(path)
    with database_session(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM account_balances").fetchone()[0] == 1


def test_institutions_reflect_only_accounts_at_the_selected_valuation_date(tmp_path):
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    store.save([balance("Example Bank")])
    portfolio = store.portfolio(date(2026, 1, 1))
    assert portfolio.institutions() == ()
    assert PortfolioPresenter(portfolio).account_rows() == []
    assert [record.name for record in store.institutions()] == ["Example Bank"]


def statement_response():
    today = date.today().isoformat()
    return json.dumps({
        "institution": {"name": "Example Credit Union"},
        "account": {"number": "1234"},
        "balances": [{
            "balance": "125.50", "currency": "INR", "as_of": today,
            "balance_role": "closing_balance", "account_scope": "single_account",
            "date_role": "statement_date",
        }],
    })


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def run_review(app, institution):
    selector = by_label(app.selectbox, "Statement institution")
    assert selector.proto.accept_new_options
    # AppTest serializes only listed options, unlike the browser's free-text selectbox.
    if institution not in selector.options:
        selector.options.append(institution)
    return app.run()


@pytest.mark.parametrize("selected_name", ["Existing Mutual", "Corrected Credit Union"])
def test_new_statement_issuer_can_be_corrected_and_confirmation_is_rebound(
    tmp_path, monkeypatch, selected_name,
):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"page image",))
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("Example Credit Union",))
    runtime = Mock()
    runtime.generate.return_value = statement_response()
    monkeypatch.setattr(
        TransformersStatementAgent, "from_environment",
        classmethod(lambda agent_type, **options: TransformersStatementAgent(runtime)),
    )
    monkeypatch.setattr(
        TransformersStatementAgent, "from_text_environment",
        classmethod(lambda agent_type, **options: TransformersStatementAgent(runtime)),
    )
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    app = AppTest.from_file(str(APP)).run()
    store.save([balance("Existing Mutual", alias="Original account")])
    by_label(app.file_uploader, "Statement files (PDF, up to 10 MB each)").set_value(
        ("statement.pdf", b"PDF content", "application/pdf"),
    ).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert by_label(app.selectbox, "Statement institution").value == "Example Credit Union"
    assert by_label(app.text_input, "Account alias").value == "Example"
    by_label(app.checkbox, "I reviewed every account and currency balance and want to save them.").set_value(True).run()
    by_label(app.selectbox, "Statement institution").set_value(selected_name)
    run_review(app, selected_name)
    assert by_label(app.button, "Save balances").disabled
    by_label(app.checkbox, "I reviewed every account and currency balance and want to save them.").set_value(True)
    run_review(app, selected_name)
    by_label(app.button, "Save balances").click()
    run_review(app, selected_name)
    assert not app.exception
    saved = next(account for account in store.portfolio(date.today()).accounts if account.source == "statement")
    assert saved.institution_name == selected_name
    assert saved.balance == Decimal("125.50")
    assert len(store.institutions()) == (1 if selected_name == "Existing Mutual" else 2)
