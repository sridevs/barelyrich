"""One parsed CSV statement record, keeping its exact source text."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CsvRecord:
    """Parsed cell values and the raw text they came from, which may span several quoted lines."""

    values: tuple[str, ...]
    raw: str

    @property
    def width(self) -> int:
        return len(self.values)

    def is_data_row(self, header_width: int) -> bool:
        return self.width == header_width and any(value.strip() for value in self.values)
