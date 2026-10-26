"""Text-first extraction with a visual retry only for missing output data."""

import logging

from src.log_messages import info
from src.agents.response import MissingStatementData
from src.documents.reader import StatementDocumentReader
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.service.statements import StatementAgent


LOGGER = logging.getLogger(__name__)


class HybridStatementAgent:
    def __init__(
        self, agent: StatementAgent, filename: str, content: bytes,
        *, text_agent: StatementAgent | None = None, password: str | None = None,
    ):
        self._agent = agent
        self._text_agent = text_agent or agent
        self._filename = filename
        self._content = content
        self._password = password

    def parse(self, document: StatementDocument) -> StatementExtraction:
        LOGGER.info(
            info.EXTRACTION_STARTED,
            "text model" if document.text_only else "vision model", len(document.pages),
        )
        if not document.text_only:
            return self._agent.parse(document)
        try:
            return self._text_agent.parse(document)
        except MissingStatementData:
            LOGGER.info(info.VISION_FALLBACK)
        visual_document = StatementDocumentReader().read(
            self._filename, self._content, self._password,
        )
        LOGGER.info(info.VISION_EXTRACTION_STARTED, len(visual_document.pages))
        return self._agent.parse(visual_document)
