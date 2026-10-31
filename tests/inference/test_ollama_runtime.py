import json
import logging
from dataclasses import replace
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src import config
from src.agents.response import STATEMENT_RESPONSE_SCHEMA
from src.inference import generation_progress, ollama_runtime
from src.inference.ollama_runtime import (
    OllamaRuntime,
    OllamaRuntimeConfig,
    OllamaRuntimeError,
)
from src.inference.progress import GenerationProgress, InferenceProgress, observe
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_document import StatementDocument


def document():
    return StatementDocument((StatementPage(1, "fictional statement"),))


def complete(**overrides):
    return {
        "done": True, "done_reason": "stop", "prompt_eval_count": 20, "eval_count": 5,
        **overrides,
    }


def server(monkeypatch, frames, *, status=200):
    body = b"".join(
        frame if isinstance(frame, bytes) else json.dumps(frame).encode() + b"\n"
        for frame in frames
    )
    response = BytesIO(body)
    response.status = status
    connection = MagicMock()
    connection.getresponse.return_value = response
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(ollama_runtime, "HTTPConnection", factory)
    return connection, factory


def test_http_error_preserves_ollama_context_rejection(monkeypatch):
    server(monkeypatch, [{"error": "request exceeds available context size (40960 tokens)"}], status=400)
    with pytest.raises(OllamaRuntimeError, match="HTTP 400: request exceeds available context size"):
        OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "instructions")


def test_stream_uses_same_page_text_and_publishes_only_completed_counts(monkeypatch, caplog):
    connection, factory = server(monkeypatch, [
        {"message": {"content": '{"amount":'}},
        {"message": {"content": '"12.34"}'}},
        complete(),
    ])
    progress = InferenceProgress()
    updates = []
    original = progress.generation

    def record(state):
        updates.append(state)
        original(state)

    monkeypatch.setattr(progress, "generation", record)
    with observe(progress), caplog.at_level(logging.INFO):
        result = OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "private instructions")

    assert result == '{"amount":"12.34"}'
    factory.assert_called_once_with("127.0.0.1", 11434, timeout=900)
    payload = json.loads(connection.request.call_args.kwargs["body"])
    assert payload["messages"] == [
        {"role": "system", "content": "private instructions"},
        {"role": "user", "content": "Statement page 1 (untrusted document content):\nfictional statement"},
    ]
    assert payload["model"] == "qwen3:4b-instruct"
    assert payload["think"] is False
    assert payload["truncate"] is False
    assert payload["shift"] is False
    assert payload["stream"] is True
    assert "format" not in payload
    assert payload["options"] == {"temperature": 0, "num_ctx": 40960, "num_predict": 16384}
    assert any(update.text and update.generated_tokens is None for update in updates)
    final = progress.snapshot().generation
    assert final.finished and final.eos
    assert final.input_tokens == 20 and final.generated_tokens == 5
    assert final.first_token_seconds is not None
    assert final.generated_characters == len(result)
    assert "private instructions" not in caplog.text
    assert "12.34" not in caplog.text
    connection.close.assert_called_once()


def test_list_models_returns_sorted_unique_installed_model_names(monkeypatch):
    connection, factory = server(monkeypatch, [{
        "models": [
            {"name": "qwen3:1.7b"},
            {"name": "qwen3:4b-instruct"},
            {"name": "qwen3:1.7b"},
            {"name": "qwen3-vl:8b", "capabilities": ["completion", "vision"]},
        ],
    }])
    monkeypatch.setattr(OllamaRuntime, "_model_details", lambda name: ollama_runtime._ModelDetails(
        capabilities=["completion", "vision", "thinking"],
        thinking={"values": [False, True]},
    ))

    assert OllamaRuntime.list_models() == ("qwen3-vl:8b", "qwen3:1.7b", "qwen3:4b-instruct")
    factory.assert_called_once_with("127.0.0.1", 11434, timeout=5)
    connection.request.assert_called_once_with("GET", "/api/tags")
    connection.close.assert_called_once()


