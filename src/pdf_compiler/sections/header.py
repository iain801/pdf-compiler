"""Header / divider section: a centered title page with optional markdown body."""

from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.md_ast import make_md
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import (
    SectionMeta,
    dest_prefix,
    simple_compiled_section,
)
from pdf_compiler.sections.base import CompiledSection
from pdf_compiler.spec import HeaderSection


@dataclass(frozen=True, slots=True)
class HeaderImpl:
    spec: HeaderSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-header"
        title = interpolate(self.spec.title, ctx.vars)
        subtitle = interpolate(self.spec.subtitle, ctx.vars)
        body = interpolate(self.spec.body, ctx.vars, markdown=True)

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(),
            extra=f"header:{prefix}:{ctx.vars_hash}".encode(),
        )
        cached = ctx.cache.get(key)
        if cached is None:
            body_html = make_md().render(body) if body else None
            out = ctx.tmp_pdf("header")
            render_to_pdf(
                "header.html",
                {
                    "title": title,
                    "subtitle": subtitle,
                    "body_html": body_html,
                    "dest_name": dest_name,
                    "subtoc_entries": None,
                    "page_size": defaults.page_size,
                    "margin": defaults.margin,
                },
                out,
                base_url=ctx.project_root,
            )
            out = ctx.cache.put(key, out)
        else:
            out = cached
        return simple_compiled_section(
            out,
            dest_name=dest_name,
            label=title,
            in_toc=self.spec.in_toc,
        )
