"""Typed YAML spec models — pydantic v2 discriminated union over section types.

The :class:`Spec` is the root model. Sections are tagged by their ``type`` field;
pydantic dispatches to the correct subclass automatically.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


PageSize = Literal["letter", "legal", "a4", "a5", "tabloid"]
NumberingStyle = Literal["arabic", "roman", "none"]
NumberingPosition = Literal[
    "bottom-center",
    "bottom-left",
    "bottom-right",
    "top-center",
    "top-left",
    "top-right",
]
CaptionPlacement = Literal["below", "above", "overlay", "none"]
GalleryLayout = Literal["grid", "autopack"]


class PageNumbering(_Strict):
    # ``enabled`` controls whether numbers are *stamped onto* the rendered
    # pages. ToC always uses the same numbering scheme for labels regardless.
    enabled: bool = False
    front_matter: NumberingStyle = "roman"
    body: NumberingStyle = "arabic"
    position: NumberingPosition = "bottom-center"


class Defaults(_Strict):
    index_headers: bool = True
    page_size: PageSize = "letter"
    margin: str = "0.75in"
    page_numbering: PageNumbering = Field(default_factory=PageNumbering)
    # If true, embedded PDF pages are scaled & centered into a target-sized
    # page so scanned/oversized originals match the rest of the document.
    regularize_pages: bool = False
    # If true, form fields, sticky notes, highlights, etc. on embedded PDFs
    # are baked into the page content (link annotations are preserved).
    flatten_annotations: bool = False
    # Whether sections appear in the ToC by default. Applies to header, pdf,
    # and images sections; title sections always default to False.
    in_toc: bool = True
    # Whether embedded PDF outlines are preserved as nested ToC/outline
    # entries by default.
    preserve_bookmarks: bool = True


class Metadata(_Strict):
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: tuple[str, ...] = ()
    # Document date. Title sections fall back to this when their own `date`
    # is omitted. ``None`` means "no date"; omitting the field entirely
    # means "use today's date" (distinguished via ``model_fields_set``).
    date: _dt.date | str | None = None


# -- Section types ---------------------------------------------------------- #


class TitleSection(_Strict):
    type: Literal["title"] = "title"
    # All three of these fall back to the corresponding field on the
    # top-level ``metadata`` when omitted here. See sections/title.py.
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    # ``date`` resolution: section overrides metadata, both honour explicit
    # ``none`` (YAML null) as "disable", and the ultimate default — when
    # nothing is set anywhere — is today's date.
    date: _dt.date | str | None = None
    front_matter: bool = True
    # Whether the title appears as a ToC entry (usually no).
    in_toc: bool = False


class TocSection(_Strict):
    type: Literal["toc"] = "toc"
    title: str = "Table of Contents"
    depth: int = Field(3, ge=1, le=6)
    front_matter: bool = True


class HeaderSection(_Strict):
    type: Literal["header"] = "header"
    title: str
    subtitle: str | None = None
    body: str | None = None  # optional markdown shown below the title
    in_toc: bool | None = None  # None = inherit Defaults.in_toc
    # When true, this header is followed by a mini ToC of the entries from
    # every subsequent section, up to (but not including) the next header.
    subtoc: bool = False
    subtoc_depth: int = Field(3, ge=1, le=6)


class MarkdownSection(_Strict):
    type: Literal["markdown"] = "markdown"
    path: Path
    title: str | None = None  # else taken from first H1
    index_headers: bool | None = None  # None → inherit from defaults


class PdfSection(_Strict):
    type: Literal["pdf"] = "pdf"
    path: Path
    pages: str | None = None  # e.g. "1-10,15,20-"; None = all
    title: str | None = None
    rotate: Literal[0, 90, 180, 270] = 0
    preserve_bookmarks: bool | None = None  # None = inherit Defaults.preserve_bookmarks
    in_toc: bool | None = None  # None = inherit Defaults.in_toc
    # Override Defaults.regularize_pages for this section. None = inherit.
    regularize_pages: bool | None = None
    # Override Defaults.flatten_annotations for this section. None = inherit.
    flatten_annotations: bool | None = None


class ImageItem(_Strict):
    path: Path
    caption: str | None = None
    rotate: Literal[0, 90, 180, 270] = 0


class ImagesSection(_Strict):
    type: Literal["images"] = "images"
    title: str | None = None
    per_page: int | None = Field(None, ge=1, le=64)
    layout: GalleryLayout = "grid"
    captions: CaptionPlacement = "below"
    images: tuple[ImageItem, ...]
    in_toc: bool | None = None  # None = inherit Defaults.in_toc
    # Use variable row heights so every page fills edge-to-edge while keeping
    # image order.  Rows taller for portrait images, shorter for landscape.
    variable_heights: bool = False
    # Sort images by aspect ratio (widest first) AND use variable row heights.
    # Better packing than variable_heights alone but does not preserve order.
    optimize_packing: bool = False

    @model_validator(mode="after")
    def _nonempty(self):
        if not self.images:
            raise ValueError("images section needs at least one image")
        return self


SectionUnion = Annotated[
    TitleSection | TocSection | HeaderSection | MarkdownSection | PdfSection | ImagesSection,
    Field(discriminator="type"),
]


class Spec(_Strict):
    output: Path = Path("out.pdf")
    metadata: Metadata = Field(default_factory=Metadata)
    defaults: Defaults = Field(default_factory=Defaults)
    # User-defined ``{{ name }}`` substitutions. Builtins (today, year, ...)
    # are always available; entries here override or extend them.
    vars: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    sections: tuple[SectionUnion, ...]

    @model_validator(mode="after")
    def _nonempty(self):
        if not self.sections:
            raise ValueError("spec needs at least one section")
        return self
