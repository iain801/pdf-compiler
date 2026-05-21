"""Markdown section: compile a .md file to PDF with heading-based ToC entries."""
from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.md_ast import Heading, first_h1_text, render_with_headings
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import MarkdownSection


@dataclass(frozen=True, slots=True)
class MarkdownImpl:
    spec: MarkdownSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        md_path = ctx.resolve(self.spec.path)
        md_text = md_path.read_text(encoding="utf-8")

        # Render markdown → HTML and extract headings (with injected anchors).
        html_body, headings = render_with_headings(md_text, id_prefix=prefix)
        title = self.spec.title or first_h1_text(headings) or md_path.stem
        # Section-level anchor: point at the top of the section's first page.
        section_dest = f"{prefix}-top"

        index_headers = (
            self.spec.index_headers
            if self.spec.index_headers is not None
            else defaults.index_headers
        )

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(md_path,),
            extra=f"markdown:{prefix}:{index_headers}".encode(),
        )
        cached = ctx.cache.get(key)
        out = cached if cached is not None else ctx.tmp_pdf("markdown")
        if cached is None:
            # Prepend an invisible anchor for the section as a whole.
            anchored = f'<span id="{section_dest}"></span>\n{html_body}'
            render_to_pdf(
                "markdown.html",
                {
                    "title": title,
                    "body_html": anchored,
                    "page_size": defaults.page_size,
                    "margin": defaults.margin,
                },
                out,
                base_url=ctx.project_root,
            )
            out = ctx.cache.put(key, out)

        # Heading anchors all label as page 0 of this section; WeasyPrint
        # stores true per-anchor positions inside the PDF, so click-through
        # still lands on the right page. The ToC page-number column will
        # show the section's first page for every heading — accepted trade-off
        # in v1 to avoid a second WeasyPrint pass to extract anchor offsets.
        toc_entries: list[TocEntry] = [
            TocEntry(depth=1, label=title, dest_name=section_dest, local_page=0),
        ]
        outline = [OutlineNode(title=title, dest_name=section_dest, local_page=0)]
        destinations: dict[str, int] = {section_dest: 0}

        if index_headers:
            # Skip the first H1 if it matches the section title to avoid dupes.
            walk = list(_iter_headings(headings))
            if walk and walk[0].level == 1 and walk[0].text == title:
                walk = walk[1:]
            for h in walk:
                toc_entries.append(TocEntry(
                    depth=h.level, label=h.text, dest_name=h.anchor_id, local_page=0,
                ))
                destinations.setdefault(h.anchor_id, 0)
            outline[0] = OutlineNode(
                title=title, dest_name=section_dest, local_page=0,
                children=_to_outline(headings, skip_first_h1_titled=title),
            )

        from pdf_compiler.sections._common import page_count_of
        n = page_count_of(out)
        return CompiledSection(
            pdf_path=out, page_count=n,
            toc_entries=tuple(toc_entries),
            outline=tuple(outline),
            destinations=destinations,
        )


def _iter_headings(hs: list[Heading]):
    for h in hs:
        yield h
        yield from _iter_headings(h.children)


def _to_outline(hs: list[Heading], *, skip_first_h1_titled: str | None) -> tuple[OutlineNode, ...]:
    out = []
    for i, h in enumerate(hs):
        if i == 0 and skip_first_h1_titled and h.level == 1 and h.text == skip_first_h1_titled:
            # Hoist its children up so we don't lose them.
            out.extend(_to_outline(h.children, skip_first_h1_titled=None))
            continue
        out.append(OutlineNode(
            title=h.text, dest_name=h.anchor_id, local_page=0,
            children=_to_outline(h.children, skip_first_h1_titled=None),
        ))
    return tuple(out)
