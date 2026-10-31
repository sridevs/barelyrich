"""Run local statement extraction, one model call per page chunk."""

import logging
from collections.abc import Callable
from time import perf_counter

from pydantic_ai import Agent, PromptedOutput, UnexpectedModelBehavior
from pydantic_ai.usage import UsageLimits

from src.agents.extraction_merger import ExtractionMerger
from src.agents.field_repair import FieldRepairInference
from src.agents.financial_validator import FinancialOutputValidator
from src.agents.local_model import LocalStatementModel, StatementRuntime
from src.agents.output import StatementOutput
from src.agents.response import (
    MAX_OUTPUT_CORRECTIONS,
    STATEMENT_RESPONSE_SCHEMA,
    StatementParsingError,
)
from src.agents.statement_chunks import StatementChunks
from src.agents.statement_prompt import build_statement_prompt
from src.inference.ollama_runtime import OllamaRuntime, OllamaRuntimeConfig
from src.inference.progress import report_stage
from src.log_messages import error as error_messages
from src.log_messages import info, warning
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction

LOGGER = logging.getLogger(__name__)
# Validators keep per-call state (expected count, last issue), so each extraction gets a fresh one.
ValidatorFactory = Callable[[int | None], FinancialOutputValidator]


class StatementAgent:
    """Extract statement text locally with Ollama for human review."""

    def __init__(
        self, runtime: StatementRuntime, *, log_model_output: bool = False,
        validator_factory: ValidatorFactory = FinancialOutputValidator,
    ):
        self._runtime = runtime
        self._log_model_output = log_model_output
        self._new_validator = validator_factory

    @classmethod
    def from_environment(
        cls, *, log_model_output: bool = False, model_name: str | None = None,
    ) -> "StatementAgent":
        runtime = OllamaRuntime(
            OllamaRuntimeConfig.from_environment(model_name=model_name),
            output_schema=STATEMENT_RESPONSE_SCHEMA,
        )
        return cls(FieldRepairInference(runtime, log_model_output=log_model_output), log_model_output=log_model_output)

    def parse(self, document: StatementDocument) -> StatementExtraction:
        started_at = perf_counter()
        try:
            chunks = StatementChunks(document)
            extraction = self._extract_chunks(chunks) if len(chunks) > 1 else self._extract(document)
            LOGGER.info(info.PREVIEW_READY)
            return extraction
        except StatementParsingError as error:
            if self._log_model_output:
                LOGGER.warning(warning.VALIDATION_FAILED, error)
            raise
        finally:
            LOGGER.info(info.INFERENCE_FINISHED, perf_counter() - started_at, len(document.pages))

    def _extract(self, document: StatementDocument, context: str = "") -> StatementExtraction:
        model = LocalStatementModel(
            self._runtime, document, build_statement_prompt(document) + context,
            log_model_output=self._log_model_output,
        )
        validator = self._new_validator(document.expected_transaction_count)
        output = self._run_agent(model, validator)
        try:
            return output.to_domain()
        except ValueError as error:
            raise StatementParsingError(str(error)) from error

    def _extract_chunks(self, chunks: StatementChunks) -> StatementExtraction:
        merger = ExtractionMerger()
        previous = None
        for index, chunk in enumerate(chunks):
            previous = self._extract_chunk(chunks, index, chunk, merger, previous)
            merger.add(previous, chunk)
        return merger.result()

    def _extract_chunk(
        self, chunks: StatementChunks, index: int, chunk: StatementDocument,
        merger: ExtractionMerger, previous: StatementExtraction | None,
    ) -> StatementExtraction:
        report_stage(f"Extracting chunk {index + 1}/{len(chunks)} (pages {chunk.page_range})")
        LOGGER.info(info.CHUNK_EXTRACTION, chunk.page_range, index + 1, len(chunks))
        try:
            return self._extract(chunk, chunks.context(index, merger.institution, previous))
        except ValueError as failure:
            raise StatementParsingError(error_messages.STATEMENT_CHUNK_FAILED.format(
                page_range=chunk.page_range, failure=failure,
            )) from failure

    @staticmethod
    def _run_agent(model: LocalStatementModel, validator: FinancialOutputValidator) -> StatementOutput:
        agent = Agent[None, StatementOutput](
            model, output_type=PromptedOutput(StatementOutput, template=False),
            retries=MAX_OUTPUT_CORRECTIONS, name="statement_extraction",
        )
        agent.output_validator(validator.validate)
        try:
            return agent.run_sync(
                model.prompt, usage_limits=UsageLimits(request_limit=MAX_OUTPUT_CORRECTIONS + 1),
            ).output
        except UnexpectedModelBehavior:
            raise StatementParsingError(validator.failure_message()) from None
