import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from time import perf_counter
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.delta_generator import DeltaGenerator
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
from streamlit.runtime.scriptrunner_utils.script_run_context import ThreadState
from streamlit.testing.v1 import AppTest

from src import config
from src.agents.statement_agent import StatementAgent
from src.inference.cancellation import ExtractionCancelled
from src.inference.ollama_runtime import OllamaRuntimeError
from src.inference.progress import GenerationProgress, current_progress, report_stage
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.institution import Institution
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution
from src.providers.exchange_rates import (
    ExchangeRateFetchError,
    FrankfurterExchangeRateProvider,
)
from src.readers.statement_pdf import (
    IncorrectStatementPasswordError,
    StatementPasswordRequiredError,
    StatementPdf,
)
from src.repo.portfolio import PortfolioStore
from src.service.entry_services import EntryServices
from src.service.portfolio import PortfolioActions
from src.ui.statement_edit import _pending_rows
from tests.statement_fixtures import statement_extraction

APP = Path(__file__).resolve().parents[2] / "app.py"
CONFIRMATION = "I reviewed every account, transaction and currency balance and want to save them."
BATCH_CONFIRMATION = "I reviewed all remaining parsed statements and want to save their transactions and balances."


def test_conflicting_currency_summaries_open_review_with_warning(monkeypatch):
    extraction = statement_extraction()
    account = extraction.accounts[0]
    original = replace(
        account.balances[0], currency="EUR", balance=Decimal("11.01"),
        withdrawal=None, deposit=None,
    )
    conflicting = replace(original, balance=Decimal("16.05"))
    extraction = replace(
        extraction, accounts=(replace(account, balances=(original, conflicting)),),
    )
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: extraction)
    app = start_app()
    extract(app, "statement.pdf")
    assert not app.exception
    card = app.get_by_key("statement_review_account_1")
    assert any("Conflicting balance summaries" in warning.value for warning in card.warning)
    assert len(card.table[0].value) == 2


@pytest.fixture(autouse=True)
def automatic_fx(monkeypatch):
    def fetch(provider: FrankfurterExchangeRateProvider, currencies: set[str], as_of: date):
        return tuple(
            ExchangeRateObservation(currency, Decimal("60"), as_of)
            for currency in sorted(currencies)
        )

    monkeypatch.setattr(FrankfurterExchangeRateProvider, "fetch", fetch)
    monkeypatch.setattr(
        "src.ui.forms._installed_ollama_models",
        lambda: ("qwen3:4b-instruct", "qwen3:1.7b"),
    )


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    return tmp_path


def start_app():
    return AppTest.from_file(str(APP)).run()


def upload(app, *names):
    files = [(name, Path(name).stem.encode(), "application/pdf") for name in names]
    return app.file_uploader[0].set_value(files).run()


def extract(app, *names, **run):
    upload(app, *names)
    return by_label(app.button, "Extract balances").click().run(**run)


def open_review(app, *names):
    extract(app, *names)
    return by_label(app.button, "Edit extracted rows").click().run()


def app_store(tmp_path):
    return PortfolioStore(tmp_path / config.PORTFOLIO_DATABASE)


def saved_history(tmp_path):
    return app_store(tmp_path).balance_history(date.today())


def extraction_for(filename):
    extraction = statement_extraction()
    account = replace(extraction.accounts[0], number=filename + "1234")
    return replace(extraction, accounts=(account,))

def by_label(elements, label):
    return next(item for item in elements if item.label == label)


def review_editor(app):
    return next(
        item for item in app.dataframe if "statement_editor_" in item.proto.id
    )


def review_event(app, *, edits=None, added=(), deleted=()):
    editor = review_editor(app)
    key = editor.proto.id.split("-", 2)[2]
    data = app.session_state[key]
    data = {
        "edited_rows": {index: dict(values) for index, values in data["edited_rows"].items()},
        "added_rows": [dict(row) for row in data["added_rows"]],
        "deleted_rows": list(data["deleted_rows"]),
    }
    count = len(app.session_state[key.removesuffix("_native") + "_data"])
    for index, values in (edits or {}).items():
        if index < count:
            data["edited_rows"].setdefault(index, {}).update(values)
        else:
            data["added_rows"][index - count].update(values)
    data["added_rows"].extend(added)
    data["deleted_rows"].extend(deleted)
    states = WidgetStates()
    widget = states.widgets.add(id=editor.proto.id)
    widget.string_value = json.dumps(data)
    return app._run(states)


def test_stop_extraction_skips_remaining_files(tmp_path, monkeypatch):
    calls = []

    def preview(*args, **kwargs):
        calls.append(True)
        report_stage("Generating")
        return statement_extraction()

    original = DeltaGenerator.button

    def stop_button(self, label, *args, **kwargs):
        if label == "Stop extraction":
            kwargs["on_click"]()
        return original(self, label, *args, **kwargs)

    monkeypatch.setattr(EntryServices, "preview", preview)
    monkeypatch.setattr(DeltaGenerator, "button", stop_button)
    app = start_app()
    extract(app, "one.pdf", "two.pdf")
    assert not app.exception
    assert len(calls) == 1
    assert any("Extraction stopped" in item.value for item in app.warning)
    assert not any(button.label == "Save balances" for button in app.button)
    assert not saved_history(tmp_path)
    assert not any(button.label == "Reset" for button in app.button)


