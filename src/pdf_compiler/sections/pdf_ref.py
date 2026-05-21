"""Embed pages from an existing PDF, with optional page-range selection,
rotation, and outline preservation."""
from __future__ import annotations

from dataclasses import dataclass

import pikepdf

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.page_range import parse_page_range
from pdf_compiler.sections._common import SectionMeta, dest_prefix
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import PdfSection


@dataclass(frozen=True, slots=True)
class PdfRefImpl:
    spec: PdfSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        src_path = ctx.resolve(self.spec.path)
        dest_name = f"{prefix}-pdf"

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(src_path,),
            extra=f"pdf:{prefix}".encode(),
        )
        cached = ctx.cache.get(key)
        out_path = cached if cached is not None else ctx.tmp_pdf("pdfref")
        outline_children: tuple[OutlineNode, ...] = ()

        if cached is None:
            with pikepdf.open(src_path) as src:
                total = len(src.pages)
                indices = parse_page_range(self.spec.pages, total)
                dst = pikepdf.Pdf.new()
                for i in indices:
                    page = src.pages[i]
                    if self.spec.rotate:
                        page.rotate(self.spec.rotate, relative=True)
                    dst.pages.append(page)
                dst.save(out_path)
                dst.close()
            out_path = ctx.cache.put(key, out_path)

        # Outline preservation runs from the freshly written PDF so we can
        # remap source page numbers to our local 0-based indices.
        if self.spec.preserve_bookmarks:
            with pikepdf.open(src_path) as src:
                total = len(src.pages)
                indices = parse_page_range(self.spec.pages, total)
                local_for_src = {src_idx: local
                                  for local, src_idx in enumerate(indices)}
                outline_children = _preserve_outline(src, local_for_src, prefix)

        title = self.spec.title or src_path.stem
        n_pages = len(parse_page_range(self.spec.pages, _count_pages(src_path)))
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


def _count_pages(p) -> int:
    with pikepdf.open(p) as pdf:
        return len(pdf.pages)


def _preserve_outline(
    src: pikepdf.Pdf,
    local_for_src: dict[int, int],
    prefix: str,
) -> tuple[OutlineNode, ...]:
    """Walk the source outline; emit only entries whose target survived selection."""
    try:
        with src.open_outline() as ol:
            return _convert_outline(ol.root, src, local_for_src, prefix, counter=[0])
    except Exception:
        # Some PDFs have malformed outlines — silently skip rather than abort.
        return ()


def _convert_outline(items, src, local_for_src, prefix, *, counter):
    out: list[OutlineNode] = []
    for item in items:
        # Resolve the item's destination page index in the source PDF.
        src_page_idx = _resolve_outline_page(item, src)
        children = _convert_outline(item.children, src, local_for_src, prefix, counter=counter)
        if src_page_idx is None or src_page_idx not in local_for_src:
            # Page was filtered out — keep children if any (hoisted).
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


def _resolve_outline_page(item, src: pikepdf.Pdf) -> int | None:
    try:
        dest = item.destination
        # destination can be int (page number), Array, or None (action-based).
        if isinstance(dest, int):
            return dest
        if dest is None:
            return None
        # Array form: [page, /XYZ, ...]
        if hasattr(dest, "__getitem__"):
            page_obj = dest[0]
            for i, p in enumerate(src.pages):
                if p.obj.objgen == page_obj.objgen:
                    return i
    except Exception:
        return None
    return None
