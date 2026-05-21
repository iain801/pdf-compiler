"""Title section: a one-page cover."""
from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix, page_count_of
from pdf_compiler.sections.base import CompiledSection
from pdf_compiler.spec import TitleSection


@dataclass(frozen=True, slots=True)
class TitleImpl:
    spec: TitleSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-title"

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(),
            extra=f"title:{prefix}".encode(),
        )
        cached = ctx.cache.get(key)
        if cached is not None:
            return _result(cached, dest_name, self.spec.in_toc, self.spec.title,
                            self.spec.front_matter)

        out = ctx.tmp_pdf("title")
        render_to_pdf(
            "title.html",
            {
                "title": self.spec.title,
                "subtitle": self.spec.subtitle,
                "author": self.spec.author,
                "date": str(self.spec.date) if self.spec.date else None,
                "page_size": defaults.page_size,
                "margin": defaults.margin,
            },
            out,
            base_url=ctx.project_root,
        )
        out = ctx.cache.put(key, out)
        return _result(out, dest_name, self.spec.in_toc, self.spec.title,
                       self.spec.front_matter)


def _result(pdf, dest_name, in_toc, label, front_matter) -> CompiledSection:
    from pdf_compiler.sections.base import OutlineNode, TocEntry
    n = page_count_of(pdf)
    toc = (TocEntry(depth=1, label=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    outline = (OutlineNode(title=label, dest_name=dest_name, local_page=0),) if in_toc else ()
    return CompiledSection(
        pdf_path=pdf, page_count=n,
        toc_entries=toc, outline=outline,
        front_matter=front_matter,
        destinations={dest_name: 0},
    )
