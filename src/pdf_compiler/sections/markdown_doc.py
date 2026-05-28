"""Markdown section: compile a .md file to PDF with heading-based ToC entries."""

from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.md_ast import Heading, first_h1_text, render_with_headings
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import (
    SectionMeta,
    dest_prefix,
    extract_named_dests,
    page_count_of,
)
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
        md_text = interpolate(md_path.read_text(encoding="utf-8"), ctx.vars, markdown=True)

        # Render markdown → HTML and extract headings (with injected anchors).
        html_body, headings = render_with_headings(md_text, id_prefix=prefix)
        title = interpolate(self.spec.title, ctx.vars) or first_h1_text(headings) or md_path.stem
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
            extra=f"markdown:{prefix}:{index_headers}:{ctx.vars_hash}".encode(),
        )
        cached = ctx.cache.get(key)
        out = cached if cached is not None else ctx.tmp_pdf("markdown")
        font_family = (
            self.spec.font_family if self.spec.font_family is not None else defaults.font_family
        )
        font_size = self.spec.font_size if self.spec.font_size is not None else defaults.font_size

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
                    "font_family": font_family,
                    "font_size": font_size,
                },
                out,
                base_url=ctx.project_root,
            )
            out = ctx.cache.put(key, out)

        # Read WeasyPrint's named destinations (one per heading id) to learn
        # each anchor's real page + on-page position. Without this every
        # heading would resolve to the section's first page in the assembled
        # PDF.
        ws_dests = extract_named_dests(out)

        def _page_for(name: str) -> int:
            info = ws_dests.get(name)
            return info[0] if info is not None else 0

        destination_coords: dict[str, tuple[float, float]] = {
            name: (x, y) for name, (_, x, y) in ws_dests.items()
        }

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
                local_page = _page_for(h.anchor_id)
                toc_entries.append(
                    TocEntry(
                        depth=h.level,
                        label=h.text,
                        dest_name=h.anchor_id,
                        local_page=local_page,
                    )
                )
                destinations.setdefault(h.anchor_id, local_page)
            outline[0] = OutlineNode(
                title=title,
                dest_name=section_dest,
                local_page=0,
                children=_to_outline(headings, ws_dests, skip_first_h1_titled=title),
            )

        n = page_count_of(out)
        return CompiledSection(
            pdf_path=out,
            page_count=n,
            toc_entries=tuple(toc_entries),
            outline=tuple(outline),
            destinations=destinations,
            destination_coords=destination_coords,
        )


def _iter_headings(hs: list[Heading]):
    for h in hs:
        yield h
        yield from _iter_headings(h.children)


def _to_outline(
    hs: list[Heading],
    ws_dests: dict[str, tuple[int, float, float]],
    *,
    skip_first_h1_titled: str | None,
) -> tuple[OutlineNode, ...]:
    out = []
    for i, h in enumerate(hs):
        if i == 0 and skip_first_h1_titled and h.level == 1 and h.text == skip_first_h1_titled:
            # Hoist its children up so we don't lose them.
            out.extend(_to_outline(h.children, ws_dests, skip_first_h1_titled=None))
            continue
        page = ws_dests[h.anchor_id][0] if h.anchor_id in ws_dests else 0
        out.append(
            OutlineNode(
                title=h.text,
                dest_name=h.anchor_id,
                local_page=page,
                children=_to_outline(h.children, ws_dests, skip_first_h1_titled=None),
            )
        )
    return tuple(out)
