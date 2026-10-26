from datetime import date, timedelta
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.statement_agent import TransformersStatementAgent
from tests.statement_fixtures import statement_extraction
from src.documents.images import StatementPdf
from src.documents.images import (
    IncorrectStatementPasswordError, StatementPasswordRequiredError,
)
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.institution import Institution
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution
from src.providers.exchange_rates import (
    ExchangeRateFetchError, FrankfurterExchangeRateProvider,
)
from src.repo.db import initialise
from src.repo.portfolio import PortfolioStore
from src.service.entry import EntryServices
from src.service.portfolio import PortfolioActions


APP = Path(__file__).resolve().parents[2] / "app.py"
CONFIRMATION = "I reviewed every account and currency balance and want to save them."
BATCH_CONFIRMATION = "I reviewed all remaining parsed statements and want to save their balances."


@pytest.fixture(autouse=True)
def automatic_fx(monkeypatch):
    def fetch(provider: FrankfurterExchangeRateProvider, currencies: set[str], as_of: date):
        return tuple(
            ExchangeRateObservation(currency, Decimal("60"), as_of)
            for currency in sorted(currencies)
        )

    monkeypatch.setattr(FrankfurterExchangeRateProvider, "fetch", fetch)


def by_label(elements, label):
    return next(item for item in elements if item.label == label)


def save_valuation(app, name="Gold", amount="100", currency="SGD", kind="asset", as_of=None):
    by_label(app.button, "Manual valuation").click().run()
    by_label(app.text_input, "Asset or debt name").set_value(name)
    by_label(app.text_input, "Total value").set_value(amount)
    by_label(app.selectbox, "Valuation currency").set_value(currency)
    by_label(app.selectbox, "Valuation kind").set_value(kind)
    if as_of is not None:
        by_label(app.date_input, "Value as of").set_value(as_of)
    by_label(app.button, "Save valuation").click().run()


