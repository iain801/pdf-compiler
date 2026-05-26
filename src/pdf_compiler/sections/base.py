"""Section protocol and shared dataclasses.

Each section type produces a :class:`CompiledSection` — a temp PDF on disk plus
metadata. Sections speak in *named destinations* (string keys), never in page
numbers. Page numbers are resolved only during final assembly so the two-pass
ToC needs no iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pdf_compiler.context import BuildContext

# Page indices in TocEntry/OutlineNode are LOCAL to the compiled section
# (0-based, relative to the section's own PDF). Assembly remaps them to
# global page indices.


@dataclass(frozen=True, slots=True)
class TocEntry:
    """One row in the table of contents."""

    depth: int  # 1 = top-level, 2 = subheading, ...
    label: str
    dest_name: str  # unique across the whole document
    local_page: int = 0  # 0-based index within the section's PDF


@dataclass(frozen=True, slots=True)
class OutlineNode:
    """One node in the PDF outline (bookmarks panel) tree."""

    title: str
    dest_name: str
    local_page: int = 0
    children: tuple[OutlineNode, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledSection:
    """A section that has been rendered to a temporary PDF on disk."""

    pdf_path: Path
    page_count: int
    toc_entries: tuple[TocEntry, ...] = ()
    outline: tuple[OutlineNode, ...] = ()
    front_matter: bool = False
    # Map of dest_name -> (local_page_index, x_y_optional). Assembly uses this
    # to install named destinations on the final, concatenated PDF.
    destinations: dict[str, int] = field(default_factory=dict)


class Section(Protocol):
    """Anything that knows how to compile itself to a CompiledSection."""

    def compile(self, ctx: BuildContext) -> CompiledSection: ...