def test_removing_uploads_discards_completed_review_but_preserves_saved_data(tmp_path, monkeypatch):
    monkeypatch.setattr(
        EntryServices, "preview",
        lambda *arguments, **keywords: statement_extraction(),
    )
    app = start_app()
    save_valuation(app)
    by_label(app.button, "Parse statement").click().run()
    extract(app, "one.pdf")
    assert not app.exception
    assert any(button.label == "Edit extracted rows" for button in app.button)
    app.file_uploader[0].set_value([]).run()
    assert not app.exception
    assert not app.file_uploader[0].value
    assert not any(button.label == "Edit extracted rows" for button in app.button)
    saved = saved_history(tmp_path)
    assert len(saved) == 1


@pytest.mark.parametrize("cooperative", [True, False])
def test_live_click_interrupts_running_extraction(tmp_path, monkeypatch, cooperative):
    running = Event()
    stopped = Event()
    clicked = Event()

    def preview(*args, **kwargs):
        progress = current_progress()
        assert progress
        running.set()
        try:
            deadline = perf_counter() + 3
            while perf_counter() < deadline:
                if cooperative:
                    progress.cancellation.check()
                else:
                    try:
                        progress.cancellation.check()
                    except ExtractionCancelled:
                        # A blocked stage need not exit for the UI to stop waiting.
                        stopped.set()
                        Event().wait(0.5)
                        return statement_extraction()
                Event().wait(0.01)
            raise AssertionError("Click was deferred until model completion")
        except ExtractionCancelled:
            stopped.set()
            raise

    original_text = DeltaGenerator.text

    def click_during_progress(self, body, *args, **kwargs):
        if running.is_set() and not clicked.is_set():
            clicked.set()
            ctx = get_script_run_ctx()
            key = "stop_statement_extraction_"
            widget_id = next(item.id for item in ctx.session_state.get_widget_states() if key in item.id)
            states = WidgetStates()
            states.widgets.add(id=widget_id, trigger_value=True)
            ctx.script_requests.request_rerun(RerunData(
                widget_states=states, fragment_id=ThreadState.get().fragment_id,
            ))
        return original_text(self, body, *args, **kwargs)

    monkeypatch.setattr(EntryServices, "preview", preview)
    monkeypatch.setattr(DeltaGenerator, "text", click_during_progress)
    app = start_app()
    extract(app, "one.pdf", timeout=6)
    assert not app.exception
    assert clicked.is_set()
    assert stopped.wait(1)
    assert not any(button.label == "Save balances" for button in app.button)
    assert not saved_history(tmp_path)
    assert any("Extraction stopped" in item.value for item in app.error)


def save_valuation(app, name="Gold", amount="100", currency="SGD", kind="asset", as_of=None):
    by_label(app.button, "Manual valuation").click().run()
    by_label(app.text_input, "Asset or debt name").set_value(name)
    by_label(app.text_input, "Total value").set_value(amount)
    by_label(app.selectbox, "Valuation currency").set_value(currency)
    by_label(app.selectbox, "Valuation kind").set_value(kind)
    if as_of:
        by_label(app.date_input, "Value as of").set_value(as_of)
    by_label(app.button, "Save valuation").click().run()


def test_minimal_navigation_has_no_mode_selector():
    app = start_app()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Data entry", "Portfolio overview"]
    assert any("No recorded wealth" in item.value for item in app.info)
    assert [button.label for button in app.button[:2]] == ["Parse statement", "Manual valuation"]
    assert by_label(app.button, "Parse statement").proto.type == "primary"
    assert by_label(app.button, "Manual valuation").proto.type == "primary"
    assert any(".st-key-wealth_card_selected" in item.value for item in app.get("html"))
    assert not any("transaction" in button.label.lower() for button in app.button)
    assert not any(button.label in {"API sync", "Manual import"} for button in app.button)
    assert not app.get("download_button")
    assert app.file_uploader[0].proto.max_upload_size_mb == 10
    assert not app.sidebar.radio
    assert not app.metric


