from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdf_compiler.page_range import PageRangeError, parse_page_range


def test_none_means_all_pages():
    assert parse_page_range(None, 5) == [0, 1, 2, 3, 4]


def test_empty_string_means_all_pages():
    assert parse_page_range("   ", 3) == [0, 1, 2]


def test_single_page():
    assert parse_page_range("3", 5) == [2]


def test_range():
    assert parse_page_range("2-4", 5) == [1, 2, 3]


def test_open_end():
    assert parse_page_range("3-", 5) == [2, 3, 4]


def test_open_start():
    assert parse_page_range("-3", 5) == [0, 1, 2]


def test_mixed():
    assert parse_page_range("1-2, 4, 5-", 6) == [0, 1, 3, 4, 5]


def test_whitespace_tolerated():
    assert parse_page_range(" 1 - 3 , 5 ", 5) == [0, 1, 2, 4]


def test_duplicates_preserved():
    # User asked for page 2 twice — keep it.
    assert parse_page_range("2,2,2", 5) == [1, 1, 1]


def test_out_of_range_raises():
    with pytest.raises(PageRangeError, match="out of range"):
        parse_page_range("1-10", 3)


def test_reversed_range_raises():
    with pytest.raises(PageRangeError, match="reversed"):
        parse_page_range("5-2", 10)


def test_zero_page_raises():
    with pytest.raises(PageRangeError, match="1-based"):
        parse_page_range("0", 5)


def test_too_many_dashes():
    with pytest.raises(PageRangeError, match="too many"):
        parse_page_range("1-2-3", 5)


def test_non_integer():
    with pytest.raises(PageRangeError, match="non-integer"):
        parse_page_range("a-b", 5)


def test_empty_token():
    with pytest.raises(PageRangeError, match="empty token"):
        parse_page_range("1,,3", 5)


def test_total_pages_must_be_positive():
    with pytest.raises(PageRangeError, match="positive"):
        parse_page_range("1", 0)


@given(
    total=st.integers(min_value=1, max_value=200),
    pages=st.lists(st.integers(min_value=1, max_value=200), min_size=1, max_size=20),
)
def test_property_single_pages_round_trip(total: int, pages: list[int]):
    """Picking any in-range pages gives 0-based indices in the same order."""
    in_range = [p for p in pages if p <= total]
    if not in_range:
        return
    expr = ",".join(str(p) for p in in_range)
    got = parse_page_range(expr, total)
    assert got == [p - 1 for p in in_range]


@given(
    total=st.integers(min_value=2, max_value=200),
    lo=st.integers(min_value=1, max_value=100),
    span=st.integers(min_value=0, max_value=100),
)
def test_property_ranges_are_inclusive(total: int, lo: int, span: int):
    hi = lo + span
    if hi > total:
        return
    got = parse_page_range(f"{lo}-{hi}", total)
    assert got == list(range(lo - 1, hi))
