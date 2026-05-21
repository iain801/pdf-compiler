"""Small shared helpers."""
from __future__ import annotations

import re
import unicodedata


def slugify(text: str) -> str:
    """Lower-cased, hyphen-separated, ASCII-only slug. Empty input → 'x'."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_only = norm.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return s or "x"


def page_size_to_css(name: str) -> str:
    """Pass-through; WeasyPrint accepts these names natively."""
    return name
