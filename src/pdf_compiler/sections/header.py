"""Header / divider section: a centered title page with optional markdown body."""
from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.md_ast import make_md
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix, page_count_of
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import HeaderSection


@dataclass(frozen=True, slots=True)
class HeaderImpl:
    spec: HeaderSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-header"

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(),
            extra=f"header:{prefix}".encode(),
        )
        cached = ctx.cache.get(key)
        if cached is not None:
            return _result(cached, dest_name, self.spec)

        body_html = make_md().render(self.spec.body) if self.spec.body else None

        out = ctx.tmp_pdf("header")
        render_to_pdf(
            "header.html",
            {
                "title": self.spec.title,
                "subtitle": self.spec.subtitle,
                "body_html": body_html,
                "dest_name": dest_name,
                "page_size": defaults.page_size,
                "margin": defaults.margin,
            },
            out,
            base_url=ctx.project_root,
        )
        out = ctx.cache.put(key, out)
        return _result(out, dest_name, self.spec)


def _result(pdf, dest_name: str, spec: HeaderSection) -> CompiledSection:
    n = page_count_of(pdf)
    toc = (TocEntry(depth=1, label=spec.title, dest_name=dest_name, local_page=0),) if spec.in_toc else ()
    outline = (OutlineNode(title=spec.title, dest_name=dest_name, local_page=0),) if spec.in_toc else ()
    return CompiledSection(
        pdf_path=pdf, page_count=n,
        toc_entries=toc, outline=outline,
        destinations={dest_name: 0},
    )
