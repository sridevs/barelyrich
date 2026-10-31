import ast
import re
from pathlib import Path

import pytest

from src.agents.response import StatementResponseParser
from src.agents.statement_agent import StatementAgent
from src.inference.ollama_runtime import OllamaRuntime, OllamaRuntimeConfig
from src.models.dto.history_point import HistoryPoint
from src.models.entry.manual_balance import ManualBalance
from src.models.portfolio.portfolio import Portfolio
from src.providers.exchange_rates import FrankfurterExchangeRateProvider
from src.readers.statement_pdf import StatementPdf
from src.readers.statement_reader import read_statement
from src.repo.portfolio import PortfolioStore
from src.service.portfolio import PortfolioActions, PortfolioHistory
from src.ui.dashboard import render_portfolio, render_portfolio_layout
from src.ui.forms import render_account_forms
from src.ui.presentation import PortfolioPresenter
from src.ui.state import StatementReviewSession

PACKAGE = Path(__file__).resolve().parents[2] / "src"


def test_exception_constructors_do_not_embed_wording():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = ast.unparse(node.func)
            if not (name.endswith("Error") or name in {
                "ModelRetry", "MissingStatementData", "DuplicateStatementCurrency",
            }):
                continue
            if any(
                isinstance(part, ast.Constant) and isinstance(part.value, str)
                and (" " in part.value or isinstance(node.args[0], ast.JoinedStr))
                for part in ast.walk(node.args[0])
                if not isinstance(node.args[0], ast.Call)
            ):
                violations.append(f"{path.relative_to(PACKAGE)}:{node.lineno}: centralize exception wording")
    assert not violations, "\n".join(violations)


def test_logging_calls_use_central_templates():
    violations = []
    levels = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    for path in [PACKAGE.parent / "app.py", *PACKAGE.rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"LOGGER", "logger", "logging"}
                and node.func.attr in levels
            ):
                continue
            index = 1 if node.func.attr == "log" else 0
            template = node.args[index] if len(node.args) > index else next(
                (item.value for item in node.keywords if item.arg == "msg"), None,
            )
            if not (
                isinstance(template, ast.Attribute) and isinstance(template.value, ast.Name)
                and template.value.id in {"info", "warning", "error", "debug", "critical"}
                and (node.func.attr == "log" or template.value.id == {
                    "exception": "error",
                }.get(node.func.attr, node.func.attr))
            ):
                violations.append(f"{path.name}:{node.lineno}: use the matching log_messages severity module")
    assert not violations, "\n".join(violations)


def test_public_dataclasses_have_individually_named_modules():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        classes = [
            node for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
               and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass"
                or isinstance(decorator, ast.Name) and decorator.id == "dataclass"
                for decorator in node.decorator_list
            )
        ]
        for node in classes:
            filename = re.sub(r"(?<!^)(?=[A-Z])", "_", node.name).lower()
            if len(classes) != 1 or path.stem != filename:
                violations.append(f"{path.relative_to(PACKAGE)}: move {node.name} to {filename}.py")
    assert not violations, "\n".join(violations)


def _public_dataclasses(path):
    return [
        node for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_") and any(
            "dataclass" in ast.unparse(decorator) for decorator in node.decorator_list
        )
    ]


def _behaviours(node):
    return [
        item.name for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name != "__post_init__"
    ]


def test_dto_packages_hold_only_field_only_data_objects():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        in_dto = "dto" in path.relative_to(PACKAGE).parts
        for node in _public_dataclasses(path):
            if in_dto and _behaviours(node):
                violations.append(f"{path.relative_to(PACKAGE)}: {node.name} has behaviour; move it out of dto")
            elif not in_dto and not _behaviours(node):
                violations.append(f"{path.relative_to(PACKAGE)}: {node.name} is data-only; move it to a dto package")
    assert not violations, "\n".join(violations)


def test_production_function_bodies_are_at_most_fifteen_lines():
    violations = []
    for path in [PACKAGE.parent / "app.py", *PACKAGE.rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body_lines = node.end_lineno - node.body[0].lineno + 1
            if body_lines > 15:
                violations.append(f"{path.name}:{node.lineno}: {node.name} ({body_lines} lines)")
    assert not violations, "\n".join(violations)


def test_ui_display_calls_do_not_embed_copy_literals():
    display_commands = {
        "title", "subheader", "caption", "warning", "info", "error", "success",
        "text", "write", "button", "checkbox", "selectbox", "text_input", "date_input",
        "file_uploader", "form_submit_button", "expander", "spinner", "metric",
    }
    violations = []
    for path in (PACKAGE / "ui").glob("*.py"):
        if path.name == "ui_text.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            arguments = node.args[:1] if node.func.attr in display_commands else []
            arguments += [item.value for item in node.keywords if item.arg in {"help", "alt", "placeholder"}]
            if any(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in arguments):
                violations.append(f"{path.name}:{node.lineno}: move wording to ui/ui_text.py")
    assert not violations, "\n".join(violations)


def test_python_variables_have_descriptive_names():
    source_files = [
        PACKAGE.parent / "app.py",
        *PACKAGE.rglob("*.py"),
        *(PACKAGE.parent / "tests").rglob("*.py"),
    ]
    violations = []
    for source_file in source_files:
        for node in ast.walk(ast.parse(source_file.read_text())):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                name = node.id
            elif isinstance(node, ast.arg):
                name = node.arg
            else:
                continue
            if len(name) == 1 and name != "_":
                violations.append(f"{source_file.name}:{node.lineno}: {name}")
    assert not violations, "\n".join(violations)


def test_implementation_state_is_stored_in_private_fields():
    violations = []
    for source_file in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(source_file.read_text())):
            if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and not node.attr.startswith("_")
            ):
                violations.append(f"{source_file.relative_to(PACKAGE)}:{node.lineno}: {node.attr}")
    assert not violations, "\n".join(violations)