@pytest.mark.parametrize(("capabilities", "thinking", "eligible"), [
    (["completion", "vision", "thinking"], {"values": [False, True]}, True),
    (["completion"], None, True),
    (["completion", "vision"], None, True),
    (["completion", "thinking"], {"values": ["low", "medium", "high"]}, False),
    (["completion", "thinking"], {"values": [True]}, False),
    (["completion", "thinking"], None, True),
    (["embedding"], {"values": [False]}, False),
    (["completion"], {"values": [False]}, True),
])
def test_model_eligibility_requires_completion_without_thinking(capabilities, thinking, eligible):
    details = ollama_runtime._ModelDetails(capabilities=capabilities, thinking=thinking)
    assert details.supports_non_thinking_completion() is eligible


def test_model_details_queries_show_metadata(monkeypatch):
    connection, _ = server(monkeypatch, [
        {"capabilities": ["completion", "vision"], "thinking": {"values": [False]}},
    ])
    assert OllamaRuntime._model_details("local-model").supports_non_thinking_completion()
    assert connection.request.call_args.args == ("POST", "/api/show")
    assert json.loads(connection.request.call_args.kwargs["body"]) == {"model": "local-model"}
    connection.close.assert_called_once()


@pytest.mark.parametrize(("frames", "message"), [
    ([{"message": {"content": "{}"}}], "without completion"),
    ([{"message": {"content": "{}"}}, complete(done_reason="length")], "normal completion"),
    ([complete(eval_count=16384)], "token limit"),
    ([complete(eval_count=None)], "omitted token counts"),
    ([complete(prompt_eval_count=None)], "omitted token counts"),
    ([{"message": {"content": "{}"}}, complete(prompt_eval_count=40000)], "insufficient context"),
    ([complete()], "empty response"),
    ([{"error": "sensitive server detail"}], "reported an inference error"),
    ([{"message": {"thinking": "not JSON"}}], "thinking despite"),
    ([b"not json\n"], "invalid stream event"),
    ([{"done": "yes"}], "invalid stream event"),
    ([{"message": {"content": "x" * (config.MAX_RESPONSE_BYTES + 1)}}], "oversized"),
])
def test_rejects_unsafe_or_incomplete_streams(monkeypatch, frames, message):
    connection, _ = server(monkeypatch, frames)
    progress = InferenceProgress()
    with observe(progress), pytest.raises(OllamaRuntimeError, match=message):
        OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "instructions")
    state = progress.snapshot().generation
    assert state.finished and not state.eos
    connection.close.assert_called_once()


def test_rejects_total_response_size_across_frames(monkeypatch):
    server(monkeypatch, [{"message": {"content": "x" * 1000}}] * 257)
    with pytest.raises(OllamaRuntimeError, match="oversized"):
        OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "instructions")


def test_http_error_is_actionable_and_closes_connection(monkeypatch):
    connection, _ = server(monkeypatch, [], status=404)
    with pytest.raises(OllamaRuntimeError, match="HTTP 404.*ollama list"):
        OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "instructions")
    connection.close.assert_called_once()


@pytest.mark.parametrize("failure", [ConnectionRefusedError(), TimeoutError()])
def test_connection_failure_does_not_accept_partial_data(monkeypatch, failure, caplog):
    connection, _ = server(monkeypatch, [])
    connection.getresponse.side_effect = failure
    with caplog.at_level(logging.INFO), pytest.raises(OllamaRuntimeError, match="No partial response"):
        OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "instructions")
    assert "input_tokens=None" in caplog.text
    connection.close.assert_called_once()


def test_deadline_is_total_not_reset_for_each_chunk(monkeypatch):
    runtime = OllamaRuntime(OllamaRuntimeConfig(max_time_seconds=5))
    monkeypatch.setattr(ollama_runtime, "perf_counter", lambda: 106)
    monkeypatch.setattr(generation_progress, "perf_counter", lambda: 106)
    with pytest.raises(TimeoutError):
        runtime._remaining(GenerationProgress(100, None))


def test_environment_settings(monkeypatch):
    monkeypatch.setenv("WT_OLLAMA_MODEL", "local-custom")
    monkeypatch.setenv("WT_OLLAMA_CONTEXT_TOKENS", "32768")
    monkeypatch.setenv("WT_OLLAMA_MAX_NEW_TOKENS", "4000")
    monkeypatch.setenv("WT_OLLAMA_MAX_TIME_SECONDS", "600")
    settings = OllamaRuntimeConfig.from_environment()
    assert settings.model_name == "local-custom"
    assert settings.context_tokens == 32768
    assert settings.max_new_tokens == 4000
    assert settings.max_time_seconds == 600


