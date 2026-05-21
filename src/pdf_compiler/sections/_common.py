"""Bits shared across section implementations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import Defaults


@dataclass(frozen=True, slots=True)
class SectionMeta:
    """Per-section info computed by the pipeline before compilation.

    ``index`` is the position in the spec (used to namespace destinations);
    ``defaults`` are the global defaults, possibly overridden by the section.
    """

    index: int
    defaults: Defaults


def dest_prefix(meta: SectionMeta | int) -> str:
    idx = meta if isinstance(meta, int) else meta.index
    return f"sec-{idx:04d}"


def page_count_of(pdf_path: Path | str) -> int:
    import pikepdf
    with pikepdf.open(pdf_path) as p:
        return len(p.pages)


def simple_compiled_section(
    pdf_path: Path,
    *,
    dest_name: str,
    label: str,
    in_toc: bool,
    front_matter: bool = False,
    page_count: int | None = None,
) -> CompiledSection:
    """Wrap a single-anchor section's rendered PDF as a CompiledSection.

    Used by title and header sections that contribute one ToC/outline entry
    pointing at their first page. ``page_count`` is read from the PDF when
    not supplied.
    """
    n = page_count if page_count is not None else page_count_of(pdf_path)
    toc = (TocEntry(depth=1, label=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    outline = (OutlineNode(title=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    return CompiledSection(
        pdf_path=pdf_path, page_count=n,
        toc_entries=toc, outline=outline,
        front_matter=front_matter,
        destinations={dest_name: 0},
    )