def test_minimal_navigation_has_no_mode_selector(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Data entry", "Portfolio overview"]
    assert any("No recorded wealth" in item.value for item in app.info)
    assert [button.label for button in app.button[:2]] == ["Parse statement", "Manual valuation"]
    assert by_label(app.button, "Parse statement").proto.type == "primary"
    assert by_label(app.button, "Manual valuation").proto.type == "secondary"
    assert any(".st-key-wealth_card_selected" in item.value for item in app.get("html"))
    assert not any("transaction" in button.label.lower() for button in app.button)
    assert not any(button.label in {"API sync", "Manual import"} for button in app.button)
    assert not app.get("download_button")
    assert app.file_uploader[0].proto.max_upload_size_mb == 10
    assert not app.sidebar.radio
    assert not app.metric


def test_workflow_tiles_keep_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    by_label(app.button, "Manual valuation").click().run()
    assert not app.exception
    assert by_label(app.button, "Manual valuation").proto.type == "primary"
    assert not app.file_uploader
    app.run()
    assert by_label(app.button, "Manual valuation").proto.type == "primary"
    by_label(app.button, "Parse statement").click().run()
    assert app.file_uploader
    assert not any(item.label == "Asset or debt name" for item in app.text_input)


def test_batch_review_preserves_edits_and_saves_only_current_statement(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    calls = []

    def preview(services, filename, content, *, log_model_output):
        calls.append(filename)
        extraction = statement_extraction()
        return replace(
            extraction,
            accounts=(replace(extraction.accounts[0], number=filename + "1234"),),
        )

    monkeypatch.setattr(EntryServices, "preview", preview)
    monkeypatch.setattr(
        PortfolioActions, "institutions", lambda actions: (Institution.from_name("First Bank"),),
    )
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value([
        ("first.pdf", b"first", "application/pdf"),
        ("second.pdf", b"second", "application/pdf"),
    ]).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert calls == ["first.pdf", "second.pdf"]
    assert by_label(app.button, "Back").disabled
    by_label(app.text_input, "Account alias").set_value("First account").run()
    by_label(app.text_input, "Account type").set_value("Savings").run()
    by_label(app.selectbox, "Statement institution").set_value("First Bank").run()
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Next").click().run()
    assert not app.exception
    assert by_label(app.button, "Next").disabled
    assert by_label(app.text_input, "Account alias").value == "DBS"
    assert by_label(app.text_input, "Account type").value == ""
    assert not by_label(app.checkbox, CONFIRMATION).value
    by_label(app.text_input, "Account alias").set_value("Second account").run()
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    assert not store.balance_history(date.today())
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert {row["account"] for row in store.balance_history(date.today())} == {"Second account SGD"}
    assert len(app.file_uploader[0].value) == 2
    assert not any(button.label == "Save balances" for button in app.button)
    by_label(app.button, "Back").click().run()
    assert by_label(app.text_input, "Account alias").value == "First account"
    assert by_label(app.text_input, "Account type").value == "Savings"
    assert by_label(app.selectbox, "Statement institution").value == "First Bank"
    assert by_label(app.checkbox, CONFIRMATION).value
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert len(store.balance_history(date.today())) == 2
    assert calls == ["first.pdf", "second.pdf"]
    assert app.file_uploader[0].value == []
    app.run()
    assert app.file_uploader[0].value == []
    assert not any(button.label == "Save balances" for button in app.button)


def test_batch_failure_and_upload_changes_do_not_leak_review(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))

    def preview(services, filename, content, *, log_model_output):
        if filename == "bad.pdf":
            raise ValueError("Unable to read this PDF statement.")
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value([
        ("bad.pdf", b"bad", "application/pdf"),
        ("good.pdf", b"good", "application/pdf"),
    ]).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert any("Unable to read" in error.value for error in app.error)
    by_label(app.button, "Next").click().run()
    assert any(button.label == "Save balances" for button in app.button)
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    app.file_uploader[0].set_value([("changed.pdf", b"changed", "application/pdf")]).run()
    assert not app.exception
    assert not any(button.label == "Save balances" for button in app.button)
    assert not PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())


def test_protected_pdf_password_is_requested_only_after_detection_and_cleared(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    attempted_passwords = []

    def preview(services, filename, content, *, log_model_output, password=None):
        if password is None:
            raise StatementPasswordRequiredError("This PDF requires an opening password.")
        attempted_passwords.append(password)
        if password != "correct horse":
            raise IncorrectStatementPasswordError(
                "The password was incorrect, or this encrypted PDF could not be opened."
            )
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = AppTest.from_file(str(APP)).run()
    assert not any(item.label == "PDF opening password" for item in app.text_input)
    app.file_uploader[0].set_value([
        ("protected.pdf", b"protected PDF", "application/pdf"),
    ]).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    password_input = by_label(app.text_input, "PDF opening password")

    password_input.set_value("incorrect")
    by_label(app.button, "Unlock and extract").click().run()
    assert not app.exception
    assert "password was incorrect" in app.error[0].value
    assert "incorrect" not in app.session_state.values()
    assert by_label(app.text_input, "PDF opening password").value == ""

    by_label(app.text_input, "PDF opening password").set_value("correct horse")
    by_label(app.button, "Unlock and extract").click().run()
    assert not app.exception
    assert attempted_passwords == ["incorrect", "correct horse"]
    assert "correct horse" not in app.session_state.values()
    assert any(item.label == "Account alias" for item in app.text_input)


def test_save_all_uses_edits_resets_confirmation_and_skips_failed_files(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))

    def preview(services, filename, content, *, log_model_output):
        if filename == "bad.pdf":
            raise ValueError("Invalid PDF")
        extraction = statement_extraction()
        return replace(
            extraction,
            accounts=(replace(extraction.accounts[0], number=filename + "1234"),),
        )

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value([
        ("first.pdf", b"first", "application/pdf"),
        ("second.pdf", b"second", "application/pdf"),
        ("bad.pdf", b"bad", "application/pdf"),
    ]).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert by_label(app.button, "Back").proto.icon
    assert by_label(app.button, "Next").proto.type == "primary"
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account alias").set_value("First edited").run()
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.button, "Next").click().run()
    by_label(app.text_input, "Account alias").set_value("Second edited").run()
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account type").set_value("Fixed deposit").run()
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save all balances").click().run()
    assert not app.exception
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    assert {row["account"] for row in store.balance_history(date.today())} == {
        "First edited SGD", "Second edited SGD",
    }
    assert {
        row["product_type"] for row in store.balance_history(date.today())
        if row["account"] == "Second edited SGD"
    } == {"Fixed deposit"}
    assert app.success[0].value == "Saved 2 currency balances from 2 statements."
    assert app.file_uploader[0].value == []
    assert not any(button.label == "Save all balances" for button in app.button)
    app.run()
    assert app.file_uploader[0].value == []
    assert len(store.balance_history(date.today())) == 2