@pytest.mark.parametrize("settings", [
    {"model_name": " "}, {"max_time_seconds": 0}, {"max_new_tokens": 32769},
    {"context_tokens": 131073},
])
def test_invalid_settings_fail_explicitly(settings):
    with pytest.raises(ValidationError):
        OllamaRuntimeConfig(**settings)


def test_context_must_reserve_output_budget():
    with pytest.raises(ValueError, match="context must exceed"):
        OllamaRuntime(OllamaRuntimeConfig(context_tokens=8192))


@pytest.mark.parametrize("model_name", ["qwen3:4b-instruct", "qwen3-vl:4b"])
def test_rejects_empty_prompt_without_contacting_ollama(monkeypatch, model_name):
    factory = MagicMock()
    monkeypatch.setattr(ollama_runtime, "HTTPConnection", factory)
    runtime = OllamaRuntime(OllamaRuntimeConfig(model_name=model_name))
    with pytest.raises(ValueError, match="prompt must not be empty"):
        runtime.generate(document(), " ")
    factory.assert_not_called()


def test_statement_schema_and_currency_enum_are_sent_to_ollama(monkeypatch):
    connection, _ = server(monkeypatch, [
        {"message": {"content": "{}"}}, complete(),
    ])
    runtime = OllamaRuntime(OllamaRuntimeConfig(), output_schema=STATEMENT_RESPONSE_SCHEMA)
    runtime.generate(document(), "instructions")
    payload = json.loads(connection.request.call_args.kwargs["body"])
    assert payload["format"] == STATEMENT_RESPONSE_SCHEMA
    currencies = payload["format"]["$defs"]["BalanceOutput"]["prefixItems"][2]["enum"]
    assert "INR" in currencies and "INT" not in currencies


def test_repair_schema_overrides_statement_schema_for_one_request(monkeypatch):
    connection, _ = server(monkeypatch, [
        {"message": {"content": "{}"}}, complete(),
    ])
    runtime = OllamaRuntime(OllamaRuntimeConfig(), output_schema=STATEMENT_RESPONSE_SCHEMA)
    schema = {"type": "object", "properties": {"corrections": {"type": "array"}}}
    runtime.generate_structured(document(), "correction instructions", schema)
    assert json.loads(connection.request.call_args.kwargs["body"])["format"] == schema


def test_defaults_allow_output_above_previous_cap_and_fit_statement_context(monkeypatch):
    monkeypatch.delenv("WT_OLLAMA_MAX_NEW_TOKENS", raising=False)
    monkeypatch.delenv("WT_OLLAMA_MAX_TIME_SECONDS", raising=False)
    settings = OllamaRuntimeConfig.from_environment()
    assert settings.max_new_tokens == 16384
    assert settings.max_time_seconds == 900
    assert 14131 + settings.max_new_tokens <= settings.context_tokens
    server(monkeypatch, [{"message": {"content": "{}"}}, complete(eval_count=9000)])
    assert OllamaRuntime(settings).generate(document(), "instructions") == "{}"


def test_live_speed_counts_characters_not_bytes_and_excludes_first_chunk(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ollama_runtime, "perf_counter", lambda: now[0])
    monkeypatch.setattr(generation_progress, "perf_counter", lambda: now[0])
    frames = iter([
        {"message": {"content": "abc"}},
        {"message": {"content": "\u20acdef"}},
        complete(),
    ])

    class Response:
        def readline(self, limit):
            now[0] += 2
            return json.dumps(next(frames)).encode() + b"\n"

    updates = []
    progress = InferenceProgress()
    monkeypatch.setattr(progress, "generation", updates.append)
    runtime = OllamaRuntime(OllamaRuntimeConfig())
    result = runtime._read_stream(
        Response(), MagicMock(), GenerationProgress(100, None, generated_tokens=None), progress,
    )
    first, second = updates[:2]
    assert result == "abc\u20acdef"
    assert first.characters_per_second == 0
    assert second.generated_tokens is None
    assert second.generated_characters == 7
    assert second.first_chunk_characters == 3
    assert second.characters_per_second == 2
    assert replace(second, elapsed_seconds=6).characters_per_second == 1
    assert updates[-1].generated_tokens == 5
    assert updates[-1].eos