def test_workflow_tiles_keep_selection():
    app = start_app()
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
    calls = []

    def preview(services, filename, content, *, log_model_output):
        calls.append(filename)
        return extraction_for(filename)

    monkeypatch.setattr(EntryServices, "preview", preview)
    monkeypatch.setattr(
        PortfolioActions, "institutions", lambda actions: (Institution.from_name("First Bank"),),
    )
    app = start_app()
    extract(app, "first.pdf", "second.pdf")
    assert not app.exception
    assert calls == ["first.pdf", "second.pdf"]
    assert by_label(app.button, "Back").disabled
    by_label(app.text_input, "Account name").set_value("First account").run()
    by_label(app.text_input, "Account type").set_value("Savings").run()
    by_label(app.selectbox, "Statement institution").set_value("First Bank").run()
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Next").click().run()
    assert not app.exception
    assert by_label(app.button, "Next").disabled
    assert by_label(app.text_input, "Account name").value == "DBS"
    assert by_label(app.text_input, "Account type").value == ""
    assert not by_label(app.checkbox, CONFIRMATION).value
    by_label(app.text_input, "Account name").set_value("Second account").run()
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    store = app_store(tmp_path)
    assert not store.balance_history(date.today())
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert {row["account"] for row in store.balance_history(date.today())} == {"Second account SGD"}
    assert len(app.file_uploader[0].value) == 2
    assert not any(button.label == "Save balances" for button in app.button)
    by_label(app.button, "Back").click().run()
    assert by_label(app.text_input, "Account name").value == "First account"
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
    def preview(services, filename, content, *, log_model_output):
        if filename == "bad.pdf":
            raise ValueError("Unable to read this PDF statement.")
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "bad.pdf", "good.pdf")
    assert not app.exception
    assert any("Unable to read" in error.value for error in app.error)
    by_label(app.button, "Next").click().run()
    assert any(button.label == "Save balances" for button in app.button)
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    upload(app, "changed.pdf")
    assert not app.exception
    assert not any(button.label == "Save balances" for button in app.button)
    assert not saved_history(tmp_path)


def test_protected_pdf_password_is_requested_only_after_detection_and_cleared(monkeypatch):
    attempted_passwords = []

    def preview(services, filename, content, *, log_model_output, password=None):
        if password is None:
            raise StatementPasswordRequiredError("This PDF requires an opening password.")
        attempted_passwords.append(password)
        assert services.ollama_model_name == "qwen3:4b-instruct"
        if password != "correct horse":
            raise IncorrectStatementPasswordError(
                "The password was incorrect, or this encrypted PDF could not be opened."
            )
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    assert not any(item.label == "PDF opening password" for item in app.text_input)
    extract(app, "protected.pdf")
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
    assert any(item.label == "Account name" for item in app.text_input)


def test_selected_ollama_model_reaches_extraction(monkeypatch):
    models = []

    def preview(services, filename, content, *, log_model_output):
        models.append(services.ollama_model_name)
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    by_label(app.selectbox, "Ollama model").set_value("qwen3:1.7b").run()
    extract(app, "test.pdf")
    assert not app.exception
    assert models == ["qwen3:1.7b"]
    assert any(item.label == "Account name" for item in app.text_input)


def test_ollama_model_dropdown_lists_installed_models(monkeypatch):
    monkeypatch.delenv("WT_OLLAMA_MODEL", raising=False)
    app = start_app()
    model = by_label(app.selectbox, "Ollama model")
    assert model.options == ["qwen3:4b-instruct", "qwen3:1.7b"]
    assert model.value == "qwen3:4b-instruct"
    assert any("Only extracted statement text is sent" in item.value for item in app.caption)
    assert not app.exception


def test_unavailable_ollama_blocks_extraction(monkeypatch):

    def offline():
        raise OllamaRuntimeError("Ollama is not running.")

    for installed, message in ((offline, "Ollama is not running"), (lambda: (), "ollama pull")):
        monkeypatch.setattr("src.ui.forms._installed_ollama_models", installed)
        app = start_app()
        upload(app, "test.pdf")
        assert any(message in item.value for item in app.error)
        assert not any(button.key == "extract_statement" for button in app.button)
        assert not app.exception


def test_custom_default_model_falls_back_to_first_installed(monkeypatch):
    monkeypatch.setenv("WT_OLLAMA_MODEL", "missing:model")
    app = start_app()
    assert by_label(app.selectbox, "Ollama model").value == "qwen3:4b-instruct"


def test_review_corrections_validate_reset_confirmation_and_save_without_inference(tmp_path, monkeypatch):
    calls = []

    def preview(*args, **kwargs):
        calls.append(True)
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "test.pdf")
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Edit extracted rows").click().run()
    review_event(app, edits={0: {"Balance": "invalid"}})
    assert not app.exception
    assert not any(button.label == "Save balances" for button in app.button)
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert app.error
    assert not saved_history(tmp_path)
    review_event(app, edits={0: {
        "Balance": "987.12345678", "Withdrawal": "10.00",
        "Description": "Corrected payment",
    }})
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert not by_label(app.checkbox, CONFIRMATION).value
    assert by_label(app.button, "Save balances").disabled
    by_label(app.button, "Edit extracted rows").click().run()
    by_label(app.button, "Cancel corrections").click().run()
    assert not app.exception
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    saved = saved_history(tmp_path)
    assert saved[0]["balance"] == "987.12345678"
    assert saved[0]["withdrawal"] == "10.00"
    assert saved[0]["description"] == "Corrected payment"
    assert len(calls) == 1


