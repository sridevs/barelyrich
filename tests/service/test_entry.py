from unittest.mock import create_autospec, patch

import pytest

from src.agents.statement_agent import TransformersStatementAgent
from tests.statement_fixtures import statement_extraction
from src.documents.images import StatementPdf
from src.inference.transformers_runtime import TransformersRuntime
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.service.entry import EntryServices


def test_statement_preview_uses_configured_vision_default_and_debug_flag(monkeypatch):
    extraction = statement_extraction()
    agent = create_autospec(TransformersStatementAgent, instance=True)
    agent.parse.return_value = extraction
    factory = create_autospec(TransformersStatementAgent.from_environment, return_value=agent)
    monkeypatch.setattr(TransformersStatementAgent, "from_environment", factory)
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"image",))
    monkeypatch.setattr(StatementPdf, "text", lambda statement: ("",))

    result = EntryServices().preview(
        "fictional.pdf", b"fictional", log_model_output=True,
    )

    assert result is extraction
    factory.assert_called_once_with(log_model_output=True)


def test_agent_factory_passes_selected_model_to_runtime(monkeypatch):
    runtime = create_autospec(TransformersRuntime, instance=True)
    factory = create_autospec(TransformersRuntime.from_environment, return_value=runtime)
    monkeypatch.setattr(TransformersRuntime, "from_environment", factory)

    agent = TransformersStatementAgent.from_environment(
        log_model_output=True, model_name="Qwen/Qwen3-VL-2B-Instruct",
    )

    with patch("src.agents.statement_agent.LocalStatementModel") as model:
        model.side_effect = ValueError("factory wiring probe")
        document = StatementDocument((StatementPage(1, b"image"),))
        with pytest.raises(ValueError, match="factory wiring probe"):
            agent.parse(document)
        assert model.call_args.args[0] is runtime
        assert model.call_args.kwargs["log_model_output"] is True
    factory.assert_called_once_with(model_name="Qwen/Qwen3-VL-2B-Instruct")
