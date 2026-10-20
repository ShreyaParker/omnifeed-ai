import csv
import io
from collections.abc import Iterator
from typing import Any

from app.parsers.base import BaseParser


class CSVParser(BaseParser):
    """Parser for CSV files with utf-8-sig support."""

    def parse(self, content: bytes) -> Iterator[dict[str, Any]]:
        if not content or not content.strip():
            raise ValueError("CSV file is empty.")

        stream = io.TextIOWrapper(
            io.BytesIO(content),
            encoding="utf-8-sig",
            newline="",
        )
        try:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("CSV file has no header row.")
            for row in reader:
                yield dict(row)
        finally:
            stream.detach()
