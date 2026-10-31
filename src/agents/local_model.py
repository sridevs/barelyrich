"""PydanticAI adapter for local text inference."""

import asyncio
import json
import logging

from pydantic_ai import ModelRetry
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings

from src.agents.field_repair import FieldRepairInference
from src.agents.response import (
    STATEMENT_RESPONSE_SCHEMA,
    MissingStatementData,
    StatementParsingError,
    StatementResponseParser,
)
from src.agents.statement_prompt import OUTPUT_RETRY_INSTRUCTIONS
from src.inference.ollama_runtime import OllamaRuntime
from src.inference.progress import report_stage
from src.log_messages import error, info, warning
from src.models.statements.statement_document import StatementDocument
from src.models.text import is_missing_text

LOGGER = logging.getLogger(__name__)
_OUTPUT_FIELDS = frozenset(STATEMENT_RESPONSE_SCHEMA["properties"]) | frozenset(
    field
    for definition in STATEMENT_RESPONSE_SCHEMA["$defs"].values()
    for field in definition.get("properties", {})
)


StatementRuntime = OllamaRuntime | FieldRepairInference


class LocalStatementModel(Model):
    def __init__(
        self, runtime: StatementRuntime, document: StatementDocument, prompt: str,
        *, log_model_output: bool = False,
    ):
        super().__init__(profile=ModelProfile(
            supports_tools=False,
            supports_json_schema_output=False,
            supports_json_object_output=False,
            supports_image_output=False,
        ))
        self._runtime = runtime
        self._document = document
        self._prompt = prompt
        self._log_model_output = log_model_output
        self._attempt = 0

    @property
    def prompt(self) -> str:
        return self._prompt

    @property
    def model_name(self) -> str:
        return "local-statement-ollama"

    @property
    def system(self) -> str:
        return "ollama"

    async def request(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _, model_request_parameters = self.prepare_request(model_settings, model_request_parameters)
        self._require_text_output(model_request_parameters)
        prompt = self._build_prompt(messages, model_request_parameters.prompted_output_instructions)
        response = await self._generate(prompt)
        report_stage("Validating model output")
        self._log_response(response)
        self._validate_response(response)
        return ModelResponse(
            parts=[TextPart(response)], model_name=self.model_name,
            provider_details=None, provider_response_id=None,
        )

    @staticmethod
    def _require_text_output(parameters: ModelRequestParameters) -> None:
        if (
            parameters.output_mode not in {"text", "prompted"}
            or parameters.function_tools
            or parameters.native_tools
            or parameters.output_tools
            or parameters.allow_image_output
        ):
            raise StatementParsingError(error.LOCAL_INFERENCE_TEXT_ONLY)

    async def _generate(self, prompt: str) -> str:
        self._attempt += 1
        phase = "text model"
        report_stage(f"{phase.capitalize()}: attempt {self._attempt}")
        LOGGER.info(info.GENERATION_STARTED, phase, self._attempt)
        response = await asyncio.to_thread(self._runtime.generate, self._document, prompt)
        LOGGER.info(info.OUTPUT_VALIDATION, phase, self._attempt)
        return response

    def _log_response(self, response: str) -> None:
        if self._log_model_output:
            LOGGER.warning(
                warning.SENSITIVE_MODEL_OUTPUT,
                json.dumps(
                    response if isinstance(response, str) else "<non-string model response>",
                    ensure_ascii=True,
                ),
            )

    def _build_prompt(self, messages: list[ModelMessage], instructions: str | None) -> str:
        """Replay the document instructions, never a previous model response."""
        prompt = self._prompt
        retry = next((
            part
            for message in reversed(messages) if isinstance(message, ModelRequest)
            for part in reversed(message.parts) if isinstance(part, RetryPromptPart)
        ), None)
        if retry:
            prompt += self._retry_prompt(retry)
        if instructions:
            prompt += "\n" + instructions
        return prompt

    @staticmethod
    def _retry_prompt(retry: RetryPromptPart) -> str:
        LOGGER.warning(
            warning.OUTPUT_RETRY,
            _safe_retry_errors(retry),
        )
        return OUTPUT_RETRY_INSTRUCTIONS + retry.model_response()

    def _validate_response(self, response: str) -> None:
        if is_missing_text(response):
            raise MissingStatementData(error.NO_STATEMENT)
        try:
            StatementResponseParser.require_bounded_response(response)
        except StatementParsingError as parsing_error:
            raise ModelRetry(str(parsing_error)) from None
        StatementResponseParser.require_present_fields(response)


def _safe_retry_errors(retry: RetryPromptPart) -> str:
    errors = []
    if isinstance(retry.content, list):
        for validation_error in retry.content:
            location = ".".join(
                str(part) if isinstance(part, int) or part in _OUTPUT_FIELDS else "<field>"
                for part in validation_error["loc"]
            )
            errors.append(f"{location}: {validation_error['type']}")
    return "; ".join(errors) or "financial or response validation"
