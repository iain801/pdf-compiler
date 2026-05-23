"""Layout image galleries into pages.

Two modes:

  * ``grid``: fixed ``per_page`` images per page, on a grid whose shape is
    chosen to minimise wasted area for the average image aspect ratio.
  * ``autopack``: variable number of images per page packed into rows of
    similar height (Flickr "justified gallery"-style). The last row of each
    page is left ragged rather than stretched.

The output is a list of pages; each page is a list of cells with positions
in CSS ``%`` of page-content area. The gallery template applies these via
``style="left:X%; top:Y%; width:W%; height:H%"`` for ``autopack`` and via
``grid-template-{rows,columns}`` for ``grid``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import batched
from pathlib import Path

from PIL import Image


@dataclass(frozen=True, slots=True)
class ImageInfo:
    path: Path
    width: int
    height: int
    caption: str | None = None

    @property
    def aspect(self) -> float:  # w / h
        return self.width / max(self.height, 1)


@dataclass(frozen=True, slots=True)
class Cell:
    image: ImageInfo
    # Position is in % of page content area. For grid layouts row/col are set
    # and (left/top/width/height) are derived by CSS.
    row: int | None = None
    col: int | None = None
    left_pct: float | None = None
    top_pct: float | None = None
    width_pct: float | None = None
    height_pct: float | None = None


@dataclass(frozen=True, slots=True)
class Page:
    cells: tuple[Cell, ...]
    rows: int = 1
    cols: int = 1


def probe_image(path: Path, caption: str | None = None, *, rotate: int = 0) -> ImageInfo:
    """Return image info with corrected dimensions (EXIF + user rotation applied)."""
    from PIL import ImageOps  # noqa: PLC0415
    with Image.open(path) as im:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:  # noqa: BLE001
            pass
        w, h = im.size
    if rotate in (90, 270):
        w, h = h, w
    return ImageInfo(path=path, width=w, height=h, caption=caption)


def grid_layout(images: list[ImageInfo], per_page: int) -> list[Page]:
    """Fixed ``per_page`` images per page. Grid shape ≈ √per_page."""
    if per_page <= 0:
        raise ValueError("per_page must be >= 1")
    cols = max(1, round(math.sqrt(per_page)))
    rows = math.ceil(per_page / cols)
    pages: list[Page] = []
    for chunk in batched(images, per_page):
        cells = tuple(
            Cell(image=img, row=i // cols, col=i % cols)
            for i, img in enumerate(chunk)
        )
        pages.append(Page(cells=cells, rows=rows, cols=cols))
    return pages


def autopack_layout(
    images: list[ImageInfo],
    *,
    page_aspect: float = 8.5 / 11.0,
    target_rows_per_page: int = 3,
) -> list[Page]:
    """Justified-rows layout: cluster images into rows of similar height.

    Algorithm:
      - Greedily fill each row with images until the row's *justified* height
        (the height it would shrink to in order to span the page width) drops
        below a target.
      - Pack rows onto pages until vertical space runs out.

    All positions are in % of page content area. No overlap by construction.
    """
    if not images:
        return []
    if page_aspect <= 0:
        raise ValueError("page_aspect must be > 0")

    # Use "row height = 1.0 / target_rows_per_page" of page height as target.
    page_h = 1.0
    page_w = page_aspect
    target_h = page_h / target_rows_per_page

    rows: list[list[ImageInfo]] = []
    row: list[ImageInfo] = []
    row_aspect_sum = 0.0
    for img in images:
        row.append(img)
        row_aspect_sum += img.aspect
        # When justified to span the page width, the row's height is
        # page_w / sum_of_aspects.
        justified_h = page_w / row_aspect_sum
        if justified_h <= target_h:
            rows.append(row)
            row, row_aspect_sum = [], 0.0
    if row:
        rows.append(row)

    pages: list[Page] = []
    cur_cells: list[Cell] = []
    y = 0.0
    for r in rows:
        sum_ar = sum(img.aspect for img in r)
        h = min(page_w / sum_ar, target_h * 1.4)  # cap on tall rows
        if y + h > page_h and cur_cells:
            pages.append(Page(cells=tuple(cur_cells)))
            cur_cells, y = [], 0.0
        x = 0.0
        for img in r:
            w = img.aspect * h / page_aspect  # convert h→x-units via page_aspect
            # Express in %:
            cur_cells.append(Cell(
                image=img,
                left_pct=x * 100.0 / page_aspect,
                top_pct=y * 100.0,
                width_pct=w * 100.0,
                height_pct=h * 100.0,
            ))
            x += w * page_aspect  # advance in x-units (same as left_pct space)
        y += h
    if cur_cells:
        pages.append(Page(cells=tuple(cur_cells)))
    return pages


