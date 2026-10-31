import csv
import json
from io import StringIO

import pytest

from src.agents.financial_validator import FinancialOutputValidator
from src.agents.response import StatementParsingError
from src.agents.statement_agent import StatementAgent
from src.agents.statement_chunks import StatementChunks
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_document import StatementDocument
from src.readers.statement_reader import read_statement


def response(amount="1", institution="Example Bank"):
    return json.dumps({
        "institution": {"name": institution} if institution else None,
        "accounts": [{
            "number": "1234", "account_type": "Savings",
            "balances": [["2025-11-18", "100", "SGD", None, amount, "Description"]],
        }],
    })


class Runtime:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, document, prompt):
        self.calls.append((document, prompt))
        return next(self.responses)


def document():
    return StatementDocument(tuple(
        StatementPage(number, text)
        for number, text in [(1, "Bank header"), (2, "Transaction"), (3, "Wrapped merchant")]
    ))


def test_default_multi_page_extraction_uses_whole_document():
    runtime = Runtime([response()])
    source = document()
    result = StatementAgent(runtime).parse(source)
    assert len(result.balances) == 1
    assert len(runtime.calls) == 1
    assert runtime.calls[0][0] is source
    assert "Page metadata: [1, 2, 3]" in runtime.calls[0][1]


def test_default_multi_page_extraction_rejects_empty_accounts():
    runtime = Runtime([
        json.dumps({"institution": {"name": "Example Bank"}, "accounts": []}),
        response(),
    ])
    source = document()
    with pytest.raises(StatementParsingError, match="Required statement data is missing"):
        StatementAgent(runtime).parse(source)
    assert len(runtime.calls) == 1
    assert all(call[0] is source for call in runtime.calls)


def test_large_statement_chunks_merge_and_carry_boundary_context():
    source = StatementDocument(tuple(
        StatementPage(page_number, f"Page {page_number} merchant")
        for page_number in range(1, 8)
    ))
    runtime = Runtime([response(), response(), response()])
    result = StatementAgent(runtime).parse(source)
    assert [[page.number for page in call[0].pages] for call in runtime.calls] == [
        [1, 2, 3], [4, 5, 6], [7],
    ]
    assert len(result.balances) == 3
    assert "Page 3 merchant" in runtime.calls[1][1]
    assert "Page 7 merchant" in runtime.calls[1][1]
    assert '"last_currency": "SGD"' in runtime.calls[1][1]


def test_each_chunk_gets_a_fresh_validator_from_the_injected_factory():
    source = StatementDocument(tuple(
        StatementPage(page_number, f"Page {page_number} merchant")
        for page_number in range(1, 8)
    ))
    validators = []

    def validator_factory(expected_transactions):
        validators.append(FinancialOutputValidator(expected_transactions))
        return validators[-1]

    StatementAgent(Runtime([response()] * 3), validator_factory=validator_factory).parse(source)
    assert len(validators) == len(set(map(id, validators))) == 3


def test_chunk_failure_reports_range_without_advancing():
    source = StatementDocument(tuple(
        StatementPage(page_number, "text") for page_number in range(1, 8)
    ))
    runtime = Runtime([response(), response(None), response(None)])
    with pytest.raises(StatementParsingError, match="Chunk pages 4-6 failed"):
        StatementAgent(runtime).parse(source)
    assert [[page.number for page in call[0].pages] for call in runtime.calls] == [
        [1, 2, 3], [4, 5, 6], [4, 5, 6],
    ]


def test_51_pages_are_chunked_by_page_count_regardless_of_text_length():
    source = StatementDocument(tuple(
        StatementPage(page_number, "x" * (page_number * 1000))
        for page_number in range(1, 52)
    ))
    chunks = list(StatementChunks(source))
    assert [page for chunk in chunks for page in chunk.pages] == list(source.pages)
    assert len(chunks) == 17
    assert all(len(chunk.pages) == 3 for chunk in chunks)


def test_csv_chunks_are_extracted_individually_and_merged_without_deduplication():
    text = b"Account,Date,Amount,Balance\n" + b"001234,2025-11-18,1,100\n" * 201
    source = read_statement("statement.csv", text)

    class CsvRuntime(Runtime):
        def generate(self, document, prompt):
            self.calls.append((document, prompt))
            rows = list(csv.reader(StringIO(document.pages[0].text)))[1:]
            output = json.loads(response())
            output["accounts"][0]["number"] = rows[0][0]
            output["accounts"][0]["balances"] = [
                [date, balance, "SGD", None, amount, "Description"]
                for _, date, amount, balance in rows
            ]
            return json.dumps(output)

    runtime = CsvRuntime([])
    result = StatementAgent(runtime).parse(source)
    assert len(result.balances) == 201
    assert [len(call[0].pages) for call in runtime.calls] == [1, 1, 1, 1, 1]
    assert "previous_tail\": \"\"" in runtime.calls[1][1]
    assert all(call[0].source_format == "csv" for call in runtime.calls)
    assert all(call[0].pages[0].text.startswith("Account,Date,Amount,Balance\n") for call in runtime.calls)
    assert '"number": "001234"' in runtime.calls[1][1]
    assert '"last_currency": "SGD"' in runtime.calls[1][1]


def rows_response(count, institution="Example Bank"):
    output = json.loads(response(institution=institution))
    output["accounts"][0]["balances"] *= count
    return json.dumps(output)


def test_csv_chunk_failure_returns_no_partial_result_and_skips_later_chunks():
    source = read_statement(
        "statement.csv", b"Date,Amount\n" + b"2025-11-18,1\n" * 101,
    )
    runtime = Runtime([rows_response(50), response(None), response(None)])
    with pytest.raises(StatementParsingError, match="Chunk pages 2-2 failed"):
        StatementAgent(runtime).parse(source)
    assert [call[0].pages[0].number for call in runtime.calls] == [1, 2, 2]


def test_csv_output_missing_rows_is_retried_with_expected_count():
    source = read_statement("statement.csv", b"Date,Amount\n" + b"2025-11-18,1\n" * 3)
    runtime = Runtime([rows_response(1), rows_response(3)])
    result = StatementAgent(runtime).parse(source)
    assert len(result.balances) == 3
    assert len(runtime.calls) == 2


def test_csv_output_with_missing_rows_is_rejected_instead_of_saved_partially():
    source = read_statement("statement.csv", b"Date,Amount\n" + b"2025-11-18,1\n" * 3)
    runtime = Runtime([rows_response(1), rows_response(1)])
    with pytest.raises(StatementParsingError, match="exactly 3 transaction records"):
        StatementAgent(runtime).parse(source)
