"""Tiny length & page-size table used outside the HTML pipeline.

WeasyPrint handles all in-template sizing via CSS. These helpers exist for
the *post-render* steps (page-number stamping, page regularization) that
work in PDF user space (points).
"""
from __future__ import annotations

from pdf_compiler.spec import PageSize

_UNIT_TO_PT: dict[str, float] = {
    "pt": 1.0,
    "in": 72.0,
    "pc": 12.0,
    "mm": 72.0 / 25.4,
    "cm": 72.0 / 2.54,
    "px": 0.75,  # CSS 1px = 0.75pt
}

# 1pt = 1/72 inch. ANSI / ISO standard sizes.
PAGE_SIZE_PT: dict[PageSize, tuple[float, float]] = {
    "letter":  (612.0,  792.0),
    "legal":   (612.0, 1008.0),
    "a4":      (595.276, 841.890),
    "a5":      (419.528, 595.276),
    "tabloid": (792.0, 1224.0),
}


def parse_length_pt(value: str) -> float:
    """Parse a CSS-style length like ``"0.75in"`` or ``"54pt"`` into points.

    Raises ``ValueError`` on an unknown unit. A bare number is taken to be
    points (consistent with PDF user space).
    """
    s = value.strip().lower()
    for unit, factor in _UNIT_TO_PT.items():
        if s.endswith(unit):
            num = s[: -len(unit)].strip()
            return float(num) * factor
    return float(s)


def page_size_pt(name: PageSize) -> tuple[float, float]:
    return PAGE_SIZE_PT[name]
