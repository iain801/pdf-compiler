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


def extract_named_dests(
    pdf_path: Path | str,
) -> tuple[int, dict[str, tuple[int, float | None, float | None]]]:
    """Read a PDF's page count and ``/Catalog/Names/Dests`` tree.

    Returns ``(page_count, {name: (page_idx, x, y)})`` using PDF user-space
    coordinates, in a single open of the file.

    WeasyPrint emits a ``[page /XYZ x y zoom]`` destination for every
    ``<span id="...">`` in the source HTML.  We read those back to learn
    the actual page + on-page position of each anchor so assembly can
    install destinations that land at the heading itself, not at the
    section's first page.
    """
    import pikepdf

    out: dict[str, tuple[int, float | None, float | None]] = {}
    with pikepdf.open(pdf_path) as pdf:
        page_index = {p.obj.objgen: i for i, p in enumerate(pdf.pages)}
        n_pages = len(page_index)
        names = pdf.Root.get("/Names")
        if names is None:
            return n_pages, out
        dests = names.get("/Dests")
        if dests is None:
            return n_pages, out
        # Flat name tree: [name, dest_array, name, dest_array, ...].
        entries = dests.get("/Names") or []
        for k in range(0, len(entries), 2):
            name = str(entries[k])
            arr = entries[k + 1]
            try:
                page_obj = arr[0]
                # A null/absent coordinate stays None so the assembler keeps
                # its "top of page" fallback rather than forcing it to 0
                # (which would scroll to the page's bottom-left edge).
                x = float(arr[2]) if arr[2] is not None else None
                y = float(arr[3]) if arr[3] is not None else None
                idx = page_index.get(page_obj.objgen) if page_obj is not None else None
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            if idx is None:
                continue
            out[name] = (idx, x, y)
    return n_pages, out


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
        pdf_path=pdf_path,
        page_count=n,
        toc_entries=toc,
        outline=outline,
        front_matter=front_matter,
        destinations={dest_name: 0},
    )