def test_bulk_save_conflict_rolls_back_and_preserves_pending_previews(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        EntryServices, "preview",
        lambda services, filename, content, **options: statement_extraction(),
    )
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value([
        ("first.pdf", b"first", "application/pdf"),
        ("duplicate.pdf", b"duplicate", "application/pdf"),
    ]).run()
    by_label(app.button, "Extract balances").click().run()
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save all balances").click().run()
    assert not app.exception
    assert any("Duplicate account/date" in error.value for error in app.error)
    assert len(app.file_uploader[0].value) == 2
    assert not PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())
    assert not by_label(app.button, "Save all balances").disabled
    by_label(app.button, "Next").click().run()
    assert any(button.label == "Save balances" for button in app.button)


@pytest.mark.parametrize("currencies", [("SGD",), ("SGD", "THB")])
@pytest.mark.parametrize("needs_review", [False, True])
def test_statement_review_confirmation_and_persistence(
    tmp_path, monkeypatch, currencies, needs_review,
):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"image",))
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("Fictional text",))

    class FakeAgent:
        @staticmethod
        def parse(document):
            assert document.text_only
            balances = tuple(
                StatementBalance(
                    Decimal("1234.50"), currency, date.today(),
                    "opening_balance" if needs_review else "closing_balance",
                    "unknown" if needs_review else "single_account", "statement_date",
                ) for currency in currencies
            )
            return StatementExtraction(
                (StatementAccount("1234", balances),),
                StatementInstitution("Example Bank"),
            )

    monkeypatch.setattr(
        TransformersStatementAgent, "from_environment",
        classmethod(lambda agent_type, **options: FakeAgent()),
    )
    monkeypatch.setattr(
        TransformersStatementAgent, "from_text_environment",
        classmethod(lambda agent_type, **options: FakeAgent()),
    )
    app = AppTest.from_file(str(APP)).run()
    assert not any(item.label == "Statement model" for item in app.selectbox)
    app.file_uploader[0].set_value(("statement.pdf", b"fictional", "application/pdf")).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert any("not independently verified" in item.value for item in app.warning)
    assert not any("evidence" in item.value.lower() for item in app.caption)
    assert any("double-counting" in item.value for item in app.warning) == needs_review
    card = app.get_by_key("statement_review_account_1")
    assert [item.label for item in card.text_input] == ["Account type", "Account alias"]
    assert [item.label for item in card.button] == ["Save balances"]
    assert card.table[0].value.to_dict("records") == [
        {"Currency": currency, "Balance": "1,234.50"} for currency in currencies
    ]
    assert [item.label for item in card.expander] == ["AI interpretation"]
    assert sum(
        "Statement date:" in item.value for item in card.caption
    ) == 1
    assert by_label(app.text_input, "Account alias").value == "Example"
    assert by_label(app.button, "Save balances").disabled
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    assert not store.balance_history(date.today())
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account alias").set_value("Savings").run()
    assert by_label(app.button, "Save balances").disabled
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert app.success[0].value == f"Saved {len(currencies)} statement currency balances."
    assert {row["account"] for row in store.balance_history(date.today())} == {
        f"Savings {currency}" for currency in currencies
    }


