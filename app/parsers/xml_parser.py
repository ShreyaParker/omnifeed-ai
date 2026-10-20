from collections.abc import Iterator
from typing import Any
from defusedxml import ElementTree as ET

from app.parsers.base import BaseParser


class XMLParser(BaseParser):
    """Parser for XML files using defusedxml to extract <item> records."""

    def parse(self, content: bytes) -> Iterator[dict[str, Any]]:
        if not content or not content.strip():
            raise ValueError("XML file is empty.")

        try:
            root = ET.fromstring(content)
        except Exception as exc:
            raise ValueError(f"Invalid or unsafe XML: {exc}") from exc

        # Find all <item> elements under root (e.g. <items><item>...</item></items>)
        items = root.findall(".//item")
        if not items and root.tag.lower() == "item":
            items = [root]

        for element in items:
            row: dict[str, Any] = {}
            for child in list(element):
                row[child.tag] = child.text.strip() if child.text else ""
            yield row
