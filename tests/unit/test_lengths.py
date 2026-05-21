from __future__ import annotations

import pytest

from pdf_compiler.lengths import PAGE_SIZE_PT, page_size_pt, parse_length_pt


def test_inches():
    assert parse_length_pt("1in") == pytest.approx(72.0)
    assert parse_length_pt("0.75in") == pytest.approx(54.0)


def test_points_and_picas():
    assert parse_length_pt("36pt") == 36.0
    assert parse_length_pt("3pc") == 36.0


def test_metric():
    assert parse_length_pt("25.4mm") == pytest.approx(72.0)
    assert parse_length_pt("2.54cm") == pytest.approx(72.0)


def test_pixels():
    # CSS 1px = 0.75pt
    assert parse_length_pt("4px") == pytest.approx(3.0)


def test_bare_number_is_points():
    assert parse_length_pt("42") == 42.0


def test_whitespace_tolerated():
    assert parse_length_pt("  0.5 in ") == pytest.approx(36.0)


def test_letter_dimensions():
    w, h = page_size_pt("letter")
    assert (w, h) == (612.0, 792.0)


def test_all_known_sizes_have_entries():
    for name in ("letter", "legal", "a4", "a5", "tabloid"):
        assert name in PAGE_SIZE_PT