def test_native_editor_edits_are_used_by_batch_save(tmp_path, monkeypatch):
    def preview(services, filename, content, **kwargs):
        extraction = statement_extraction()
        if filename == "two.pdf":
            return replace(extraction, accounts=(replace(extraction.accounts[0], number="OTHER1234"),))
        account = extraction.accounts[0]
        extra = replace(account.balances[0], balance=Decimal("50"), currency="USD")
        return replace(extraction, accounts=(replace(account, balances=(*account.balances, extra)),))

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    open_review(app, "one.pdf", "two.pdf")
    assert not app.exception
    assert any("Apply or cancel" in item.value for item in app.error)
    assert not any(button.label == "Save all balances" for button in app.button)
    review_event(
        app, edits={0: {"Balance": "999.12345678", "Description": "User correction"}},
        added=[{
            "Date": "2026-01-02", "Currency": "SGD", "Balance": "1000.12345678",
            "Withdrawal": "", "Deposit": "1.00", "Description": "Added transaction",
        }], deleted=[1],
    )
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    by_label(app.button, "Next").click().run()
    by_label(app.button, "Back").click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Balance"] == "999.12"
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save all balances").click().run()
    assert not app.exception
    saved = saved_history(tmp_path)
    assert any(row["balance"] == "999.12345678" and row["description"] == "User correction" for row in saved)
    assert any(
        row["balance"] == "1000.12345678" and row["deposit"] == "1.00"
        and row["description"] == "Added transaction" for row in saved
    )
    assert not any(row["currency"] == "USD" for row in saved)


def test_native_editor_restores_open_custom_table_draft(monkeypatch):
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: statement_extraction())
    app = start_app()
    open_review(app, "one.pdf")
    editor = review_editor(app)
    key = editor.proto.id.split("-", 2)[2].removesuffix("_native") + "_data"
    values = editor.value.iloc[0].to_dict()
    values["Description"] = "Retained draft"
    values["Balance"] = "123.12345678"
    app.session_state[key] = SimpleNamespace(rows=(
        SimpleNamespace(values=values),
        SimpleNamespace(values={"Description": "Incomplete added row"}),
    ))
    app.run()
    assert not app.exception
    assert not app.get("bidi_component")
    assert review_editor(app).value.iloc[0]["Description"] == "Retained draft"
    assert review_editor(app).value.iloc[0]["Balance"] == "123.12345678"
    assert len(review_editor(app).value) == 2
    by_label(app.button, "Apply corrections").click().run()
    assert app.error
    by_label(app.button, "Cancel corrections").click().run()
    assert not app.exception
    assert not by_label(app.button, "Edit extracted rows").disabled
    assert len(app.table[0].value) == 1


def test_cancel_unlocks_edit_and_save_before_table_render_can_interrupt(monkeypatch):
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: statement_extraction())
    app = start_app()
    extract(app, "one.pdf")
    by_label(app.checkbox, CONFIRMATION).check().run()
    by_label(app.button, "Edit extracted rows").click().run()
    review_event(app, edits={0: {"Balance": "invalid"}})
    by_label(app.button, "Apply corrections").click().run()
    assert app.error

    def interrupted_table(*args, **kwargs):
        st.stop()

    with monkeypatch.context() as interrupted:
        interrupted.setattr("src.ui.statement_edit.st.data_editor", interrupted_table)
        by_label(app.button, "Cancel corrections").click().run()
        assert not app.exception
        assert not app.error
        assert not by_label(app.button, "Edit extracted rows").disabled
        assert not by_label(app.button, "Save balances").disabled
    by_label(app.button, "Edit extracted rows").click().run()
    assert review_editor(app).value.iloc[0]["Balance"] != "invalid"
    by_label(app.button, "Cancel corrections").click().run()
    assert not by_label(app.button, "Edit extracted rows").disabled


def test_incomplete_added_review_row_blocks_apply_and_cancel_preserves_original(tmp_path, monkeypatch):
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: statement_extraction())
    app = start_app()
    open_review(app, "one.pdf")
    review_event(app, added=[{"Description": "Incomplete transaction"}])
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert app.error
    assert not any(button.label == "Save balances" for button in app.button)
    assert not saved_history(tmp_path)
    by_label(app.button, "Cancel corrections").click().run()
    assert not app.exception
    assert len(app.table[0].value) == 1


