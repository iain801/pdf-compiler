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


def css_font_family(value: str | None) -> str | None:
    """Render a YAML ``font_family`` value as a safe CSS font-family.

    Single-name values get double-quoted (so ``Times New Roman`` works
    without needing nested YAML quotes). Comma-separated stacks are
    treated as ready-to-use CSS and pass through verbatim.
    """
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if "," in v or v.startswith(('"', "'")):
        return v
    # Single bare name: strip characters that can't appear in a real font
    # name and would otherwise break (or escape) the inline ``:root { … }``
    # declaration this value is injected into.
    safe = "".join(c for c in v if c not in '"\\;{}\n\r')
    return f'"{safe}"'
