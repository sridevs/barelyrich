"""Run local text inference through the loopback-only Ollama API."""

import json
import logging
from dataclasses import replace
from http.client import HTTPConnection, HTTPException, HTTPResponse
from socket import SHUT_RDWR, socket
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src import config
from src.inference.configuration import OllamaRuntimeConfig
from src.inference.generation_progress import GenerationProgress
from src.inference.progress import InferenceProgress, current_progress, report_stage
from src.log_messages import error
from src.models.statements.statement_document import StatementDocument

LOGGER = logging.getLogger(__name__)


def _interrupt_transport(transport: socket) -> None:
    try:
        transport.shutdown(SHUT_RDWR)
    except OSError:
        # Completion may close the socket concurrently with a stop request.
        pass


class OllamaRuntimeError(ValueError):
    """Ollama could not produce a complete local response."""


class _Message(BaseModel):
    model_config = ConfigDict(strict=True)
    content: str = ""
    thinking: str = ""


class _Frame(BaseModel):
    model_config = ConfigDict(strict=True)
    message: _Message = Field(default_factory=_Message)
    done: bool = False
    done_reason: str | None = None
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)
    error: str | None = None


class _InstalledModel(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)


class _ThinkingControls(BaseModel):
    model_config = ConfigDict(strict=True)
    values: list[bool | str]


class _ModelDetails(BaseModel):
    model_config = ConfigDict(strict=True)
    capabilities: list[str]
    thinking: _ThinkingControls | None = None

    def supports_non_thinking_completion(self) -> bool:
        if "completion" not in self.capabilities:
            return False
        if self.thinking:
            return any(value is False for value in self.thinking.values)
        # Older/custom model definitions may omit the thinking controls entirely.
        # Request think=false and retain the stream guard for those models.
        return True


class _ModelList(BaseModel):
    model_config = ConfigDict(strict=True)
    models: list[_InstalledModel]