def test_review_requires_manual_balance_for_added_row(tmp_path, monkeypatch):
    extraction = statement_extraction()
    account = extraction.accounts[0]
    first = replace(account.balances[0], balance=Decimal("100"), as_of=date(2026, 4, 1))
    second = replace(
        first, balance=Decimal("120"), withdrawal=Decimal("20"), as_of=date(2026, 4, 2),
    )
    extraction = replace(extraction, accounts=(
        replace(account, account_type="Savings", balances=(first, second)),
    ))
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: extraction)
    app = start_app()
    extract(app, "one.pdf")
    assert app.dataframe[0].value.iloc[1]["Withdrawal"] == "20.00"
    by_label(app.button, "Edit extracted rows").click().run()
    editor = review_editor(app)
    assert list(editor.value.columns) == [
        "Date", "Currency", "Balance", "Withdrawal", "Deposit", "Description",
    ]
    review_event(app, added=[{
            "Date": "2026-04-03", "Currency": "SGD", "Balance": "",
            "Withdrawal": "10", "Deposit": "", "Description": "Added payment",
    }])
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert any("Enter a balance" in item.value for item in app.error)
    assert not saved_history(tmp_path)
    review_event(app, edits={2: {"Balance": "110"}})
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[1]["Withdrawal"] == "20.00"
    assert app.dataframe[0].value.iloc[1]["Deposit"] == ""
    assert app.dataframe[0].value.iloc[2]["Balance"] == "110.00"
    by_label(app.checkbox, CONFIRMATION).check().run()
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    saved = saved_history(tmp_path)
    assert any(row["balance"] == "110" and row["withdrawal"] == "10" for row in saved)


@pytest.mark.parametrize("action", ["Apply corrections", "Cancel corrections"])
def test_review_never_automatically_swaps_movements(monkeypatch, action):
    extraction = statement_extraction()
    account = extraction.accounts[0]
    first = replace(account.balances[0], balance=Decimal("100"))
    second = replace(first, balance=Decimal("120"), withdrawal=Decimal("20"))
    extraction = replace(extraction, accounts=(
        replace(account, account_type="Savings", balances=(first, second)),
    ))
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: extraction)
    app = start_app()
    open_review(app, "one.pdf")
    by_label(app.button, action).click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[1]["Withdrawal"] == "20.00"
    assert app.dataframe[0].value.iloc[1]["Deposit"] == ""


@pytest.mark.parametrize("action", ["Apply corrections", "Cancel corrections"])
def test_native_review_preserves_pending_row_order_until_apply_or_cancel(tmp_path, monkeypatch, action):
    extraction = statement_extraction()
    account = extraction.accounts[0]
    original = replace(account.balances[0], balance=Decimal("10"), as_of=date(2026, 4, 2))
    extraction = replace(extraction, accounts=(replace(account, balances=(original,)),))
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: extraction)
    app = start_app()
    open_review(app, "one.pdf")
    review_event(app, edits={0: {"Description": "Pending edit"}}, added=[{
            "Date": "2026-04-01", "Currency": "SGD", "Balance": "2",
            "Withdrawal": "", "Deposit": "", "Description": "Added row",
    }])
    assert not app.exception
    key = review_editor(app).proto.id.split("-", 2)[2]
    rows = _pending_rows(
        app.session_state[key.removesuffix("_native") + "_data"], app.session_state[key],
    )
    assert [row["Description"] for row in rows] == ["Pending edit", "Added row"]
    assert not any(button.label == "Save balances" for button in app.button)
    assert [row["Balance"] for row in rows] == ["10", "2"]
    by_label(app.button, action).click().run()
    assert not app.exception
    if action == "Cancel corrections":
        assert len(app.table[0].value) == 1
        assert app.table[0].value.iloc[0]["Description"] == ""
    else:
        assert list(app.table[0].value["Description"]) == ["Pending edit", "Added row"]
    assert not saved_history(tmp_path)


def test_deleting_all_review_rows_shows_error_and_cancel_preserves_original(tmp_path, monkeypatch):
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: statement_extraction())
    app = start_app()
    open_review(app, "one.pdf")
    review_event(app, deleted=[0])
    by_label(app.button, "Apply corrections").click().run()
    assert not app.exception
    assert any("Keep at least one row" in item.value for item in app.error)
    assert not any(button.label == "Save balances" for button in app.button)
    assert not saved_history(tmp_path)
    by_label(app.button, "Cancel corrections").click().run()
    assert not app.exception
    assert len(app.table[0].value) == 1
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert len(saved_history(tmp_path)) == 1


