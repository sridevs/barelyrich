from copy import deepcopy
from datetime import date
from io import BytesIO
import json
from unittest.mock import create_autospec

import pytest

from src.agents.local_model import StatementInference
from src.agents.response import StatementParsingError
from src.agents.statement_agent import TransformersStatementAgent
from src.agents.statement_prompt import STATEMENT_RESPONSE_EXAMPLE
from src.documents.images import StatementPdf
from src.documents.reader import StatementDocumentReader
from src.inference.errors import TransformersRuntimeError
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.service.entry import EntryServices
from src.service.hybrid import HybridStatementAgent


def complete_response():
    result = deepcopy(STATEMENT_RESPONSE_EXAMPLE)
    result["accounts"] = result["accounts"][:1]
    for account in result["accounts"]:
        for balance in account["balances"]:
            balance["as_of"] = date.today().isoformat()
    return result


def text_document():
    return StatementDocument((StatementPage(1, b"", "Example Bank\nAccount ****1234"),))


def text_pdf():
    stream = b"BT /F1 12 Tf 30 100 Td (Example Bank Account 1234 SGD 10.25) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, item in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + item + b"\nendobj\n")
    xref_offset = output.tell()
    output.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    )
    return output.getvalue()


def hybrid(runtime):
    return HybridStatementAgent(TransformersStatementAgent(runtime), "statement.pdf", b"pdf")


def test_embedded_text_is_read_without_rendering_images(monkeypatch):
    def forbid_render(*arguments):
        pytest.fail("Complete embedded text must not render images.")

    monkeypatch.setattr(StatementPdf, "render", forbid_render)
    document = StatementDocumentReader(prefer_text=True).read("statement.pdf", text_pdf())
    assert document.text_only
    assert document.pages[0].image == b""
    assert document.pages[0].number == 1
    assert "Example Bank Account 1234 SGD 10.25" in document.pages[0].text


def test_complete_text_result_does_not_use_images(monkeypatch, caplog):
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = json.dumps(complete_response())

    def forbid_render(*arguments):
        pytest.fail("Complete text output must not use vision.")

    monkeypatch.setattr(StatementPdf, "render", forbid_render)
    with caplog.at_level("INFO"):
        result = hybrid(runtime).parse(text_document())
    assert result.account_number == "****1234"
    assert len(result.balances) == 2
    assert runtime.generate.call_count == 1
    document, prompt = runtime.generate.call_args.args
    assert document.text_only
    assert "no page images are provided" in prompt
    assert "no extracted PDF text is provided" not in prompt
    assert "Account ****1234" not in caplog.text
    assert "Statement phase: text model extraction" in caplog.text
    assert "Statement generation: text model, attempt=1 started." in caplog.text
    assert "Statement phase: output validation (text model, attempt=1)" in caplog.text
    assert "preview ready for human review" in caplog.text


def test_evidence_free_savings_and_fixed_deposit_do_not_retry_or_load_vision(monkeypatch):
    response = deepcopy(STATEMENT_RESPONSE_EXAMPLE)
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = json.dumps(response)

    def forbid_render(*arguments):
        pytest.fail("Complete financial data without citations must not require vision.")

    monkeypatch.setattr(StatementPdf, "render", forbid_render)
    def forbid_vision(*arguments, **keywords):
        pytest.fail("Complete financial data must not load vision weights.")

    monkeypatch.setattr(TransformersStatementAgent, "from_environment", forbid_vision)
    result = hybrid(runtime).parse(text_document())
    assert [account.number for account in result.accounts] == ["****1234", "****5678"]
    assert [balance.currency for balance in result.balances] == ["SGD", "EUR", "SGD"]
    assert str(result.accounts[1].balances[0].balance) == "100.00"
    assert runtime.generate.call_count == 1


def test_hybrid_uses_different_text_and_vision_agents(monkeypatch, caplog):
    text_runtime = create_autospec(StatementInference, instance=True)
    text_runtime.generate.return_value = "{}"
    vision_runtime = create_autospec(StatementInference, instance=True)
    vision_runtime.generate.return_value = json.dumps(complete_response())
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"image",))
    router = HybridStatementAgent(
        TransformersStatementAgent(vision_runtime), "statement.pdf", b"pdf",
        text_agent=TransformersStatementAgent(text_runtime),
    )
    with caplog.at_level("INFO"):
        assert len(router.parse(text_document()).balances) == 2
    assert "Vision fallback: required text output data is missing" in caplog.text
    assert "Statement phase: vision model extraction" in caplog.text
    assert "Statement generation: vision model, attempt=1 started." in caplog.text
    assert "****1234" not in caplog.text
    assert text_runtime.generate.call_count == vision_runtime.generate.call_count == 1
    assert text_runtime.generate.call_args.args[0].text_only
    assert not vision_runtime.generate.call_args.args[0].text_only