def test_multi_account_statement_reviews_and_saves_fixed_deposit_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    extraction = statement_extraction()
    savings = extraction.accounts[0]
    fixed_deposit_balance = replace(
        savings.balances[0],
        balance=Decimal("50000.00"),
    )
    multi_account = StatementExtraction(
        (
            savings,
            StatementAccount(
                "****5678", (fixed_deposit_balance,), account_type="Savings",
            ),
        ),
        extraction.institution,
    )
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: multi_account)
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value(("statement.pdf", b"fictional", "application/pdf")).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert by_label(app.text_input, "Account alias").value == "DBS 1"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account alias").value == "DBS Savings 2"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").value == "Savings"
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").set_value(
        "Fixed deposit",
    ).run()
    assert by_label(
        app.get_by_key("statement_review_account_2").text_input, "Account alias",
    ).value == "DBS Fixed deposit 2"
    first_card = app.get_by_key("statement_review_account_1")
    second_card = app.get_by_key("statement_review_account_2")
    assert [item.label for item in first_card.button] == ["Save account 1 balances"]
    assert [item.label for item in second_card.button] == ["Save account 2 balances"]
    assert first_card.table[0].value.to_dict("records") == [
        {"Currency": "SGD", "Balance": "1,234.50"},
    ]
    assert second_card.table[0].value.to_dict("records") == [
        {"Currency": "SGD", "Balance": "50,000.00"},
    ]
    assert sum("not independently verified" in item.value for item in app.warning) == 1
    assert not first_card.warning
    assert not second_card.warning
    by_label(app.text_input, "Account alias").set_value("Savings").run()
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account alias").set_value("Fixed deposit").run()
    by_label(app.checkbox, "I reviewed account 2 and want to save its balances.").set_value(True).run()
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").set_value("Term deposit").run()
    assert by_label(app.button, "Save account 2 balances").disabled
    by_label(app.checkbox, "I reviewed account 1 and want to save its balances.").set_value(True).run()
    by_label(app.button, "Save account 1 balances").click().run()
    assert not app.exception
    rows = PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())
    assert [(row["account"], row["account_number"]) for row in rows] == [
        ("Savings SGD", "TEST1234"),
    ]
    saved_card = app.get_by_key("statement_review_account_1")
    assert all(item.disabled for item in saved_card.text_input)
    assert not saved_card.checkbox
    assert not saved_card.button
    assert any(item.value == "Saved" for item in saved_card.caption)
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account alias").value == "Fixed deposit"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").value == "Term deposit"
    assert by_label(app.button, "Save account 2 balances").disabled
    by_label(app.checkbox, "I reviewed account 2 and want to save its balances.").set_value(True).run()
    by_label(app.button, "Save account 2 balances").click().run()

    rows = PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())
    assert {(row["account"], row["account_number"], row["balance"]) for row in rows} == {
        ("Savings SGD", "TEST1234", "1234.50"),
        ("Fixed deposit SGD", "****5678", "50000.00"),
    }
    assert {row["product_type"] for row in rows if row["account_number"] == "****5678"} == {
        "Term deposit",
    }
    restarted = AppTest.from_file(str(APP)).run()
    assert not restarted.exception
    assert any(
        "Account type" in grid.value.columns
        and "Term deposit" in grid.value["Account type"].values
        for grid in restarted.dataframe
    )