@pytest.mark.parametrize("protected", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_extraction_shows_timed_spinner_inside_import_fragment(
    monkeypatch, protected, fails,
):
    spinner_calls = []
    active = []
    original_spinner = st.spinner

    @contextmanager
    def spinner(text, **kwargs):
        spinner_calls.append((text, kwargs))
        active.append(text)
        try:
            with original_spinner(text, **kwargs):
                yield
        finally:
            active.pop()

    def preview(services, filename, content, *, log_model_output, password=None):
        assert active == ["Parsing statement 1 of 1: statement.pdf"]
        assert spinner_calls[-1][1]["show_time"] is True
        progress = current_progress()
        assert progress
        report_stage("Generating response")
        progress.generation(GenerationProgress(
            started_at=0, input_tokens=100, generated_tokens=5,
            first_token_seconds=1, elapsed_seconds=2, text='{"accounts":',
            finished=True, eos=not fails,
        ))
        if protected and password is None:
            raise StatementPasswordRequiredError("Password required.")
        if protected:
            assert password == "test-password"
        if fails:
            raise ValueError("Extraction failed.")
        return statement_extraction()

    monkeypatch.setattr(st, "spinner", spinner)
    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "statement.pdf")
    assert not app.exception
    if protected:
        by_label(app.text_input, "PDF opening password").set_value("test-password")
        by_label(app.button, "Unlock and extract").click().run()
    assert not app.exception
    assert not active
    assert len(spinner_calls) == (2 if protected else 1)
    assert app.title[0].value == "BarelyRich"
    assert any("Generated: 5 tokens" in element.value for element in app.text)
    assert any(element.value == '{"accounts":' for element in app.code)
    assert app.status[-1].state == ("error" if fails else "complete")
    if fails:
        assert any(error.value == "Extraction failed." for error in app.error)
    else:
        assert any(item.label == "Account name" for item in app.text_input)


def test_partial_output_is_rendered_before_worker_finishes_and_never_saved(
    tmp_path, monkeypatch,
):
    rendered = Event()
    worker_finished = Event()
    original_code = DeltaGenerator.code

    def code(element, body, *args, **kwargs):
        if body == '{"partial":':
            assert not worker_finished.is_set()
            rendered.set()
        return original_code(element, body, *args, **kwargs)

    def preview(services, filename, content, *, log_model_output):
        progress = current_progress()
        assert progress
        report_stage("Generating response")
        progress.generation(GenerationProgress(
            started_at=perf_counter(), input_tokens=100, generated_tokens=3,
            first_token_seconds=0.01, text='{"partial":',
        ))
        assert rendered.wait(timeout=2), "Partial output was not rendered while generation was running"
        worker_finished.set()
        raise ValueError("Model timed out; no partial response accepted.")

    monkeypatch.setattr(DeltaGenerator, "code", code)
    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "statement.pdf")
    assert not app.exception
    assert rendered.is_set() and worker_finished.is_set()
    assert app.status[-1].state == "error"
    assert any(item.value == '{"partial":' for item in app.code)
    assert not saved_history(tmp_path)
    assert not any(button.label == "Save balances" for button in app.button)


def test_ollama_live_decode_speed_renders_before_final_token_counts(monkeypatch):
    rendered = Event()
    live_labels = []
    original_text = DeltaGenerator.text

    def text(element, body, *args, **kwargs):
        if "chars/s (live)" in body:
            live_labels.append(body)
            assert "Decode: pending" not in body
            assert "120 characters (tokens pending)" in body
            rendered.set()
        return original_text(element, body, *args, **kwargs)

    def preview(services, filename, content, *, log_model_output):
        progress = current_progress()
        state = GenerationProgress(
            started_at=perf_counter() - 3, input_tokens=None, generated_tokens=None,
            first_token_seconds=1, text='{"partial":',
            generated_characters=120, first_chunk_characters=20,
        )
        progress.generation(state)
        assert rendered.wait(timeout=2), "Live speed did not render before completion"
        progress.generation(replace(
            state, generated_tokens=40, input_tokens=100,
            elapsed_seconds=3, finished=True, eos=True,
        ))
        return statement_extraction()

    monkeypatch.setattr(DeltaGenerator, "text", text)
    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "test.pdf")
    assert not app.exception
    assert live_labels
    assert any("Decode: 19.50 tokens/s" in element.value for element in app.text)
    assert app.status[-1].state == "complete"


def test_save_all_uses_edits_resets_confirmation_and_skips_failed_files(tmp_path, monkeypatch):
    def preview(services, filename, content, *, log_model_output):
        if filename == "bad.pdf":
            raise ValueError("Invalid PDF")
        return extraction_for(filename)

    monkeypatch.setattr(EntryServices, "preview", preview)
    app = start_app()
    extract(app, "first.pdf", "second.pdf", "bad.pdf")
    assert not app.exception
    assert by_label(app.button, "Back").proto.icon
    assert by_label(app.button, "Next").proto.type == "primary"
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account name").set_value("First edited").run()
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.button, "Next").click().run()
    by_label(app.text_input, "Account name").set_value("Second edited").run()
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account type").set_value("Fixed deposit").run()
    assert by_label(app.button, "Save all balances").disabled
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save all balances").click().run()
    assert not app.exception
    store = app_store(tmp_path)
    assert {row["account"] for row in store.balance_history(date.today())} == {
        "First edited SGD", "Second edited SGD",
    }
    assert {
        row["product_type"] for row in store.balance_history(date.today())
        if row["account"] == "Second edited SGD"
    } == {"Fixed deposit"}
    assert app.success[0].value == "Saved 2 transaction/balance rows from 2 statements."
    assert app.file_uploader[0].value == []
    assert not any(button.label == "Save all balances" for button in app.button)
    app.run()
    assert app.file_uploader[0].value == []
    assert len(store.balance_history(date.today())) == 2


