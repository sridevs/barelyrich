"""Application services for importing and reviewing a statement."""

from dataclasses import dataclass, replace

from src.agents.statement_agent import StatementAgent
from src.models.statements.statement_extraction import StatementExtraction
from src.service.statements import StatementImportService


@dataclass(frozen=True)
class EntryServices:
    """External entry operations, injected into the shared forms."""

    ollama_model_name: str | None = None

    def with_ollama_model(self, model_name: str) -> "EntryServices":
        return replace(self, ollama_model_name=model_name)

    def preview(
        self, filename: str, content: bytes, *, log_model_output: bool,
        password: str | None = None,
    ) -> StatementExtraction:
        agent = StatementAgent.from_environment(log_model_output=log_model_output, model_name=self.ollama_model_name)
        return StatementImportService(agent).preview(filename, content, password)
