"""Final PDF assembly: concatenate, install named destinations, build outline.

Input is an ordered list of :class:`CompiledSection`. Output is a single PDF.
We never rewrite link annotations directly; instead we install a global
``/Catalog/Names/Dests`` name tree so any link with ``/A /S /GoTo /D (name)``
in any concatenated page resolves to the right destination automatically.
That's how WeasyPrint emits internal HTML anchor links — so the ToC's
``<a href="#dest">`` links become clickable across the whole document for
free.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from pdf_compiler.sections.base import CompiledSection, OutlineNode
from pdf_compiler.spec import Metadata


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    page_count: int
    # name -> 0-based global page index
    destinations: dict[str, int]
    # name -> 0-based global page index for ToC entries from all sections
    toc_destinations: dict[str, int]


def assemble(
    sections: list[CompiledSection],
    output_path: Path,
    metadata: Metadata,
) -> AssemblyResult:
    if not sections:
        raise ValueError("no sections to assemble")

    combined = pikepdf.Pdf.new()
    global_dests: dict[str, int] = {}
    toc_dests: dict[str, int] = {}
    outline_nodes: list[OutlineNode] = []
    page_offset = 0

    for sec in sections:
        with pikepdf.open(sec.pdf_path) as src:
            n = len(src.pages)
            if n != sec.page_count:
                raise AssemblyError(
                    f"{sec.pdf_path}: declared {sec.page_count} pages, found {n}"
                )
            combined.pages.extend(src.pages)
        for name, local in sec.destinations.items():
            if name in global_dests:
                raise AssemblyError(f"duplicate destination name: {name!r}")
            global_dests[name] = page_offset + local
        for entry in sec.toc_entries:
            toc_dests[entry.dest_name] = page_offset + entry.local_page
        for node in sec.outline:
            outline_nodes.append(_shift_outline(node, page_offset))
        page_offset += sec.page_count

    _install_named_destinations(combined, global_dests)
    _install_outline(combined, outline_nodes)
    _install_metadata(combined, metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path, linearize=False)
    combined.close()
    return AssemblyResult(
        page_count=page_offset,
        destinations=global_dests,
        toc_destinations=toc_dests,
    )


class AssemblyError(RuntimeError):
    """Something is structurally wrong with the sections handed to assembly."""


def _shift_outline(node: OutlineNode, page_offset: int) -> OutlineNode:
    # local_page becomes a *global* index after shifting.
    return copy.replace(
        node,
        local_page=node.local_page + page_offset,
        children=tuple(_shift_outline(c, page_offset) for c in node.children),
    )


def _install_named_destinations(pdf: pikepdf.Pdf, dests: dict[str, int]) -> None:
    """Install a flat ``/Dests`` name tree on ``/Catalog/Names``."""
    if not dests:
        return
    null = pikepdf.Object.parse(b"null")
    pairs: list = []
    for name in sorted(dests):
        page_idx = dests[name]
        page = pdf.pages[page_idx]
        # /XYZ with nulls means "preserve current zoom + position from top".
        dest_array = pikepdf.Array(
            [page.obj, pikepdf.Name("/XYZ"), null, null, null]
        )
        pairs.append(pikepdf.String(name))
        pairs.append(dest_array)
    leaf = pikepdf.Dictionary(Names=pikepdf.Array(pairs))
    names = pdf.Root.get("/Names")
    if names is None:
        names = pikepdf.Dictionary()
        pdf.Root["/Names"] = names
    names["/Dests"] = leaf


def _install_outline(pdf: pikepdf.Pdf, nodes: list[OutlineNode]) -> None:
    if not nodes:
        return
    with pdf.open_outline() as outline:
        outline.root.clear()
        for n in nodes:
            outline.root.append(_to_outline_item(n))


def _to_outline_item(node: OutlineNode) -> pikepdf.OutlineItem:
    # node.local_page has already been shifted to a global index by _shift_outline.
    item = pikepdf.OutlineItem(
        node.title,
        destination=node.local_page,
        page_location=pikepdf.PageLocation.XYZ,
    )
    for child in node.children:
        item.children.append(_to_outline_item(child))
    return item


def _install_metadata(pdf: pikepdf.Pdf, metadata: Metadata) -> None:
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        if metadata.title:
            meta["dc:title"] = metadata.title
        if metadata.author:
            meta["dc:creator"] = [metadata.author]
        if metadata.subject:
            meta["dc:description"] = metadata.subject
        if metadata.keywords:
            meta["pdf:Keywords"] = ", ".join(metadata.keywords)
    # Also write the classic info dict for older readers.
    info = pdf.docinfo
    if metadata.title:
        info["/Title"] = metadata.title
    if metadata.author:
        info["/Author"] = metadata.author
    if metadata.subject:
        info["/Subject"] = metadata.subject
    if metadata.keywords:
        info["/Keywords"] = ", ".join(metadata.keywords)
