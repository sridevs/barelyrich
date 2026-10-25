"""Pydantic statement decoding and inference response limits."""


from pydantic import ValidationError

from src.log_messages import error as error_messages
from src.agents.output import StatementOutput
from src.config import MAX_RESPONSE_BYTES
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.models.text import is_missing_text


STATEMENT_RESPONSE_SCHEMA = StatementOutput.model_json_schema()
MAX_OUTPUT_CORRECTIONS = 3
DOMAIN_RETRY_FEEDBACK = error_messages.DOMAIN_RETRY_FEEDBACK


class StatementParsingError(ValueError):
    """A document could not be converted to validated balances."""


class MissingStatementData(StatementParsingError):
    """Text extraction omitted data required by the output schema."""


class StatementResponseParser:
    """Decode with Pydantic before converting to domain objects."""

    @classmethod
    def parse(cls, response: str, document: StatementDocument) -> StatementExtraction:
        cls.require_bounded_response(response)
        try:
            return StatementOutput.model_validate_json(response).to_domain()
        except ValidationError as error:
            raise StatementParsingError(str(error)) from None
        except ValueError as error:
            raise StatementParsingError(str(error)) from error

    @staticmethod
    def require_bounded_response(response: str) -> None:
        if (
            not isinstance(response, str) or is_missing_text(response)
            or len(response.encode("utf-8")) > MAX_RESPONSE_BYTES
        ):
            raise StatementParsingError(error_messages.MODEL_RETURNED_AN_INVALID_OR_OVERSIZED_RESPONSE)

    @staticmethod
    def require_present_fields(response: str) -> None:
        """Use schema errors only to route missing data, not judge correctness."""
        try:
            StatementOutput.model_validate_json(response)
        except ValidationError as error:
            if any(
                item["type"] == "missing"
                or is_missing_text(item.get("input"))
                or item["type"] == "too_short"
                for item in error.errors()
            ):
                raise MissingStatementData(error_messages.REQUIRED_STATEMENT_DATA_IS_MISSING_FROM_TEXT_OUTPUT) from None