def test_inspection_properties_are_read_only(tmp_path):
    store = PortfolioStore(tmp_path / "portfolio.db")
    runtime = OllamaRuntime(OllamaRuntimeConfig())
    assert store.path == tmp_path / "portfolio.db"
    assert runtime.configuration.model_name
    with pytest.raises(AttributeError):
        store.path = tmp_path / "other.db"
    with pytest.raises(AttributeError):
        runtime.configuration = runtime.configuration


def imports(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("path", sorted((PACKAGE / "models").rglob("*.py")),
                         ids=lambda model_path: model_path.relative_to(PACKAGE / "models"))
def test_domain_models_do_not_depend_on_outer_layers(path):
    forbidden = (
        "src.repo", "src.service", "src.ui",
        "src.agents", "src.inference", "src.providers",
        "src.readers",
        "streamlit", "pandas", "sqlite3", "pydantic", "pydantic_ai",
    )
    assert not {module for module in imports(path) if module.startswith(forbidden)}


def test_portfolio_service_uses_the_repository_not_sqlite():
    modules = imports(PACKAGE / "service" / "portfolio.py")
    assert "src.repo.portfolio" in modules
    assert not modules.intersection({"sqlite3", "src.repo.db", "src.providers.csv"})


def test_manual_valuation_does_not_depend_on_ai():
    manual_ui = imports(PACKAGE / "ui" / "valuations.py")
    assert not any(
        module.startswith(("src.readers", "src.agents", "src.inference"))
        for module in manual_ui
    )
    assert (PACKAGE / "readers" / "csv_reader.py").is_file()
    pdf_reader = imports(PACKAGE / "readers" / "pdf_reader.py")
    assert "csv" not in pdf_reader
    assert "src.readers.csv_reader" not in pdf_reader


def test_layers_have_canonical_import_locations():
    assert all(cls.__module__.startswith("src.models.") for cls in (
        Portfolio, ManualBalance, HistoryPoint,
    ))
    assert PortfolioStore.__module__ == "src.repo.portfolio"
    assert all(cls.__module__.startswith("src.service.") for cls in (
        PortfolioActions, PortfolioHistory,
    ))
    assert all(component.__module__.startswith("src.ui.") for component in (
        render_portfolio, render_portfolio_layout, render_account_forms, PortfolioPresenter,
        StatementReviewSession,
    ))
    assert StatementResponseParser.__module__ == "src.agents.response"
    assert StatementAgent.__module__ == "src.agents.statement_agent"
    assert read_statement.__module__ == "src.readers.statement_reader"
    assert StatementPdf.__module__ == "src.readers.statement_pdf"
    assert OllamaRuntime.__module__ == "src.inference.ollama_runtime"
    assert FrankfurterExchangeRateProvider.__module__ == "src.providers.exchange_rates"


def test_reorganized_modules_have_only_canonical_package_paths():
    legacy_paths = (
        "dashboard.py", "forms.py", "sections.py", "presentation.py",
        "providers.py", "tiger.py", "exchange_rates.py",
        "statement_agent.py", "statement_response.py",
        "statement_documents.py", "statement_images.py", "transformers_runtime.py",
        "finance.py", "service/entry_state.py", "service/entry.py", "repo/contracts.py",
        "models/history", "ui/models", "inference/loaded_model.py", "inference/progress_snapshot.py",
        "inference/transformers_runtime.py", "inference/streaming.py", "inference/model_loader.py",
        "service/text_backend.py", "documents",
    )
    assert all(not (PACKAGE / path).exists() for path in legacy_paths)
    assert all(
        (PACKAGE / package / "__init__.py").is_file()
        for package in ("ui", "agents", "inference", "readers", "providers",
                        "models/dto", "inference/dto", "ui/dto")
    )


def test_statement_extraction_uses_runtime_adapter_not_legacy_agent():
    assert not (PACKAGE / "ollama_agent.py").exists()
    assert (PACKAGE / "inference" / "ollama_runtime.py").is_file()
    for path in PACKAGE.rglob("*.py"):
        assert "src.ollama_agent" not in imports(path)


def test_imports_are_not_nested_in_functions():
    for path in [*PACKAGE.rglob("*.py"), *(PACKAGE.parent / "tests").rglob("*.py")]:
        for scope in ast.walk(ast.parse(path.read_text())):
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert not any(
                    isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(scope)
                ), f"Move imports to the module header: {path}"
