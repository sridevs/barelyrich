"""Read CSV statements into pages without changing values or breaking quoted multiline records."""

import csv
from io import StringIO

from src import config
from src.log_messages import error as error_messages
from src.models.dto.statement_page import StatementPage
from src.models.statements.csv_chunk import CsvChunk
from src.models.statements.csv_record import CsvRecord
from src.models.statements.statement_document import StatementDocument


def read_csv(content: bytes, _: str | None = None) -> StatementDocument:
    """Decode UTF-8 CSV within the text budget; CSV files take no password."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(error_messages.CSV_ENCODING_REQUIRED) from error
    if not text.strip():
        raise ValueError(error_messages.CSV_STATEMENT_EMPTY)
    if len(text) > config.MAX_STATEMENT_TEXT_CHARACTERS:
        raise ValueError(error_messages.CSV_STATEMENT_TEXT_TOO_LARGE.format(
            max_characters=config.MAX_STATEMENT_TEXT_CHARACTERS,
        ))
    return StatementDocument(csv_pages(text), source_format="csv")


def csv_pages(text: str) -> tuple[StatementPage, ...]:
    """Chunk rows under the repeated preamble and column header, counting full-width data rows.

    The column header is the first widest record; narrower preamble and footer rows are not counted.
    """
    records = _records(text)
    width, header_end, header = _header(records)
    full_chunks: list[CsvChunk] = []
    chunk = CsvChunk(header)
    for record in records[header_end:]:
        if not chunk.accepts(record):
            full_chunks.append(chunk)
            chunk = CsvChunk(header)
        chunk = chunk.with_record(record, header_width=width)
    return tuple(item.page(number) for number, item in enumerate([*full_chunks, chunk], 1))


def _header(records: list[CsvRecord]) -> tuple[int, int, str]:
    if not any(record.values for record in records):
        raise ValueError(error_messages.CSV_STATEMENT_EMPTY)
    width = max(record.width for record in records)
    header_end = next(index for index, record in enumerate(records) if record.width == width) + 1
    return width, header_end, "".join(record.raw for record in records[:header_end])


def _records(text: str) -> list[CsvRecord]:
    lines = StringIO(text, newline="").readlines()
    reader = csv.reader(lines, strict=True)
    records = []
    start = 0
    try:
        for values in reader:
            records.append(CsvRecord(tuple(values), "".join(lines[start:reader.line_num])))
            start = reader.line_num
    except csv.Error as error:
        raise ValueError(error_messages.CSV_INVALID_RECORD) from error
    return records
