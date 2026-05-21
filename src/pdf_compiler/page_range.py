"""Parse 1-based page-range strings like "1-10,15,20-" into 0-based indices.

Rules:
  - Comma-separated tokens.
  - Each token is either ``N`` (single page) or ``A-B`` (inclusive range).
  - ``A-`` (open end) means "from A to the last page".
  - ``-B`` (open start) means "from page 1 to B".
  - Whitespace around tokens is allowed.
  - Pages are 1-based in the input string and 0-based in the output list.
  - Out-of-bounds pages raise :class:`PageRangeError`.
  - Duplicate / overlapping pages are preserved in the order they appear,
    because users sometimes legitimately want to repeat a page.
"""
from __future__ import annotations


class PageRangeError(ValueError):
    """Invalid or out-of-bounds page-range expression."""


def parse_page_range(expr: str | None, total_pages: int) -> list[int]:
    """Return a list of 0-based page indices."""
    if total_pages <= 0:
        raise PageRangeError("total_pages must be positive")
    if expr is None or expr.strip() == "":
        return list(range(total_pages))

    result: list[int] = []
    for raw in expr.split(","):
        tok = raw.strip()
        if not tok:
            raise PageRangeError(f"empty token in page range: {expr!r}")
        if "-" in tok:
            lo_s, hi_s = tok.split("-", 1)
            if "-" in hi_s:
                raise PageRangeError(f"bad token {tok!r}: too many '-'")
            lo = _parse_int(lo_s, default=1, label="start", tok=tok)
            hi = _parse_int(hi_s, default=total_pages, label="end", tok=tok)
        else:
            lo = hi = _parse_int(tok, default=None, label="page", tok=tok)
        if lo < 1 or hi < 1:
            raise PageRangeError(f"pages are 1-based: {tok!r}")
        if lo > hi:
            raise PageRangeError(f"reversed range {tok!r} (start > end)")
        if hi > total_pages:
            raise PageRangeError(
                f"page {hi} out of range (document has {total_pages} pages)"
            )
        result.extend(range(lo - 1, hi))
    return result


def _parse_int(s: str, *, default: int | None, label: str, tok: str) -> int:
    s = s.strip()
    if s == "":
        if default is None:
            raise PageRangeError(f"missing {label} in {tok!r}")
        return default
    try:
        return int(s)
    except ValueError as e:
        raise PageRangeError(f"non-integer {label} in {tok!r}: {s!r}") from e
