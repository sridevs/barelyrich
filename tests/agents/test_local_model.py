import asyncio
import json
from threading import get_ident

import pytest
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_core import ErrorDetails

from src.agents.local_model import LocalStatementModel
from src.agents.response import MissingStatementData, StatementParsingError
from src.agents.statement_agent import StatementAgent
from src.log_messages import error
from src.models.statements.statement_document import StatementDocument
from tests.prompt_fixtures import STATEMENT_RESPONSE_EXAMPLE
from tests.statement_fixtures import RepairingRuntime, text_document


def test_domain_retry_passes_specific_date_reason_and_merged_row_location():
    runtime = RepairingRuntime(
        ["2025-18-11", "100.00", "SGD", None, "1.00", "Interest"],
        ["2025-11-18", "100.00", "SGD", None, "1.00", "Interest"],
    )
    result = StatementAgent(runtime).parse(text_document())
    assert len(runtime.prompts) == 2
    assert "Merged accounts[0].balances[0]" in runtime.prompts[1]
    assert error.AS_OF_DATE_MUST_BE_YYYY_MM_DD in runtime.prompts[1]
    assert "Validation error:" in runtime.prompts[1]
    assert result.balances[0].as_of.isoformat() == "2025-11-18"


COMPLETE_RESPONSE = json.dumps(STATEMENT_RESPONSE_EXAMPLE)


class LocalRuntime:
    def __init__(self):
        self.calls = []
        self.thread_id = None

    def generate(self, document: StatementDocument, prompt: str) -> str:
        self.calls.append((document, prompt))
        self.thread_id = get_ident()
        return COMPLETE_RESPONSE


@pytest.fixture
def runtime():
    return LocalRuntime()


@pytest.fixture
def document():
    return text_document()


@pytest.fixture
def model(runtime, document):
    return LocalStatementModel(runtime, document, "original instructions")


def test_ollama_does_not_require_literal_account_match_in_source_text():
    model = LocalStatementModel(
        LocalRuntime(), text_document("Account identifier split by PDF layout"), "instructions",
    )
    payload = {
        "institution": {"name": "Bank"},
        "accounts": [{"number": "****9669", "balances": [{
            "description": "",
            "withdrawal": None, "deposit": None,
            "balance": "12.00", "currency": "INR", "as_of": "2026-09-30",
        }]}],
    }
    model._validate_response(json.dumps(payload))


def test_adapter_uses_central_exception_wording(monkeypatch, model):
    monkeypatch.setattr(error, "LOCAL_INFERENCE_TEXT_ONLY", "Unsupported inference options.")
    monkeypatch.setattr(error, "NO_STATEMENT", "Statement data is missing.")
    with pytest.raises(StatementParsingError, match="Unsupported inference options"):
        LocalStatementModel._require_text_output(ModelRequestParameters(output_mode="native"))
    with pytest.raises(MissingStatementData, match="Statement data is missing"):
        model._validate_response("")


def test_adapter_runs_in_process_off_the_event_loop_and_preserves_document_identity(runtime, document, model):
    response = asyncio.run(model.request(
        [ModelRequest(parts=[UserPromptPart("original instructions")])],
        None, ModelRequestParameters(),
    ))
    assert runtime.calls == [(document, "original instructions")]
    assert runtime.calls[0][0] is document
    assert runtime.thread_id != get_ident()
    assert response.parts == [TextPart(COMPLETE_RESPONSE)]
    assert response.model_name == model.model_name
    assert model.system == "ollama"
    assert model.profile.supports_tools is False


def test_prompt_is_read_only_and_implementation_state_is_private(model):
    assert model.prompt == "original instructions"
    with pytest.raises(AttributeError):
        model.prompt = "replacement instructions"
    for field in ("runtime", "document", "log_model_output"):
        assert not hasattr(model, field)


def test_adapter_replays_original_instructions_with_framework_retry(runtime, document, model):
    asyncio.run(model.request([
        ModelRequest(parts=[UserPromptPart("original instructions")]),
        ModelResponse(
            parts=[TextPart("private previous response")],
            provider_details=None, provider_response_id=None,
        ),
        ModelRequest(parts=[RetryPromptPart("FORMATTING RETRY: invalid JSON syntax")]),
    ], None, ModelRequestParameters()))
    assert runtime.calls[0][0] is document
    assert runtime.calls[0][1].startswith("original instructions\nOUTPUT RETRY")
    assert "private previous response" not in runtime.calls[0][1]


def test_adapter_uses_framework_structured_retry_feedback(runtime, model):
    asyncio.run(model.request(
        [ModelRequest(parts=[RetryPromptPart([
            ErrorDetails(
                type="missing", loc=("private field",), input="private input",
                msg="Field required",
            ),
        ])])], None, ModelRequestParameters(),
    ))
    assert "Field required" in runtime.calls[0][1]
    assert "OUTPUT RETRY" in runtime.calls[0][1]


def test_retry_logs_schema_path_and_error_without_private_values(caplog, runtime, model):
    asyncio.run(model.request(
        [ModelRequest(parts=[RetryPromptPart([
            ErrorDetails(
                type="string_type", loc=("accounts", 0, "number"),
                input=[{"quote": "private account number"}] * 2,
                msg="Expected citation object",
            ),
            ErrorDetails(
                type="extra_forbidden", loc=("private account number",),
                input="private balance", msg="Extra inputs are not permitted",
            ),
        ])])], None, ModelRequestParameters(),
    ))
    assert "accounts.0.number: string_type" in caplog.text
    assert "<field>: extra_forbidden" in caplog.text
    assert "private account number" not in caplog.text
    assert "private balance" not in caplog.text


def test_adapter_uses_only_latest_framework_correction_and_logs_once(caplog, runtime, model):
    asyncio.run(model.request([
        ModelRequest(parts=[RetryPromptPart(
            'Model returned a duplicate JSON field: "balances"; no balances were saved.',
        )]),
        ModelRequest(parts=[RetryPromptPart(
            "As-of date must be YYYY-MM-DD.",
        )]),
    ], None, ModelRequestParameters()))
    assert "As-of date must be YYYY-MM-DD" in runtime.calls[0][1]
    assert "Duplicate JSON field" not in runtime.calls[0][1]
    assert len(caplog.records) == 1




def test_adapter_refuses_unsupported_output_modes_before_generation(runtime, model):
    with pytest.raises(UserError, match="Native structured output"):
        asyncio.run(model.request([], None, ModelRequestParameters(output_mode="native")))
    assert not runtime.calls
