import json
from io import BytesIO

import pytest
from pdfplumber.page import Page

from src.agents.response import MissingStatementData
from src.inference.ollama_runtime import OllamaRuntime
from src.readers.statement_pdf import StatementPdf
from src.readers.statement_reader import read_statement
from src.service.entry_services import EntryServices
from tests.prompt_fixtures import STATEMENT_RESPONSE_EXAMPLE


def text_pdf(stream=b"BT /F1 12 Tf 30 100 Td (Example Bank Account 1234 SGD 10.25) Tj ET"):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
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


def test_embedded_text_is_read_without_rendering(monkeypatch, capsys):
    monkeypatch.setattr(
        Page, "to_image", lambda *args, **kwargs: pytest.fail("Text only"),
    )
    document = read_statement("statement.pdf", text_pdf())
    assert "Example Bank Account 1234 SGD 10.25" in document.to_model_text()
    assert capsys.readouterr().out == ""


def test_real_pdf_preserves_transaction_columns_and_missing_movements():
    stream = b"\n".join(
        f"BT /F1 8 Tf 1 0 0 1 {horizontal} {vertical} Tm ({text}) Tj ET".encode()
        for horizontal, vertical, text in (
            (10, 170, "Date"), (95, 170, "Description"),
            (180, 170, "Debit"), (240, 170, "Credit"), (310, 170, "Balance"),
            (310, 150, "90.00"), (95, 150, "Coffee"),
            (10, 150, "2024-01-01"), (180, 150, "10.00"),
            (240, 130, "5.00"), (10, 130, "2024-01-02"),
            (310, 130, "95.00"), (95, 130, "Refund"),
        )
    )
    document = read_statement("ledger.pdf", text_pdf(stream))
    lines = [line for line in document.pages[0].text.splitlines() if line.strip()]
    header, debit, credit = lines
    assert debit.index("10.00") == header.index("Debit")
    assert credit.index("5.00") == header.index("Credit")
    assert debit.index("90.00") == credit.index("95.00") == header.index("Balance")
    assert not debit[header.index("Credit"):header.index("Balance")].strip()
    assert not credit[header.index("Debit"):header.index("Credit")].strip()
    assert "2024-01-01" in debit and "Coffee" in debit
    assert "2024-01-02" in credit and "Refund" in credit
    assert "Statement page 1" in document.to_model_text()


def test_real_pdf_reaches_the_ollama_runtime(monkeypatch):
    calls = []

    def generate(runtime, document, prompt):
        assert "Example Bank Account 1234 SGD 10.25" in document.to_model_text()
        assert "no page images are provided" in prompt
        calls.append(runtime)
        return json.dumps(STATEMENT_RESPONSE_EXAMPLE)

    monkeypatch.setattr(OllamaRuntime, "generate", generate)
    result = EntryServices().preview("statement.pdf", text_pdf(), log_model_output=False)
    assert result.accounts
    assert len(calls) == 1


@pytest.mark.parametrize("texts", [(), ("",), ("readable first page", "")])
def test_scans_and_mixed_pdfs_have_actionable_error(monkeypatch, texts):
    monkeypatch.setattr(StatementPdf, "text", lambda statement: texts)
    with pytest.raises(ValueError, match="Run OCR"):
        read_statement("statement.pdf", b"pdf")


def test_missing_output_is_reported_without_retry(monkeypatch):
    calls = []

    def generate(*args):
        calls.append(args)
        return "{}"

    monkeypatch.setattr(OllamaRuntime, "generate", generate)
    with pytest.raises(MissingStatementData):
        EntryServices().preview(
            "statement.pdf", text_pdf(), log_model_output=False,
        )
    assert len(calls) == 1
