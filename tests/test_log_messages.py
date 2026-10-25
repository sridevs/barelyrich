import ast
from pathlib import Path
from string import Formatter

import pytest
from pydantic import ValidationError

from src.agents.output import InstitutionOutput
from src.log_messages import error


PACKAGE = Path(__file__).resolve().parents[1] / "src"


def test_schema_validation_uses_central_missing_field_message(monkeypatch):
    monkeypatch.setattr(error, "MISSING_REQUIRED_FIELDS", "Required statement field is blank.")
    with pytest.raises(ValidationError, match="Required statement field is blank"):
        InstitutionOutput(name=" ")


def test_dynamic_error_templates_match_their_call_arguments():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format" and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "error_messages"
            ):
                continue
            template = getattr(error, node.func.value.attr)
            fields = {
                field for _, field, _, _ in Formatter().parse(template) if field is not None
            }
            if fields != {keyword.arg for keyword in node.keywords} or node.args:
                violations.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert not violations, "\n".join(violations)
