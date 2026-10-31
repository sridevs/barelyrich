import json
from unittest.mock import create_autospec

import pytest

from src.agents.response import MissingStatementData
from src.agents.statement_agent import StatementAgent
from src.inference.ollama_runtime import OllamaRuntime
from src.readers.statement_pdf import StatementPdf
from src.service.entry_services import EntryServices
from tests.prompt_fixtures import STATEMENT_RESPONSE_EXAMPLE
from tests.statement_fixtures import statement_extraction


@pytest.fixture
def extraction():
    return statement_extraction()


@pytest.fixture
def agent(extraction):
    agent = create_autospec(StatementAgent, instance=True)
    agent.parse.return_value = extraction
    return agent


@pytest.fixture
def factory(monkeypatch, agent):
    factory = create_autospec(StatementAgent.from_environment, return_value=agent)
    monkeypatch.setattr(StatementAgent, "from_environment", factory)
    return factory


def test_statement_preview_uses_text_model_and_debug_flag(monkeypatch, extraction, factory):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("fictional text",))

    result = EntryServices("qwen3:1.7b").preview("fictional.pdf", b"pdf", log_model_output=True)

    assert result is extraction
    factory.assert_called_once_with(log_model_output=True, model_name="qwen3:1.7b")


@pytest.mark.usefixtures("factory")
def test_csv_statement_uses_the_same_text_model_without_pdf_reading(monkeypatch, extraction, agent):
    monkeypatch.setattr(
        StatementPdf, "text",
        lambda *_args: pytest.fail("CSV input must not use the PDF reader"),
    )
    content = b"Date,Description,Amount,Balance,Currency\n2025-01-02,Coffee,-5.00,95.00,SGD"

    result = EntryServices().preview(
        "fictional.csv", content, log_model_output=False,
    )

    assert result is extraction
    assert agent.parse.call_args.args[0].pages[0].text == content.decode()


def test_ollama_selection_uses_shared_validation(monkeypatch):
    calls = []

    def generate(runtime, document, prompt):
        assert runtime._output_schema["$defs"]["BalanceOutput"]["prefixItems"][2]["enum"]
        assert "Each row has exactly six positions" in prompt
        calls.append(runtime.configuration.model_name)
        return json.dumps(STATEMENT_RESPONSE_EXAMPLE)

    monkeypatch.setattr(OllamaRuntime, "generate", generate)
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("fictional statement",))
    result = EntryServices().with_ollama_model("qwen3:4b-instruct").preview(
        "fictional.pdf", b"pdf", log_model_output=False,
    )
    assert result.accounts
    assert calls == ["qwen3:4b-instruct"]


def test_model_selection_is_immutable():
    services = EntryServices()
    assert services.with_ollama_model("qwen3:1.7b").ollama_model_name == "qwen3:1.7b"
    assert services.ollama_model_name is None


def test_missing_output_is_reported(monkeypatch):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("fictional statement",))
    monkeypatch.setattr(OllamaRuntime, "generate", lambda *args: "{}")
    with pytest.raises(MissingStatementData):
        EntryServices().preview("fictional.pdf", b"pdf", log_model_output=False)


def test_scan_is_rejected_before_model_generation(monkeypatch):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("",))
    monkeypatch.setattr(
        OllamaRuntime, "generate", lambda *args: pytest.fail("No readable text"),
    )
    with pytest.raises(ValueError, match="Run OCR"):
        EntryServices().preview("scan.pdf", b"pdf", log_model_output=False)
