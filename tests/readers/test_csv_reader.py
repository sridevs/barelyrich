import csv
from io import StringIO

import pytest

from src.models.statements.csv_chunk import (
    CSV_CHUNK_MAX_CHARACTERS,
    CSV_CHUNK_MAX_RECORDS,
)
from src.readers.statement_reader import read_statement


def read(text):
    return read_statement("statement.csv", text.encode("utf-8"))


def test_small_csv_is_preserved_verbatim():
    text = '\r\nAccount,Date,Description,Amount,Direction,Balance\r\n000123,2025-01-02,"Coffee, cake",5.00,DR,95.00'
    document = read(text)
    assert document.source_format == "csv"
    assert len(document.pages) == 1
    assert document.pages[0].text == text


def test_record_limit_repeats_header_and_preserves_every_record_in_order():
    header = "Account,Description,Amount,Direction\r\n"
    records = [
        f'000123,"Merchant {index}, ""quoted""\r\ncontinued",0.00,CR\r\n'
        for index in range(205)
    ]
    document = read(header + "".join(records))
    assert [page.number for page in document.pages] == [1, 2, 3, 4, 5]
    assert [page.record_count for page in document.pages] == [50, 50, 50, 50, 5]
    decoded = []
    for page in document.pages:
        assert page.text.startswith(header)
        rows = list(csv.reader(StringIO(page.text, newline="")))
        assert len(rows) - 1 <= CSV_CHUNK_MAX_RECORDS
        decoded.extend(rows[1:])
    assert decoded == list(csv.reader(StringIO(header + "".join(records), newline="")))[1:]
    assert "".join(page.text[len(header):] for page in document.pages) == "".join(records)


def test_character_limit_includes_header_and_does_not_split_long_records():
    header = "Description,Amount\n"
    record = '"' + "x" * 5900 + '",1\n'
    document = read(header + record * 5)
    assert len(document.pages) == 3
    assert all(len(page.text) <= CSV_CHUNK_MAX_CHARACTERS for page in document.pages)
    assert "".join(page.text[len(header):] for page in document.pages) == record * 5


@pytest.mark.parametrize("text", [
    "H" * (CSV_CHUNK_MAX_CHARACTERS + 1),
    "Description\n" + "x" * CSV_CHUNK_MAX_CHARACTERS,
])
def test_oversized_header_or_record_is_rejected(text):
    with pytest.raises(ValueError, match="12,000-character chunk limit"):
        read(text)


def test_invalid_quoted_record_is_rejected():
    with pytest.raises(ValueError, match="invalid quoting"):
        read('Description,Amount\n"Unclosed description,5\n')


def test_header_only_csv_stays_one_page():
    assert read("Date,Amount\n").pages[0].text == "Date,Amount\n"


def test_preamble_and_column_header_repeat_and_only_full_width_rows_are_counted():
    preamble = '"","","Account Statement"\n"Account No.","1912785962"\n\n'
    columns = '"Sl. No.","Date","Description","Debit","Credit","Balance","Dr / Cr"\n'
    rows = [f'"{index}","01-05-2026","UPI/{index}","10.00","","100.00","CR"\n' for index in range(1, 61)]
    footer = '\n"Closing Balance","as on 30/09/2026 INR 100.00"\n"Important Note:"\n'
    document = read(preamble + columns + "".join(rows) + footer)
    assert [page.record_count for page in document.pages] == [50, 10]
    assert all(page.text.startswith(preamble + columns) for page in document.pages)
    assert document.expected_transaction_count == 60
    assert document.pages[-1].text.endswith(footer)