def test_bulk_save_conflict_rolls_back_and_preserves_pending_previews(tmp_path, monkeypatch):
    monkeypatch.setattr(
        EntryServices, "preview",
        lambda services, filename, content, **options: statement_extraction(),
    )
    app = start_app()
    extract(app, "first.pdf", "duplicate.pdf")
    by_label(app.checkbox, BATCH_CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save all balances").click().run()
    assert not app.exception
    assert any("Duplicate account/date" in error.value for error in app.error)
    assert len(app.file_uploader[0].value) == 2
    assert not saved_history(tmp_path)
    assert not by_label(app.button, "Save all balances").disabled
    by_label(app.button, "Next").click().run()
    assert any(button.label == "Save balances" for button in app.button)


@pytest.mark.parametrize("currencies", [("SGD",), ("SGD", "THB")])
def test_statement_review_confirmation_and_persistence(
    tmp_path, monkeypatch, currencies,
):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("statement text",))
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("Fictional text",))

    class FakeAgent:
        @staticmethod
        def parse(document):
            balances = tuple(
                StatementBalance(
                    Decimal("1234.50"), currency, date.today(),
                ) for currency in currencies
            )
            return StatementExtraction(
                (StatementAccount("1234", balances),),
                StatementInstitution("Example Bank"),
            )

    monkeypatch.setattr(
        StatementAgent, "from_environment",
        classmethod(lambda agent_type, **options: FakeAgent()),
    )
    app = start_app()
    assert not any(item.label == "Statement model" for item in app.selectbox)
    extract(app, "statement.pdf")
    assert not app.exception
    assert any("not independently verified" in item.value for item in app.warning)
    assert not any("evidence" in item.value.lower() for item in app.caption)
    assert not any("double-counting" in item.value for item in app.warning)
    card = app.get_by_key("statement_review_account_1")
    assert [item.label for item in card.text_input] == ["Account type", "Account name"]
    assert [item.label for item in card.button] == ["Edit extracted rows", "Save balances"]
    assert card.table[0].value.to_dict("records") == [
        {
            "Date": date.today().isoformat(), "Currency": currency, "Balance": "1,234.50",
            "Withdrawal": "", "Deposit": "", "Description": "",
        } for currency in currencies
    ]
    assert not card.expander
    assert sum(
        "Statement date:" in item.value for item in card.caption
    ) == 1
    assert by_label(app.text_input, "Account name").value == "Example"
    assert by_label(app.button, "Save balances").disabled
    store = app_store(tmp_path)
    assert not store.balance_history(date.today())
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.text_input, "Account name").set_value("Savings").run()
    assert by_label(app.button, "Save balances").disabled
    by_label(app.checkbox, CONFIRMATION).set_value(True).run()
    by_label(app.button, "Save balances").click().run()
    assert not app.exception
    assert app.success[0].value == f"Saved {len(currencies)} statement transaction/balance rows."
    assert {row["account"] for row in store.balance_history(date.today())} == {
        f"Savings {currency}" for currency in currencies
    }


def test_multi_account_statement_reviews_and_saves_fixed_deposit_separately(tmp_path, monkeypatch):
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
    app = start_app()
    extract(app, "statement.pdf")
    assert not app.exception
    assert by_label(app.text_input, "Account name").value == "DBS 1"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account name").value == "DBS Savings 2"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").value == "Savings"
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").set_value(
        "Fixed deposit",
    ).run()
    assert by_label(
        app.get_by_key("statement_review_account_2").text_input, "Account name",
    ).value == "DBS Fixed deposit 2"
    first_card = app.get_by_key("statement_review_account_1")
    second_card = app.get_by_key("statement_review_account_2")
    assert [item.label for item in first_card.button] == ["Edit extracted rows", "Save account 1 balances"]
    assert [item.label for item in second_card.button] == ["Edit extracted rows", "Save account 2 balances"]
    assert first_card.table[0].value.to_dict("records") == [
        {
            "Date": date.today().isoformat(), "Currency": "SGD", "Balance": "1,234.50",
            "Withdrawal": "", "Deposit": "", "Description": "",
        },
    ]
    assert second_card.table[0].value.to_dict("records") == [
        {
            "Date": date.today().isoformat(), "Currency": "SGD", "Balance": "50,000.00",
            "Withdrawal": "", "Deposit": "", "Description": "",
        },
    ]
    assert sum("not independently verified" in item.value for item in app.warning) == 1
    assert len(first_card.warning) == 1
    assert "Account type is missing or conflicting" in first_card.warning[0].value
    assert not second_card.warning
    by_label(app.text_input, "Account name").set_value("Savings").run()
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account name").set_value("Fixed deposit").run()
    by_label(app.checkbox, "I reviewed account 2 and want to save its transactions and balances.").set_value(True).run()
    by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").set_value("Term deposit").run()
    assert by_label(app.button, "Save account 2 balances").disabled
    by_label(app.checkbox, "I reviewed account 1 and want to save its transactions and balances.").set_value(True).run()
    by_label(app.button, "Save account 1 balances").click().run()
    assert not app.exception
    rows = saved_history(tmp_path)
    assert [(row["account"], row["account_number"]) for row in rows] == [
        ("Savings SGD", "TEST1234"),
    ]
    saved_card = app.get_by_key("statement_review_account_1")
    assert all(item.disabled for item in saved_card.text_input)
    assert not saved_card.checkbox
    assert not saved_card.button
    assert any(item.value == "Saved" for item in saved_card.caption)
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account name").value == "Fixed deposit"
    assert by_label(app.get_by_key("statement_review_account_2").text_input, "Account type").value == "Term deposit"
    assert by_label(app.button, "Save account 2 balances").disabled
    by_label(app.checkbox, "I reviewed account 2 and want to save its transactions and balances.").set_value(True).run()
    by_label(app.button, "Save account 2 balances").click().run()

    rows = saved_history(tmp_path)
    assert {(row["account"], row["account_number"], row["balance"]) for row in rows} == {
        ("Savings SGD", "TEST1234", "1234.50"),
        ("Fixed deposit SGD", "****5678", "50000.00"),
    }
    assert {row["product_type"] for row in rows if row["account_number"] == "****5678"} == {
        "Term deposit",
    }
    restarted = start_app()
    assert not restarted.exception
    assert any(
        "Account type" in grid.value.columns
        and "Term deposit" in grid.value["Account type"].values
        for grid in restarted.dataframe
    )


