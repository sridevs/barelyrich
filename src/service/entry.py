from src.models.statements.statement_extraction import StatementExtraction
from src.service.statements import StatementImportService
from src.agents.statement_agent import TransformersStatementAgent
from src.service.hybrid import HybridStatementAgent
from src.documents.reader import StatementDocumentReader


class EntryServices:
    """External entry operations, injected into the shared forms."""

    def preview(
        self, filename: str, content: bytes, *, log_model_output: bool,
    ) -> StatementExtraction:
        return StatementImportService(
            StatementDocumentReader(prefer_text=True),
            agent=HybridStatementAgent(
                TransformersStatementAgent.from_environment(
                    log_model_output=log_model_output,
                ),
                filename, content,
                text_agent=TransformersStatementAgent.from_text_environment(
                    log_model_output=log_model_output,
                ),
            ),
        ).preview(filename, content)