class OllamaRuntime:
    """Keep prompts and output local, and reject interrupted or capped streams."""

    def __init__(self, configuration: OllamaRuntimeConfig, *, output_schema: dict | None = None):
        if configuration.context_tokens <= configuration.max_new_tokens:
            raise ValueError(error.OLLAMA_CONTEXT_TOO_SMALL)
        self._configuration = configuration
        self._output_schema = output_schema

    @property
    def configuration(self) -> OllamaRuntimeConfig:
        return self._configuration

    @staticmethod
    def list_models() -> tuple[str, ...]:
        try:
            models = _ModelList.model_validate_json(OllamaRuntime._fetch_model_list())
        except ValidationError:
            raise OllamaRuntimeError(error.OLLAMA_MODEL_LIST_INVALID) from None
        return tuple(
            name for name in sorted({model.name for model in models.models})
            if OllamaRuntime._model_details(name).supports_non_thinking_completion()
        )

    @staticmethod
    def _model_details(name: str) -> _ModelDetails:
        try:
            return _ModelDetails.model_validate_json(OllamaRuntime._fetch_model_list(name))
        except ValidationError:
            raise OllamaRuntimeError(error.OLLAMA_MODEL_LIST_INVALID) from None

    @staticmethod
    def _fetch_model_list(model_name: str | None = None) -> bytes:
        timeout = 5
        connection = HTTPConnection("127.0.0.1", 11434, timeout=timeout)
        try:
            return OllamaRuntime._read_model_list(connection, model_name)
        except (OSError, HTTPException) as failure:
            raise OllamaRuntimeError(
                error.OLLAMA_CONNECTION_FAILURE.format(seconds=timeout)
            ) from failure
        finally:
            connection.close()

    @staticmethod
    def _read_model_list(connection: HTTPConnection, model_name: str | None = None) -> bytes:
        _request_model_list(connection, model_name)
        with connection.getresponse() as response:
            return _read_model_list_response(response)

    def generate(self, document: StatementDocument, prompt: str) -> str:
        return self.generate_structured(document, prompt, self._output_schema)

    def generate_structured(
        self, document: StatementDocument, prompt: str, schema: dict | None,
    ) -> str:
        self._validate_generation(document, prompt)
        report_stage(f"Ollama: {self._configuration.model_name} (loading/prompt processing)")
        return self._generate(self._build_request(document, prompt, schema))

    def _validate_generation(self, document: StatementDocument, prompt: str) -> None:
        if not prompt.strip():
            raise ValueError(error.THE_STATEMENT_EXTRACTION_PROMPT_MUST_NOT_BE_EMPTY)

    def _build_request(
        self, document: StatementDocument, prompt: str, schema: dict | None,
    ) -> dict:
        request = self._chat_request(
            prompt, {"role": "user", "content": document.to_model_text()},
        )
        if schema:
            request["format"] = schema
        return request

    def _chat_request(self, prompt: str, user_message: dict) -> dict:
        return {
            "model": self._configuration.model_name,
            "messages": [
                {"role": "system", "content": prompt},
                user_message,
            ],
            "stream": True,
            "think": False,
            "truncate": False,
            "shift": False,
            "options": self._generation_options(),
        }

    def _generation_options(self) -> dict[str, int]:
        return {
            "temperature": 0,
            "num_ctx": self._configuration.context_tokens,
            "num_predict": self._configuration.max_new_tokens,
        }

    def _generate(self, request: dict) -> str:
        state = GenerationProgress(perf_counter(), None, generated_tokens=None)
        progress = current_progress() or InferenceProgress()
        progress.generation(state)
        connection = self._open_connection()
        try:
            return self._run_generation(connection, request, state, progress)
        except (OSError, HTTPException) as failure:
            progress.cancellation.check()
            raise OllamaRuntimeError(
                error.OLLAMA_CONNECTION_FAILURE.format(seconds=self._configuration.max_time_seconds)
            ) from failure
        finally:
            connection.close()
            self._finish_generation(progress, state)

    def _open_connection(self) -> HTTPConnection:
        return HTTPConnection(
            "127.0.0.1", 11434, timeout=self._configuration.max_time_seconds,
        )

    def _run_generation(
        self, connection: HTTPConnection, request: dict,
        state: GenerationProgress, progress: InferenceProgress,
    ) -> str:
        connection.connect()
        transport = connection.sock
        if transport is None:
            raise OllamaRuntimeError(error.OLLAMA_CONNECTION_UNAVAILABLE)
        with progress.cancellation.interrupt_with(lambda: _interrupt_transport(transport)):
            return self._request_stream(connection, transport, request, state, progress)

    @staticmethod
    def _finish_generation(progress: InferenceProgress, state: GenerationProgress) -> None:
        latest = progress.snapshot().generation
        if latest:
            state = latest
        progress.generation(state.finish())

    def _request_stream(
        self, connection: HTTPConnection, transport: socket, request: dict,
        state: GenerationProgress, progress: InferenceProgress,
    ) -> str:
        connection.request(
            "POST", "/api/chat", body=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        transport.settimeout(self._remaining(state))
        with connection.getresponse() as response:
            if response.status != 200:
                raise self._http_failure(response)
            result = self._read_stream(response, transport, state, progress)
            progress.cancellation.check()
            return result

    def _http_failure(self, response: HTTPResponse) -> OllamaRuntimeError:
        body = response.read(8192)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            payload = {}
        detail = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(detail, str) and detail.strip():
            return OllamaRuntimeError(error.OLLAMA_HTTP_ERROR_DETAIL.format(
                status=response.status, detail=detail[:2000],
            ))
        return OllamaRuntimeError(error.OLLAMA_HTTP_FAILURE.format(
            status=response.status, model_name=self._configuration.model_name,
        ))

    def _remaining(self, state: GenerationProgress) -> float:
        remaining = self._configuration.max_time_seconds - (perf_counter() - state.started_at)
        if remaining <= 0:
            raise TimeoutError(error.OLLAMA_GENERATION_DEADLINE_EXCEEDED)
        return remaining

    def _read_stream(
        self, response: HTTPResponse, transport: socket, state: GenerationProgress,
        progress: InferenceProgress,
    ) -> str:
        parts: list[str] = []
        size = 0
        while True:
            frame = self._read_frame(response, transport, state, progress)
            size += len(frame.message.content.encode("utf-8"))
            self._require_stream_size(size)
            parts.append(frame.message.content)
            state = self._record_frame(frame, state, progress)
            if frame.done:
                return self._complete_stream(frame, state, size, parts, progress)

    def _read_frame(
        self, response: HTTPResponse, transport: socket, state: GenerationProgress,
        progress: InferenceProgress,
    ) -> _Frame:
        progress.cancellation.check()
        transport.settimeout(self._remaining(state))
        line = response.readline(config.MAX_RESPONSE_BYTES + 1)
        progress.cancellation.check()
        return _validated_frame(line)

    def _record_frame(
        self, frame: _Frame, state: GenerationProgress, progress: InferenceProgress,
    ) -> GenerationProgress:
        text = frame.message.content
        if text and state.first_token_seconds is None:
            report_stage(f"Ollama: generating response ({self._configuration.model_name})")
        updated = state.with_chunk(text)
        progress.generation(updated)
        self._remaining(updated)
        return updated

    def _complete_stream(
        self, frame: _Frame, state: GenerationProgress, size: int, parts: list[str],
        progress: InferenceProgress,
    ) -> str:
        state = replace(
            state, input_tokens=frame.prompt_eval_count, generated_tokens=frame.eval_count,
        )
        progress.generation(state)
        self._require_complete(frame, size)
        progress.generation(replace(state, eos=True))
        return "".join(parts)

    @staticmethod
    def _require_stream_size(size: int) -> None:
        if size > config.MAX_RESPONSE_BYTES:
            raise OllamaRuntimeError(error.MODEL_RETURNED_AN_INVALID_OR_OVERSIZED_RESPONSE)

    def _require_complete(self, frame: _Frame, size: int) -> None:
        if frame.done_reason != "stop":
            raise OllamaRuntimeError(error.OLLAMA_ABNORMAL_STOP)
        if frame.eval_count is None or frame.prompt_eval_count is None:
            raise OllamaRuntimeError(error.OLLAMA_MISSING_COUNTS)
        if frame.eval_count >= self._configuration.max_new_tokens:
            raise OllamaRuntimeError(error.MODEL_OUTPUT_TOKEN_LIMIT)
        if frame.prompt_eval_count + self._configuration.max_new_tokens > self._configuration.context_tokens:
            raise OllamaRuntimeError(error.OLLAMA_INPUT_TOO_LARGE)
        if not size or frame.eval_count == 0:
            raise OllamaRuntimeError(error.THE_LOCAL_MODEL_RETURNED_AN_EMPTY_RESPONSE)


def _request_model_list(connection: HTTPConnection, model_name: str | None) -> None:
    if model_name is None:
        connection.request("GET", "/api/tags")
        return
    connection.request(
        "POST", "/api/show", body=json.dumps({"model": model_name}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _read_model_list_response(response: HTTPResponse) -> bytes:
    if response.status != 200:
        raise OllamaRuntimeError(error.OLLAMA_MODEL_LIST_HTTP_FAILURE.format(status=response.status))
    body = response.read(config.MAX_RESPONSE_BYTES + 1)
    if len(body) > config.MAX_RESPONSE_BYTES:
        raise OllamaRuntimeError(error.OLLAMA_MODEL_LIST_OVERSIZED)
    return body


def _validated_frame(line: bytes) -> _Frame:
    if not line:
        raise OllamaRuntimeError(error.OLLAMA_INCOMPLETE_STREAM)
    if len(line) > config.MAX_RESPONSE_BYTES:
        raise OllamaRuntimeError(error.MODEL_RETURNED_AN_INVALID_OR_OVERSIZED_RESPONSE)
    try:
        frame = _Frame.model_validate_json(line)
    except ValidationError:
        raise OllamaRuntimeError(error.OLLAMA_INVALID_EVENT) from None
    _require_frame_content(frame)
    return frame


def _require_frame_content(frame: _Frame) -> None:
    if frame.error is not None:
        raise OllamaRuntimeError(error.OLLAMA_INFERENCE_FAILURE)
    if frame.message.thinking:
        raise OllamaRuntimeError(error.OLLAMA_UNEXPECTED_THINKING)