def test_manual_assets_debts_fx_replacement_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    earlier = date.today() - timedelta(days=30)
    save_valuation(app, name="Gold", amount="100", as_of=earlier)
    save_valuation(app, name="Gold", amount="125", as_of=date.today())
    save_valuation(app, name="Home", amount="100000", currency="INR")
    save_valuation(app, name="Mortgage", amount="20000", currency="INR", kind="liability")
    assert not app.exception
    assert app.metric[0].value == "87,500.00"
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    assert len(store.balance_history(date.today())) == 4
    save_valuation(app, name="Gold", amount="150", as_of=date.today())
    assert len(store.balance_history(date.today())) == 4
    assert app.metric[0].value == "89,000.00"
    assert app.get("vega_lite_chart")
    restarted = AppTest.from_file(str(APP)).run()
    assert restarted.metric[0].value == "89,000.00"
    by_label(restarted.sidebar.date_input, "Valuation date").set_value(earlier).run()
    assert restarted.metric[0].value == "6,000.00"
    by_label(restarted.sidebar.selectbox, "Display currency").set_value("SGD").run()
    assert restarted.metric[0].value == "100.00"


@pytest.mark.parametrize("amount,kind,message", [
    ("NaN", "asset", "finite"),
    ("-10", "liability", "positive"),
    ("", "asset", "required"),
])
def test_invalid_manual_valuation_never_saves(tmp_path, monkeypatch, amount, kind, message):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    save_valuation(app, amount=amount, kind=kind)
    assert not app.exception
    assert any(message in error.value for error in app.error)
    assert not PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())


def test_inr_portfolio_displays_crore_grouping_without_changing_saved_amount(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    save_valuation(app, name="Home", amount="12345678.906", currency="INR")
    assert not app.exception
    assert app.metric[0].value == "1,23,45,678.91"
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    assert store.balance_history(date.today())[0]["balance"] == "12345678.906"
    assert app.get("vega_lite_chart")


def test_zero_value_retires_asset_and_foreign_currency_is_supported(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run()
    save_valuation(app, name="Overseas home", currency="USD", amount="500")
    assert app.metric[0].value == "30,000.00"
    save_valuation(app, name="Overseas home", currency="USD", amount="0")
    assert app.metric[0].value == "0.00"
    save_valuation(app, name="Overseas home", currency="EUR", amount="500")
    assert any("currency or kind cannot change" in item.value for item in app.error)


def test_statement_failure_is_visible_without_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))

    def unavailable(agent_type, **options):
        raise ValueError("Local model files are missing.")

    monkeypatch.setattr(TransformersStatementAgent, "from_environment", classmethod(unavailable))
    app = AppTest.from_file(str(APP)).run()
    app.file_uploader[0].set_value(("statement.pdf", b"fictional", "application/pdf")).run()
    by_label(app.button, "Extract balances").click().run()
    assert not app.exception
    assert any("Local model files" in item.value for item in app.error)
    assert not PortfolioStore(tmp_path / "portfolio.sqlite3").balance_history(date.today())


def test_stale_observations_and_fx_failure_are_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))

    def fail_fetch(provider, currencies, as_of):
        raise ExchangeRateFetchError("Automatic FX refresh failed: offline.")

    monkeypatch.setattr(FrankfurterExchangeRateProvider, "fetch", fail_fetch)
    path = tmp_path / "portfolio.sqlite3"
    initialise(path)
    store = PortfolioStore(path)
    stale = date.today() - timedelta(days=31)
    store.save([BalanceSnapshot("Bank", "Savings", "SGD", Decimal("100"), "asset", stale, "manual")])
    app = AppTest.from_file(str(APP)).run()
    assert not app.metric
    assert any("missing dated FX" in item.value for item in app.error)
    store.save_rate("SGD", "60", stale)
    app.run()
    assert not app.exception
    assert app.metric[0].value == "6,000.00"
    assert any("Balances more than 30 days old" in item.value for item in app.warning)
    assert any("FX rates more than 30 days old" in item.value for item in app.warning)
