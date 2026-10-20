import json
from collections.abc import Iterator
from typing import Any

from app.parsers.base import BaseParser


class JSONParser(BaseParser):
    """Parser for JSON files handling top-level lists or dicts with an 'items' key."""

    def parse(self, content: bytes) -> Iterator[dict[str, Any]]:
        if not content or not content.strip():
            raise ValueError("JSON file is empty.")

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if isinstance(data, dict):
            if "items" in data:
                data = data["items"]
            else:
                data = [data]

        if not isinstance(data, list):
            raise ValueError(
                "JSON must be an array of objects or an object containing an 'items' key."
            )

        for row in data:
            if not isinstance(row, dict):
                yield {"_parse_error": "Each JSON record must be an object."}
            else:
                yield row