@pytest.mark.parametrize("missing", [
    "institution", "account", "balance", "currency", "as_of",
    "empty_balances", "empty_account",
    "empty_response",
])
def test_missing_required_output_switches_once_to_full_visual_document(monkeypatch, missing):
    incomplete = complete_response()
    if missing == "institution":
        incomplete.pop("institution")
    elif missing == "account":
        incomplete.pop("accounts")
    elif missing in {"balance", "currency", "as_of"}:
        incomplete["accounts"][0]["balances"][0][missing] = ""
    elif missing == "empty_balances":
        incomplete["accounts"][0]["balances"] = []
    elif missing == "empty_account":
        incomplete["accounts"][0]["number"] = " "
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.side_effect = [
        "" if missing == "empty_response" else json.dumps(incomplete),
        json.dumps(complete_response()),
    ]
    renderer = create_autospec(StatementPdf.render, return_value=(b"first", b"second"))
    monkeypatch.setattr(StatementPdf, "render", renderer)
    result = hybrid(runtime).parse(text_document())
    assert len(result.balances) == 2
    assert runtime.generate.call_count == 2
    assert runtime.generate.call_args_list[0].args[0].text_only
    visual_document, prompt = runtime.generate.call_args_list[1].args
    assert not visual_document.text_only
    assert [page.number for page in visual_document.pages] == [1, 2]
    assert "no extracted PDF text is provided" in prompt
    renderer.assert_called_once()


def test_incorrect_but_present_data_is_left_to_user_review():
    result = complete_response()
    result["accounts"][0]["balances"][0]["balance"] = "999999.00"
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = json.dumps(result)
    assert str(hybrid(runtime).parse(text_document()).balances[0].balance) == "999999.00"
    assert runtime.generate.call_count == 1


@pytest.mark.parametrize("failure", ["malformed", "invalid_currency", "runtime"])
def test_nonmissing_errors_do_not_trigger_visual_fallback(monkeypatch, failure):
    def forbid_render(*arguments):
        pytest.fail("Only missing data should trigger vision.")

    monkeypatch.setattr(StatementPdf, "render", forbid_render)
    runtime = create_autospec(StatementInference, instance=True)
    if failure == "runtime":
        runtime.generate.side_effect = TransformersRuntimeError("Model unavailable")
    else:
        result = complete_response()
        result["accounts"][0]["balances"][0]["currency"] = "ZZZ"
        runtime.generate.return_value = "{" if failure == "malformed" else json.dumps(result)
    with pytest.raises((StatementParsingError, TransformersRuntimeError)):
        hybrid(runtime).parse(text_document())
    assert runtime.generate.call_count == (1 if failure == "runtime" else 4)


@pytest.mark.parametrize("texts", [("",), ("first page", "")])
def test_scan_or_mixed_pdf_with_missing_page_text_goes_directly_to_images(monkeypatch, texts):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: texts)
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"image",) * len(texts))
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = json.dumps(complete_response())
    document = StatementDocumentReader(prefer_text=True).read("statement.pdf", b"pdf")
    assert not document.text_only
    hybrid(runtime).parse(document)
    assert runtime.generate.call_count == 1
    assert not runtime.generate.call_args.args[0].text_only


def test_visual_failure_does_not_loop_back_to_text(monkeypatch):
    monkeypatch.setattr(StatementPdf, "render", lambda statement: (b"image",))
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = "{}"
    with pytest.raises(StatementParsingError):
        hybrid(runtime).parse(text_document())
    assert runtime.generate.call_count == 5
    assert sum(call.args[0].text_only for call in runtime.generate.call_args_list) == 1


def test_real_entry_flow_uses_text_first_with_default_models(monkeypatch):
    runtime = create_autospec(StatementInference, instance=True)
    runtime.generate.return_value = json.dumps(complete_response())
    monkeypatch.setattr(
        TransformersStatementAgent, "from_environment",
        lambda **options: TransformersStatementAgent(runtime),
    )
    monkeypatch.setattr(
        TransformersStatementAgent, "from_text_environment",
        lambda **options: TransformersStatementAgent(runtime),
    )
    result = EntryServices().preview(
        "statement.pdf", text_pdf(), log_model_output=False,
    )
    assert len(result.balances) == 2
    assert runtime.generate.call_args.args[0].text_only