def test_manual_assets_debts_fx_replacement_and_history(tmp_path):
    app = start_app()
    earlier = date.today() - timedelta(days=30)
    save_valuation(app, name="Gold", amount="100", as_of=earlier)
    save_valuation(app, name="Gold", amount="125", as_of=date.today())
    save_valuation(app, name="Home", amount="100000", currency="INR")
    save_valuation(app, name="Mortgage", amount="20000", currency="INR", kind="liability")
    assert not app.exception
    assert app.metric[0].value == "87,500.00"
    store = app_store(tmp_path)
    assert len(store.balance_history(date.today())) == 4
    save_valuation(app, name="Gold", amount="150", as_of=date.today())
    assert len(store.balance_history(date.today())) == 4
    assert app.metric[0].value == "89,000.00"
    assert app.get("vega_lite_chart")
    restarted = start_app()
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
def test_invalid_manual_valuation_never_saves(tmp_path, amount, kind, message):
    app = start_app()
    save_valuation(app, amount=amount, kind=kind)
    assert not app.exception
    assert any(message in error.value for error in app.error)
    assert not saved_history(tmp_path)


def test_inr_portfolio_displays_crore_grouping_without_changing_saved_amount(tmp_path):
    app = start_app()
    save_valuation(app, name="Home", amount="12345678.906", currency="INR")
    assert not app.exception
    assert app.metric[0].value == "1,23,45,678.91"
    store = app_store(tmp_path)
    assert store.balance_history(date.today())[0]["balance"] == "12345678.906"
    assert app.get("vega_lite_chart")


def test_zero_value_retires_asset_and_foreign_currency_is_supported():
    app = start_app()
    save_valuation(app, name="Overseas home", currency="USD", amount="500")
    assert app.metric[0].value == "30,000.00"
    save_valuation(app, name="Overseas home", currency="USD", amount="0")
    assert app.metric[0].value == "0.00"
    save_valuation(app, name="Overseas home", currency="EUR", amount="500")
    assert any("currency or kind cannot change" in item.value for item in app.error)


def test_statement_failure_is_visible_without_persistence(tmp_path, monkeypatch):

    def unavailable(agent_type, **options):
        raise ValueError("Local model files are missing.")

    monkeypatch.setattr(StatementAgent, "from_environment", classmethod(unavailable))
    app = start_app()
    extract(app, "statement.pdf")
    assert not app.exception
    assert any("Local model files" in item.value for item in app.error)
    assert not saved_history(tmp_path)


def test_stale_observations_and_fx_failure_are_visible(store, monkeypatch):

    def fail_fetch(provider, currencies, as_of):
        raise ExchangeRateFetchError("Automatic FX refresh failed: offline.")

    monkeypatch.setattr(FrankfurterExchangeRateProvider, "fetch", fail_fetch)
    stale = date.today() - timedelta(days=31)
    store.save([BalanceSnapshot("Bank", "Savings", "SGD", Decimal("100"), "asset", stale, "manual")])
    app = start_app()
    assert not app.metric
    assert any("missing dated FX" in item.value for item in app.error)
    store.save_rate("SGD", "60", stale)
    app.run()
    assert not app.exception
    assert app.metric[0].value == "6,000.00"
    assert any("Balances more than 30 days old" in item.value for item in app.warning)
    assert any("FX rates more than 30 days old" in item.value for item in app.warning)
