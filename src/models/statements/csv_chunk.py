"""A model-sized group of CSV statement records under the repeated preamble and column header."""

from dataclasses import dataclass, replace

from src.log_messages import error as error_messages
from src.models.dto.statement_page import StatementPage
from src.models.statements.csv_record import CsvRecord

CSV_CHUNK_MAX_RECORDS = 50
CSV_CHUNK_MAX_CHARACTERS = 12_000


@dataclass(frozen=True)
class CsvChunk:
    """CSV records sent to the model together under the repeated header, counting full-width data rows."""

    header: str
    rows: tuple[str, ...] = ()
    count: int = 0

    def __post_init__(self):
        if len(self.header) > CSV_CHUNK_MAX_CHARACTERS:
            raise ValueError(error_messages.CSV_RECORD_TOO_LARGE)

    @property
    def text(self) -> str:
        return self.header + "".join(self.rows)

    def accepts(self, record: CsvRecord) -> bool:
        return not self.rows or (
            self.count < CSV_CHUNK_MAX_RECORDS
            and len(self.text) + len(record.raw) <= CSV_CHUNK_MAX_CHARACTERS
        )

    def with_record(self, record: CsvRecord, header_width: int) -> "CsvChunk":
        if len(self.header) + len(record.raw) > CSV_CHUNK_MAX_CHARACTERS:
            raise ValueError(error_messages.CSV_RECORD_TOO_LARGE)
        return replace(
            self, rows=(*self.rows, record.raw),
            count=self.count + record.is_data_row(header_width),
        )

    def page(self, number: int) -> StatementPage:
        return StatementPage(number, self.text, self.count)
