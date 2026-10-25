import asyncio
from threading import get_ident

from pydantic_ai.messages import (
    ModelRequest, ModelResponse, RetryPromptPart, TextPart, UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.exceptions import UserError
from pydantic_core import ErrorDetails
import pytest

from src.agents.local_model import LocalStatementModel
from src.log_messages import error
from src.agents.response import MissingStatementData, StatementParsingError
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage


class LocalRuntime:
    def __init__(self):
        self.calls = []
        self.thread_id = None

    def generate(self, document: StatementDocument, prompt: str) -> str:
        self.calls.append((document, prompt))
        self.thread_id = get_ident()
        return '{"account": {}, "balances": []}'


def test_adapter_uses_central_exception_wording(monkeypatch):
    monkeypatch.setattr(error, "LOCAL_INFERENCE_TEXT_ONLY", "Unsupported inference options.")
    monkeypatch.setattr(error, "NO_STATEMENT", "Statement data is missing.")
    with pytest.raises(StatementParsingError, match="Unsupported inference options"):
        LocalStatementModel._require_text_output(ModelRequestParameters(output_mode="native"))
    model = LocalStatementModel(
        LocalRuntime(), StatementDocument((StatementPage(1, b"", "statement text"),)), "instructions",
    )
    with pytest.raises(MissingStatementData, match="Statement data is missing"):
        model._validate_response("")


def test_adapter_runs_in_process_off_the_event_loop_and_preserves_image_identity():
    runtime = LocalRuntime()
    document = StatementDocument((StatementPage(1, b"page image"),))
    model = LocalStatementModel(runtime, document, "original instructions")
    response = asyncio.run(model.request(
        [ModelRequest(parts=[UserPromptPart("original instructions")])],
        None, ModelRequestParameters(),
    ))
    assert runtime.calls == [(document, "original instructions")]
    assert runtime.calls[0][0] is document
    assert runtime.thread_id != get_ident()
    assert response.parts == [TextPart('{"account": {}, "balances": []}')]
    assert response.model_name == model.model_name
    assert model.system == "transformers"
    assert model.profile.supports_tools is False


def test_prompt_is_read_only_and_implementation_state_is_private():
    runtime = LocalRuntime()
    document = StatementDocument((StatementPage(1, b"page image"),))
    model = LocalStatementModel(runtime, document, "original instructions")
    assert model.prompt == "original instructions"
    with pytest.raises(AttributeError):
        model.prompt = "replacement instructions"
    for field in ("runtime", "document", "log_model_output"):
        assert not hasattr(model, field)


def test_adapter_replays_original_instructions_with_framework_retry():
    runtime = LocalRuntime()
    document = StatementDocument((StatementPage(1, b"page image"),))
    model = LocalStatementModel(runtime, document, "original instructions")
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


def test_adapter_uses_framework_structured_retry_feedback():
    runtime = LocalRuntime()
    model = LocalStatementModel(
        runtime, StatementDocument((StatementPage(1, b"page image"),)), "original instructions",
    )
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


def test_retry_logs_schema_path_and_error_without_private_values(caplog):
    runtime = LocalRuntime()
    model = LocalStatementModel(
        runtime, StatementDocument((StatementPage(1, b"image"),)), "original instructions",
    )
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


def test_adapter_uses_only_latest_framework_correction_and_logs_once(caplog):
    runtime = LocalRuntime()
    model = LocalStatementModel(
        runtime, StatementDocument((StatementPage(1, b"page image"),)), "original instructions",
    )
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




def test_adapter_refuses_unsupported_output_modes_before_generation():
    runtime = LocalRuntime()
    model = LocalStatementModel(
        runtime, StatementDocument((StatementPage(1, b"page image"),)), "original instructions",
    )
    with pytest.raises(UserError, match="Native structured output"):
        asyncio.run(model.request([], None, ModelRequestParameters(output_mode="native")))
    assert not runtime.calls
