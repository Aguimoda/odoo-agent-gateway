"""Plain text from Odoo field values (HTML fields, False for empty values)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

_BLOCK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def odoo_text(value: Any) -> str:
    """Odoo returns False for empty fields and HTML for rich-text fields; give plain text."""
    if not value or not isinstance(value, str):
        return ""
    extractor = _TextExtractor()
    extractor.feed(value)
    extractor.close()
    text = html.unescape("".join(extractor.parts))
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)
