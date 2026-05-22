"""Image gallery section."""
from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.layout.pack import (
    autopack_layout,
    grid_layout,
    probe_image,
)
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix, page_count_of
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import ImagesSection


@dataclass(frozen=True, slots=True)
class ImagesImpl:
    spec: ImagesSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-images"

        paths = [ctx.resolve(img.path) for img in self.spec.images]
        captions = [interpolate(img.caption, ctx.vars) for img in self.spec.images]
        title = interpolate(self.spec.title, ctx.vars)
        infos = [probe_image(p, c) for p, c in zip(paths, captions)]

        if self.spec.layout == "grid":
            per_page = self.spec.per_page or 4
            pages_layout = grid_layout(infos, per_page)
        else:  # autopack
            pages_layout = autopack_layout(infos)

        # Convert to template data with file:// URLs (WeasyPrint resolves them).
        template_pages = []
        for pg in pages_layout:
            cells_ctx = []
            for cell in pg.cells:
                c = {
                    "path_url": cell.image.path.as_uri(),
                    "caption": cell.image.caption,
                    "row": cell.row, "col": cell.col,
                    "left_pct": cell.left_pct, "top_pct": cell.top_pct,
                    "width_pct": cell.width_pct, "height_pct": cell.height_pct,
                }
                cells_ctx.append(c)
            template_pages.append({"cells": cells_ctx, "rows": pg.rows, "cols": pg.cols})

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=tuple(paths),
            extra=f"images:{prefix}:{ctx.vars_hash}".encode(),
        )
        cached = ctx.cache.get(key)
        out = cached if cached is not None else ctx.tmp_pdf("images")
        if cached is None:
            render_to_pdf(
                "gallery.html",
                {
                    "title": title,
                    "dest_name": dest_name,
                    "pages": template_pages,
                    "captions": self.spec.captions,
                    "gallery_css": "",
                    "page_size": defaults.page_size,
                    "margin": defaults.margin,
                },
                out,
                base_url=ctx.project_root,
            )
            out = ctx.cache.put(key, out)

        n = page_count_of(out)
        label = title or "Gallery"
        toc = (
            (TocEntry(depth=1, label=label, dest_name=dest_name, local_page=0),)
            if self.spec.in_toc else ()
        )
        outline = (
            (OutlineNode(title=label, dest_name=dest_name, local_page=0),)
            if self.spec.in_toc else ()
        )
        return CompiledSection(
            pdf_path=out, page_count=n,
            toc_entries=toc, outline=outline,
            destinations={dest_name: 0},
        )
