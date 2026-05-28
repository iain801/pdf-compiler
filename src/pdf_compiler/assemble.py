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

from dataclasses import dataclass, replace
from pathlib import Path

import pikepdf

from pdf_compiler.lengths import parse_length_pt
from pdf_compiler.numbering import format_page_number
from pdf_compiler.sections.base import CompiledSection, OutlineNode
from pdf_compiler.spec import Metadata, NumberingStyle, PageNumbering


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
    *,
    page_numbering: PageNumbering | None = None,
    margin: str | None = None,
) -> AssemblyResult:
    if not sections:
        raise ValueError("no sections to assemble")

    combined = pikepdf.Pdf.new()
    global_dests: dict[str, int] = {}
    toc_dests: dict[str, int] = {}
    outline_nodes: list[OutlineNode] = []
    front_matter_pages: set[int] = set()
    page_offset = 0

    for sec in sections:
        with pikepdf.open(sec.pdf_path) as src:
            n = len(src.pages)
            if n != sec.page_count:
                raise AssemblyError(f"{sec.pdf_path}: declared {sec.page_count} pages, found {n}")
            combined.pages.extend(src.pages)
        for name, local in sec.destinations.items():
            if name in global_dests:
                raise AssemblyError(f"duplicate destination name: {name!r}")
            global_dests[name] = page_offset + local
        for entry in sec.toc_entries:
            toc_dests[entry.dest_name] = page_offset + entry.local_page
        for node in sec.outline:
            outline_nodes.append(_shift_outline(node, page_offset))
        if sec.front_matter:
            front_matter_pages.update(range(page_offset, page_offset + sec.page_count))
        page_offset += sec.page_count

    _install_named_destinations(combined, global_dests)
    _install_outline(combined, outline_nodes)
    _install_metadata(combined, metadata)
    if page_numbering is not None:
        _install_page_labels(combined, page_numbering, front_matter_pages)
        if page_numbering.enabled:
            margin_pt = parse_length_pt(margin) if margin else 54.0
            _stamp_page_numbers(combined, page_numbering, front_matter_pages, margin_pt)

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
    return replace(
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
        dest_array = pikepdf.Array([page.obj, pikepdf.Name("/XYZ"), null, null, null])
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


# PDF /S codes for the numbering styles we support. "none" is intentionally
# absent — a label dict with no /S has no numeric component, leaving the
# viewer to display empty page labels for that run.
_PDF_LABEL_STYLE: dict[NumberingStyle, str] = {
    "arabic": "/D",
    "roman": "/r",
}


def _install_page_labels(
    pdf: pikepdf.Pdf,
    config: PageNumbering,
    front_matter_pages: set[int],
) -> None:
    """Install a /Catalog/PageLabels number tree so PDF viewers display the
    document's logical page labels (e.g. ``i``, ``ii``, ``1``, ``2``) in
    their sidebar / page indicator, not just the sequential page index.

    A new /Nums entry is emitted at each style transition; viewers continue
    incrementing with the previous style until the next entry.
    """
    n_pages = len(pdf.pages)
    if n_pages == 0:
        return

    nums: list = []
    fm_counter = 0
    body_counter = 0
    prev_style: NumberingStyle | None = None

    for i in range(n_pages):
        if i in front_matter_pages:
            fm_counter += 1
            style = config.front_matter
            start = fm_counter
        else:
            body_counter += 1
            style = config.body
            start = body_counter
        if style == prev_style:
            continue
        entry = pikepdf.Dictionary()
        code = _PDF_LABEL_STYLE.get(style)
        if code is not None:
            entry["/S"] = pikepdf.Name(code)
        if start != 1:
            entry["/St"] = start
        nums.append(i)
        nums.append(entry)
        prev_style = style

    pdf.Root["/PageLabels"] = pikepdf.Dictionary(Nums=pikepdf.Array(nums))


_STAMP_FONT_KEY = "/PdfcPgNum"
_STAMP_FONT_SIZE = 10.0
# Average Helvetica glyph width as a fraction of font size — good enough for
# bottom-corner alignment of a 1–4 character page label.
_HELV_AVG_WIDTH_EM = 0.55


def _stamp_page_numbers(
    pdf: pikepdf.Pdf,
    config: PageNumbering,
    front_matter_pages: set[int],
    margin_pt: float,
) -> None:
    """Append a page-number text op to every page's content stream.

    A single Helvetica font resource (standard 14, no embedding) is shared
    across all pages by indirect reference, so the per-page overhead is one
    small content-stream object.
    """
    font_obj = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/Helvetica"),
        )
    )
    fm_counter = 0
    body_counter = 0
    for i, page in enumerate(pdf.pages):
        if i in front_matter_pages:
            fm_counter += 1
            label = format_page_number(fm_counter, config.front_matter, front=True)
        else:
            body_counter += 1
            label = format_page_number(body_counter, config.body, front=False)
        if not label:
            continue
        _stamp_page(page, label, font_obj, config.position, margin_pt)


def _stamp_page(
    page: pikepdf.Page,
    text: str,
    font_obj,
    position: str,
    margin_pt: float,
) -> None:
    mb = page.MediaBox
    w = float(mb[2]) - float(mb[0])
    h = float(mb[3]) - float(mb[1])
    est_w = len(text) * _STAMP_FONT_SIZE * _HELV_AVG_WIDTH_EM
    # Position number ~halfway into the margin so it sits clear of content.
    edge = min(margin_pt * 0.45, 30.0)

    vert, horiz = position.split("-")
    y = edge if vert == "bottom" else h - edge - _STAMP_FONT_SIZE
    if horiz == "left":
        x = margin_pt
    elif horiz == "right":
        x = w - margin_pt - est_w
    else:
        x = (w - est_w) / 2

    resources = page.obj.get("/Resources")
    if resources is None:
        resources = pikepdf.Dictionary()
        page.obj["/Resources"] = resources
    fonts = resources.get("/Font")
    if fonts is None:
        fonts = pikepdf.Dictionary()
        resources["/Font"] = fonts
    fonts[_STAMP_FONT_KEY] = font_obj

    # The existing content stream may have an unbalanced CTM (WeasyPrint
    # emits ``1 0 0 -1 0 H cm`` to use top-left HTML coordinates). Wrap
    # everything in q/Q so our stamp runs in PDF default user space.
    page.contents_add(b"q\n", prepend=True)
    stream = (
        f"Q q BT {_STAMP_FONT_KEY} {_STAMP_FONT_SIZE:g} Tf "
        f"0.25 0.25 0.25 rg {x:.2f} {y:.2f} Td "
        f"{_pdf_string(text)} Tj ET Q\n"
    ).encode("latin-1")
    page.contents_add(stream, prepend=False)


def _pdf_string(s: str) -> str:
    return (
        "("
        + s.translate(
            {
                ord("\\"): "\\\\",
                ord("("): "\\(",
                ord(")"): "\\)",
            }
        )
        + ")"
    )


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
