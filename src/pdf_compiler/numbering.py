"""Page-number formatting (roman / arabic / none)."""
from __future__ import annotations

from pdf_compiler.spec import NumberingStyle

_ROMAN_PAIRS = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def to_roman(n: int) -> str:
    """Lower-case roman numerals; ``n`` must be ≥ 1."""
    if n < 1:
        raise ValueError("roman numerals are positive")
    out: list[str] = []
    for v, sym in _ROMAN_PAIRS:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


def format_page_number(n: int, style: NumberingStyle, *, front: bool) -> str:
    """Format a 1-based page number per the given style."""
    if style == "none":
        return ""
    if style == "roman":
        return to_roman(n)
    if style == "arabic":
        return str(n)
    raise ValueError(f"unknown numbering style: {style!r}")
