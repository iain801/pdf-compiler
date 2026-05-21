"""Embed pages from an existing PDF, with optional page-range selection,
rotation, outline preservation, and page-size regularization."""
from __future__ import annotations

from dataclasses import dataclass

import pikepdf

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.lengths import page_size_pt
from pdf_compiler.page_range import parse_page_range
from pdf_compiler.sections._common import SectionMeta, dest_prefix
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import PdfSection

# Exceptions we tolerate when an included PDF's outline is malformed.
_OUTLINE_OK_EXCEPTIONS = (pikepdf.PdfError, AttributeError, TypeError, IndexError, KeyError)


@dataclass(frozen=True, slots=True)
class PdfRefImpl:
    spec: PdfSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        src_path = ctx.resolve(self.spec.path)
        dest_name = f"{prefix}-pdf"

        regularize = (
            self.spec.regularize_pages
            if self.spec.regularize_pages is not None
            else defaults.regularize_pages
        )

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(src_path,),
            extra=f"pdf:{prefix}:reg={regularize}".encode(),
        )
        cached = ctx.cache.get(key)

        with pikepdf.open(src_path) as src:
            indices = parse_page_range(self.spec.pages, len(src.pages))
            local_for_src = {src_idx: local for local, src_idx in enumerate(indices)}

            if cached is None:
                out_path = ctx.tmp_pdf("pdfref")
                dst = pikepdf.Pdf.new()
                target_wh = page_size_pt(defaults.page_size) if regularize else None
                for i in indices:
                    page = src.pages[i]
                    if self.spec.rotate:
                        page.rotate(self.spec.rotate, relative=True)
                    if target_wh is None:
                        dst.pages.append(page)
                    else:
                        _append_regularized(dst, page, target_wh)
                dst.save(out_path)
                dst.close()
                out_path = ctx.cache.put(key, out_path)
            else:
                out_path = cached

            outline_children: tuple[OutlineNode, ...] = ()
            if self.spec.preserve_bookmarks:
                outline_children = _preserve_outline(src, local_for_src, prefix)

        title = self.spec.title or src_path.stem
        n_pages = len(indices)
        toc = (
            (TocEntry(depth=1, label=title, dest_name=dest_name, local_page=0),)
            if self.spec.in_toc else ()
        )
        outline = (
            (OutlineNode(title=title, dest_name=dest_name, local_page=0,
                          children=outline_children),)
            if self.spec.in_toc else outline_children
        )
        return CompiledSection(
            pdf_path=out_path, page_count=n_pages,
            toc_entries=toc, outline=outline,
            destinations={dest_name: 0},
        )


def _preserve_outline(
    src: pikepdf.Pdf,
    local_for_src: dict[int, int],
    prefix: str,
) -> tuple[OutlineNode, ...]:
    """Walk the source outline; emit only entries whose target survived selection."""
    try:
        with src.open_outline() as ol:
            return _convert_outline(ol.root, src, local_for_src, prefix, counter=[0])
    except _OUTLINE_OK_EXCEPTIONS:
        return ()


def _convert_outline(items, src, local_for_src, prefix, *, counter):
    out: list[OutlineNode] = []
    for item in items:
        src_page_idx = _resolve_outline_page(item, src)
        children = _convert_outline(item.children, src, local_for_src, prefix, counter=counter)
        if src_page_idx is None or src_page_idx not in local_for_src:
            # Page was filtered out — hoist any children so we don't lose them.
            out.extend(children)
            continue
        counter[0] += 1
        anchor = f"{prefix}-bm-{counter[0]:04d}"
        out.append(OutlineNode(
            title=str(item.title) if item.title else "",
            dest_name=anchor,
            local_page=local_for_src[src_page_idx],
            children=tuple(children),
        ))
    return tuple(out)


def _append_regularized(
    dst: pikepdf.Pdf,
    src_page: pikepdf.Page,
    target_wh: tuple[float, float],
) -> None:
    """Stamp ``src_page`` onto a fresh target-sized page in ``dst``.

    ``Page.add_overlay`` scales the source page to fit (preserving aspect)
    inside the given rectangle, so scanned-at-A3 originals end up the same
    on-screen size as letter-sized scans. Pages already at the target size
    pass through cheaply (the overlay is a no-op transformation).
    """
    tw, th = target_wh
    sw, sh = _page_size_pt(src_page)
    if abs(sw - tw) < 0.5 and abs(sh - th) < 0.5:
        dst.pages.append(src_page)
        return
    dst.add_blank_page(page_size=(tw, th))
    dst.pages[-1].add_overlay(src_page, rect=pikepdf.Rectangle(0, 0, tw, th))


def _page_size_pt(page: pikepdf.Page) -> tuple[float, float]:
    """Return the page's visual size in points, accounting for /Rotate."""
    mb = page.MediaBox
    w = float(mb[2]) - float(mb[0])
    h = float(mb[3]) - float(mb[1])
    rot = int(page.obj.get("/Rotate", 0)) % 360
    if rot in (90, 270):
        w, h = h, w
    return w, h


def _resolve_outline_page(item, src: pikepdf.Pdf) -> int | None:
    """Map a pikepdf OutlineItem to its 0-based source-PDF page index, if any."""
    try:
        dest = item.destination
        if isinstance(dest, int):
            return dest
        if dest is None:
            return None
        if hasattr(dest, "__getitem__"):  # [page, /XYZ, ...]
            page_obj = dest[0]
            for i, p in enumerate(src.pages):
                if p.obj.objgen == page_obj.objgen:
                    return i
    except _OUTLINE_OK_EXCEPTIONS:
        return None
    return None
