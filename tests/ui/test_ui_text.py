import tomllib
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import config
from src.service.entry_services import EntryServices
from src.ui import ui_text
from tests.statement_fixtures import statement_extraction

APP = Path(__file__).resolve().parents[2] / "app.py"


def test_button_accent_is_consistent_across_light_and_dark_themes():
    theme = tomllib.loads((APP.parent / ".streamlit/config.toml").read_text())["theme"]
    assert theme["light"]["primaryColor"] == theme["dark"]["primaryColor"] == "#1D4ED8"


def test_dynamic_copy_reads_current_limits_and_preserves_formatting(monkeypatch):
    monkeypatch.setattr(config, "MAX_STATEMENT_PAGES", 3)
    monkeypatch.setattr(config, "MAX_STATEMENT_BYTES", 2_000_000)
    monkeypatch.setattr(config, "STALE_AFTER_DAYS", 5)
    assert "up to 3 pages each" in ui_text.statement_guidance()
    assert ui_text.statement_upload_label() == "Statement files (PDF or CSV, up to 2 MB each)"
    assert ui_text.stale_accounts(["Savings"]) == "Balances more than 5 days old: Savings"
    assert ui_text.stale_currencies(["SGD"]) == "FX rates more than 5 days old affect: SGD"
    assert ui_text.history_hover(date(2024, 1, 2), "SGD", "1,234.00") == "02 Jan 2024 | SGD 1,234.00"
    assert ui_text.currency_warning("SGD", "Check amount") == "SGD: Check amount"


def test_csv_upload_uses_statement_review_without_a_password_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))

    def preview(_services, filename, _content, *, log_model_output, password=None):
        assert filename == "statement.csv"
        assert password is None
        return statement_extraction()

    monkeypatch.setattr(EntryServices, "preview", preview)
    monkeypatch.setattr("src.ui.forms._installed_ollama_models", lambda: ("qwen3:4b-instruct",))
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.file_uploader[0].set_value(
        ("statement.csv", b"Date,Description,Amount,Balance,Currency", "text/csv"),
    ).run()
    app.button(key="extract_statement").click().run()

    assert not app.exception
    assert not any(item.label == "PDF opening password" for item in app.text_input)
    assert any(item.label == "Statement institution" for item in app.selectbox)


def test_workflow_and_manual_labels_can_change_without_losing_selection_or_values(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert set(app.file_uploader[0].proto.type) == {".pdf", ".csv"}
    assert all(button.proto.type == "primary" for button in app.button)
    assert app.button(key="extract_statement").disabled
    app.button(key="choose_Manual valuation").click().run()
    assert all(button.proto.type == "primary" for button in app.button)
    app.text_input(key="valuation_name").set_value("Gold")
    app.text_input(key="valuation_amount").set_value("125")
    app.text_input(key="valuation_group").set_value("")
    app.button(key="save_valuation").click().run()
    assert app.error
    assert app.text_input(key="valuation_name").value == "Gold"
    monkeypatch.setattr(ui_text, "MANUAL_VALUATION", "Record a valuation")
    monkeypatch.setattr(ui_text, "ASSET_NAME", "Valuation name")
    monkeypatch.setattr(ui_text, "TOTAL_VALUE", "Estimated value")
    monkeypatch.setattr(ui_text, "DATA_ENTRY", "Add records")
    app.run()
    assert not app.exception
    assert app.tabs[0].label == "Add records"
    assert app.button(key="choose_Manual valuation").label == "Record a valuation"
    assert app.button(key="choose_Manual valuation").proto.type == "primary"
    assert app.text_input(key="valuation_name").label == "Valuation name"
    assert app.text_input(key="valuation_name").value == "Gold"
    assert app.text_input(key="valuation_amount").value == "125"
    assert not app.file_uploader


def test_review_wording_changes_preserve_edits_and_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("WT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(EntryServices, "preview", lambda *args, **kwargs: statement_extraction())
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.file_uploader[0].set_value([("test.pdf", b"test", "application/pdf")]).run()
    app.button(key="extract_statement").click().run()
    alias = next(item for item in app.text_input if item.label == "Account name")
    alias.set_value("My savings").run()
    confirmation = next(item for item in app.checkbox if item.label == ui_text.ACCOUNT_CONFIRMATION)
    confirmation.set_value(True).run()
    monkeypatch.setattr(ui_text, "ACCOUNT_ALIAS", "Display name")
    monkeypatch.setattr(ui_text, "ACCOUNT_CONFIRMATION", "I approve these balances.")
    monkeypatch.setattr(ui_text, "SAVE_BALANCES", "Save reviewed balances")
    app.run()
    assert not app.exception
    assert next(item for item in app.text_input if item.label == "Display name").value == "My savings"
    assert next(item for item in app.checkbox if item.label == "I approve these balances.").value
    assert app.button(key="save_statement").label == "Save reviewed balances"
    assert not app.button(key="save_statement").disabled
    assert all(button.proto.type == "primary" for button in app.button)
