
import logging
from time import perf_counter

from pydantic_ai import Agent, ModelRetry, PromptedOutput, UnexpectedModelBehavior
from pydantic_ai.usage import UsageLimits

from src.log_messages import error as error_messages
from src.log_messages import info, warning
from src.agents.local_model import LocalStatementModel, StatementInference
from src.agents.output import StatementOutput
from src.agents.response import (
    DOMAIN_RETRY_FEEDBACK, MAX_OUTPUT_CORRECTIONS, StatementParsingError,
)
from src.agents.statement_prompt import build_statement_prompt
from src.inference.configuration import TransformersRuntimeConfig
from src.inference.transformers_runtime import TransformersRuntime
from src.models.statements.errors import DuplicateStatementCurrency
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction


LOGGER = logging.getLogger(__name__)


class TransformersStatementAgent:
    """Extract locally from PDF text or images for human review."""

    def __init__(self, runtime: StatementInference, *, log_model_output: bool = False):
        self._runtime = runtime
        self._log_model_output = log_model_output

    @classmethod
    def from_text_environment(cls, *, log_model_output: bool = False) -> "TransformersStatementAgent":
        return cls(
            TransformersRuntime(TransformersRuntimeConfig.from_environment(model_kind="text")),
            log_model_output=log_model_output,
        )

    @classmethod
    def from_environment(
        cls, *, log_model_output: bool = False, model_name: str | None = None,
    ) -> "TransformersStatementAgent":
        return cls(
            TransformersRuntime.from_environment(model_name=model_name),
            log_model_output=log_model_output,
        )

    def parse(self, document: StatementDocument) -> StatementExtraction:
        started_at = perf_counter()
        try:
            extraction = self._extract(document)
            LOGGER.info(info.PREVIEW_READY)
            return extraction
        except StatementParsingError as error:
            if self._log_model_output:
                LOGGER.warning(warning.VALIDATION_FAILED, error)
            raise
        finally:
            LOGGER.info(
                info.INFERENCE_FINISHED,
                perf_counter() - started_at, len(document.pages),
            )

    def _extract(self, document: StatementDocument) -> StatementExtraction:
        model = LocalStatementModel(
            self._runtime, document, build_statement_prompt(document),
            log_model_output=self._log_model_output,
        )
        validation = _FinancialOutputValidator()
        agent = self._create_agent(model, validation)
        output = self._run_agent(agent, model.prompt, validation)
        try:
            return output.to_domain()
        except ValueError as error:
            raise StatementParsingError(str(error)) from error

    @staticmethod
    def _create_agent(
        model: LocalStatementModel, validation: "_FinancialOutputValidator",
    ) -> Agent[None, StatementOutput]:
        agent = Agent[None, StatementOutput](
            model,
            output_type=PromptedOutput(StatementOutput, template=False),
            retries=MAX_OUTPUT_CORRECTIONS,
            name="statement_extraction",
        )
        agent.output_validator(validation.validate)
        return agent

    @staticmethod
    def _run_agent(
        agent: Agent[None, StatementOutput], prompt: str, validation: "_FinancialOutputValidator",
    ) -> StatementOutput:
        try:
            return agent.run_sync(
                prompt, usage_limits=UsageLimits(request_limit=MAX_OUTPUT_CORRECTIONS + 1),
            ).output
        except UnexpectedModelBehavior:
            raise StatementParsingError(validation.failure_message()) from None


class _FinancialOutputValidator:
    def __init__(self):
        self._last_issue = ""

    def validate(self, candidate: StatementOutput) -> StatementOutput:
        try:
            return self._validate_output(candidate)
        except ModelRetry as error:
            self._last_issue = str(error)
            LOGGER.warning(warning.FINANCIAL_CORRECTION, self._last_issue)
            raise

    def failure_message(self) -> str:
        return (
            error_messages.STATEMENT_VALIDATION_EXHAUSTED
            + (error_messages.LAST_FINANCIAL_ISSUE.format(issue=self._last_issue) if self._last_issue else "")
        )

    @staticmethod
    def _validate_output(output: StatementOutput) -> StatementOutput:
        try:
            output.to_domain()
        except DuplicateStatementCurrency:
            raise ModelRetry(
                error_messages.DUPLICATE_CURRENCY_RETRY_FEEDBACK
            ) from None
        except ValueError:
            raise ModelRetry(DOMAIN_RETRY_FEEDBACK) from None
        return output
