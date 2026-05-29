"""ToC renderer.

The ToC is unique: we cannot compile it until every other section has been
compiled, because we need their page counts. The pipeline therefore runs a
"reserve / measure / render" sequence:

  1. Compile every non-ToC section, getting page counts and ToC entries.
  2. Reserve a placeholder N-page slot at each ToC position. We estimate N
     from entry count, render once, and assert the actual page count
     matches; if it overflows we widen and re-render (rare).
  3. Compute the global page number for every section, with the ToC
     contribution folded in.
  4. Render each ToC PDF with the resolved page labels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.md_ast import make_md
from pdf_compiler.numbering import format_page_number
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections.base import CompiledSection, TocEntry
from pdf_compiler.spec import HeaderSection, TocSection
from pdf_compiler.util import slugify

# Heuristic for how many ToC entries fit on one page. Tuned for our default
# CSS: ~36 entries on US letter with 0.75in margins. We over-allocate at
# first to leave headroom for long labels.
ENTRIES_PER_PAGE_HINT = 30


@dataclass(frozen=True, slots=True)
class TocLayout:
    """Where the ToC sits in the final document and how many pages it takes."""

    section_index: int  # index of the TocSection in spec.sections
    page_count: int  # how many pages this ToC occupies
    front_matter: bool


def estimate_toc_pages(n_entries: int) -> int:
    if n_entries <= 0:
        return 1
    return max(1, math.ceil(n_entries / ENTRIES_PER_PAGE_HINT))


def render_toc(
    ctx: BuildContext,
    spec: TocSection,
    entries: list[tuple[TocEntry, int]],
    *,
    out_path: Path,
    front_matter_pages: set[int],
) -> int:
    """Render the ToC PDF and return its page count.

    ``entries`` is a list of (TocEntry, global_page_index_0_based) tuples
    that are within ``spec.depth``.
    """
    defaults = ctx.defaults
    rendered_entries = _entries_with_labels(
        entries,
        spec.depth,
        defaults.page_numbering,
        front_matter_pages,
    )
    render_to_pdf(
        "toc.html",
        {
            "title": interpolate(spec.title, ctx.vars),
            "entries": rendered_entries,
            "page_size": defaults.page_size,
            "margin": defaults.margin,
            "font_family": defaults.font_family,
            "font_size": defaults.font_size,
        },
        out_path,
        base_url=ctx.project_root,
    )
    with pikepdf.open(out_path) as pdf:
        n = len(pdf.pages)
    _rewrite_toc_links(out_path, rendered_entries)
    return n


def render_subtoc_header(
    ctx: BuildContext,
    spec: HeaderSection,
    entries: list[tuple[TocEntry, int]],
    *,
    out_path: Path,
    front_matter_pages: set[int],
    dest_name: str,
) -> int:
    """Render a header page followed by a mini ToC of its scoped entries."""
    defaults = ctx.defaults
    rendered_entries = _entries_with_labels(
        entries,
        spec.subtoc_depth,
        defaults.page_numbering,
        front_matter_pages,
    )
    body = interpolate(spec.body, ctx.vars, markdown=True)
    body_html = make_md().render(body) if body else None
    render_to_pdf(
        "header.html",
        {
            "title": interpolate(spec.title, ctx.vars),
            "subtitle": interpolate(spec.subtitle, ctx.vars),
            "body_html": body_html,
            "dest_name": dest_name,
            "subtoc_entries": rendered_entries,
            "page_size": defaults.page_size,
            "margin": defaults.margin,
            "font_family": defaults.font_family,
            "font_size": defaults.font_size,
        },
        out_path,
        base_url=ctx.project_root,
    )
    with pikepdf.open(out_path) as pdf:
        n = len(pdf.pages)
    _rewrite_toc_links(out_path, rendered_entries)
    return n


def _entries_with_labels(
    entries: list[tuple[TocEntry, int]],
    max_depth: int,
    page_numbering,
    front_matter_pages: set[int],
) -> list[dict]:
    """Format (entry, global_page) pairs into the dicts the templates consume."""
    out: list[dict] = []
    last_fm = max(front_matter_pages, default=-1)
    for e, gp in entries:
        if e.depth > max_depth:
            continue
        if gp in front_matter_pages:
            label = format_page_number(gp + 1, page_numbering.front_matter, front=True)
        else:
            body_idx = gp - last_fm
            label = format_page_number(body_idx, page_numbering.body, front=False)
        out.append(
            {
                "depth": e.depth,
                "label": e.label,
                "dest_name": e.dest_name,
                "page_label": label,
            }
        )
    return out


def toc_compiled_section(
    pdf_path: Path,
    page_count: int,
    spec: TocSection,
    *,
    title: str | None = None,
) -> CompiledSection:
    """Wrap the rendered ToC into a CompiledSection for assembly.

    ``title`` is the interpolated title (vars resolved); defaults to the raw
    spec title when the caller hasn't substituted variables.
    """
    from pdf_compiler.sections.base import OutlineNode

    label = title or spec.title
    dest = f"toc-{slugify(label)}"
    return CompiledSection(
        pdf_path=pdf_path,
        page_count=page_count,
        toc_entries=(),
        outline=(OutlineNode(title=label, dest_name=dest, local_page=0),),
        front_matter=spec.front_matter,
        destinations={dest: 0},
    )


def subtoc_header_compiled_section(
    pdf_path: Path,
    page_count: int,
    spec: HeaderSection,
    dest_name: str,
    *,
    title: str | None = None,
    in_toc: bool = True,
) -> CompiledSection:
    """Wrap a deferred-rendered subtoc header into a CompiledSection."""
    from pdf_compiler.sections.base import OutlineNode

    label = title or spec.title
    toc = (TocEntry(depth=1, label=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    outline = (OutlineNode(title=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    return CompiledSection(
        pdf_path=pdf_path,
        page_count=page_count,
        toc_entries=toc,
        outline=outline,
        destinations={dest_name: 0},
    )


# ---------------------------------------------------------------------------
# Link annotation rewriter
# ---------------------------------------------------------------------------


def _rewrite_toc_links(pdf_path: Path, entries: list[dict]) -> None:
    """Replace self-referencing link annotations with cross-doc GoTo actions.

    WeasyPrint only emits a PDF link annotation when ``href="#id"`` has a
    matching ``id`` in the same document.  The templates add a dummy
    ``<span id="__toc_N">`` (or ``__stoc_N``) next to each entry so
    WeasyPrint *does* emit the annotation — but it points back to that
    span on the ToC page.  This function rewrites every such annotation to
    ``/GoTo (real-content-dest-name)`` so clicking it jumps to the right
    page in the assembled document.

    Matching is by the ``/Dest`` string already on each annotation, which
    encodes the entry index as ``__toc_N`` / ``__stoc_N``.  This handles
    the common case where a long entry straddles a page break and WeasyPrint
    emits two link annotations for the same row (both get rewritten to the
    same target, which is correct).
    """
    if not entries:
        return

    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        rewritten = 0
        for page in pdf.pages:
            for annot in page.obj.get("/Annots", []):
                if annot.get("/Subtype") != pikepdf.Name("/Link"):
                    continue
                dest = annot.get("/Dest")
                if dest is None:
                    continue
                dest_str = str(dest)
                # Parse index from "__toc_N" or "__stoc_N".
                for prefix in ("__toc_", "__stoc_"):
                    if dest_str.startswith(prefix):
                        try:
                            idx = int(dest_str[len(prefix) :])
                        except ValueError:
                            break
                        if 0 <= idx < len(entries):
                            annot["/A"] = pikepdf.Dictionary(
                                Type=pikepdf.Name("/Action"),
                                S=pikepdf.Name("/GoTo"),
                                D=pikepdf.String(entries[idx]["dest_name"]),
                            )
                            del annot["/Dest"]
                            rewritten += 1
                        break

        if rewritten:
            pdf.save(pdf_path)
