from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from pdf_compiler.numbering import format_page_number, to_roman


@pytest.mark.parametrize("n,expected", [
    (1, "i"), (2, "ii"), (3, "iii"), (4, "iv"), (5, "v"),
    (9, "ix"), (10, "x"), (40, "xl"), (50, "l"), (90, "xc"),
    (100, "c"), (400, "cd"), (500, "d"), (900, "cm"), (1000, "m"),
    (1999, "mcmxcix"),
])
def test_roman_values(n: int, expected: str):
    assert to_roman(n) == expected


def test_roman_zero_raises():
    with pytest.raises(ValueError):
        to_roman(0)


@given(n=st.integers(min_value=1, max_value=3999))
def test_roman_round_trip(n: int):
    # The string should not be empty and converting back should match.
    s = to_roman(n)
    assert s
    # Inverse via a tiny parser:
    table = {"m": 1000, "d": 500, "c": 100, "l": 50, "x": 10, "v": 5, "i": 1}
    total = 0
    prev = 0
    for ch in reversed(s):
        v = table[ch]
        if v < prev:
            total -= v
        else:
            total += v
        prev = v
    assert total == n


@pytest.mark.parametrize("style,n,expected", [
    ("arabic", 5, "5"),
    ("roman", 5, "v"),
    ("none", 5, ""),
])
def test_format(style: str, n: int, expected: str):
    assert format_page_number(n, style, front=True) == expected


def test_format_unknown_style():
    with pytest.raises(ValueError):
        format_page_number(1, "klingon", front=True)
