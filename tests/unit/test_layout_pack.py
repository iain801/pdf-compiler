from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdf_compiler.layout.pack import (
    ImageInfo,
    autopack_layout,
    grid_layout,
    variable_row_heights,
)


def _img(w: int, h: int) -> ImageInfo:
    return ImageInfo(path=Path("x.png"), width=w, height=h)


def test_grid_layout_per_page_4():
    imgs = [_img(100, 100) for _ in range(10)]
    pages = grid_layout(imgs, per_page=4)
    assert len(pages) == 3
    assert len(pages[0].cells) == 4
    assert len(pages[1].cells) == 4
    assert len(pages[2].cells) == 2
    assert pages[0].cols == 2 and pages[0].rows == 2


def test_grid_layout_per_page_6():
    imgs = [_img(100, 100) for _ in range(6)]
    pages = grid_layout(imgs, per_page=6)
    assert len(pages) == 1
    # √6 ≈ 2.45 → cols = 2, rows = 3
    assert pages[0].cols == 2 and pages[0].rows == 3


def test_grid_layout_per_page_1():
    imgs = [_img(100, 100) for _ in range(3)]
    pages = grid_layout(imgs, per_page=1)
    assert [len(p.cells) for p in pages] == [1, 1, 1]


def test_grid_layout_per_page_invalid():
    with pytest.raises(ValueError):
        grid_layout([], per_page=0)


def test_autopack_empty():
    assert autopack_layout([]) == []


def test_autopack_no_overlap_within_page():
    imgs = [_img(800, 600), _img(800, 600), _img(800, 600), _img(800, 600)]
    pages = autopack_layout(imgs)
    for page in pages:
        rects = [
            (c.left_pct, c.top_pct, c.left_pct + c.width_pct, c.top_pct + c.height_pct)
            for c in page.cells
        ]
        # Pairwise non-overlap.
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax1, ay1, ax2, ay2 = rects[i]
                bx1, by1, bx2, by2 = rects[j]
                disjoint = (
                    ax2 <= bx1 + 1e-6 or bx2 <= ax1 + 1e-6 or ay2 <= by1 + 1e-6 or by2 <= ay1 + 1e-6
                )
                assert disjoint, f"overlap between {rects[i]} and {rects[j]}"


def test_autopack_all_within_page():
    imgs = [_img(800, 600) for _ in range(6)]
    for page in autopack_layout(imgs):
        for c in page.cells:
            assert 0 <= c.left_pct <= 100 + 1e-3
            assert 0 <= c.top_pct <= 100 + 1e-3
            assert c.left_pct + c.width_pct <= 100 + 1.0  # allow small fp slack
            assert c.top_pct + c.height_pct <= 100 + 1.0


@given(
    n=st.integers(min_value=1, max_value=30),
    aspect_num=st.integers(min_value=1, max_value=10),
    aspect_den=st.integers(min_value=1, max_value=10),
)
def test_autopack_property_no_self_overlap(n: int, aspect_num: int, aspect_den: int):
    imgs = [_img(aspect_num * 100, aspect_den * 100) for _ in range(n)]
    pages = autopack_layout(imgs)
    total = sum(len(p.cells) for p in pages)
    assert total == n


def test_grid_layout_no_overlap_within_page():
    imgs = [_img(100, 100) for _ in range(9)]
    pages = grid_layout(imgs, per_page=9)
    coords = [(c.row, c.col) for c in pages[0].cells]
    assert len(set(coords)) == 9


# --- variable_row_heights -------------------------------------------------- #


def test_variable_row_heights_sum_to_content_h():
    """Heights must sum exactly to the requested content height."""
    landscape = _img(1600, 900)
    portrait = _img(600, 900)
    heights = variable_row_heights([landscape, portrait], cols=1, content_h=684.0)
    assert len(heights) == 2
    assert abs(sum(heights) - 684.0) < 1e-6


def test_variable_row_heights_fills_proportionally():
    """Portrait image should get a taller row than landscape."""
    landscape = _img(1600, 900)  # aspect 1.78 → short row
    portrait = _img(600, 900)  # aspect 0.67 → tall row
    h_land, h_port = variable_row_heights([landscape, portrait], cols=1, content_h=684.0)
    assert h_port > h_land


def test_variable_row_heights_equal_for_same_aspect():
    """Images with identical aspect ratios get equal row heights."""
    imgs = [_img(100, 100), _img(200, 200)]  # both 1:1
    h0, h1 = variable_row_heights(imgs, cols=1, content_h=684.0)
    assert abs(h0 - h1) < 1e-6


def test_variable_row_heights_multi_col():
    """Two columns: each row height based on sum of row's aspects."""
    # Row 0: two landscape images (aspect 2.0 each) → sum 4.0 → short row
    # Row 1: two portrait images (aspect 0.5 each) → sum 1.0 → tall row
    land = _img(200, 100)
    port = _img(100, 200)
    h = variable_row_heights([land, land, port, port], cols=2, content_h=600.0)
    assert len(h) == 2
    assert abs(sum(h) - 600.0) < 1e-6
    assert h[1] > h[0]  # portrait row taller
