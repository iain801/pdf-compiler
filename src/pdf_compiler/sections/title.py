"""Title section: a one-page cover.

The ``title``, ``author``, and ``date`` fields all fall back to the
top-level ``metadata`` block when omitted on the section. ``date``
additionally defaults to *today* when neither place specifies it; an
explicit ``date: none`` (YAML null) at either level disables the date.

Resolution rules per field:

  title    section.title  |  else metadata.title  |  else error
  author   section.author |  else metadata.author |  else omit
  date     section.date if the section set it (None disables)
           |  else metadata.date if metadata set it (None disables)
           |  else today's date
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix, page_count_of
from pdf_compiler.sections.base import CompiledSection
from pdf_compiler.spec import Metadata, TitleSection


@dataclass(frozen=True, slots=True)
class TitleImpl:
    spec: TitleSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-title"

        resolved_title = _resolve_title(self.spec, ctx.metadata)
        resolved_author = _resolve_author(self.spec, ctx.metadata)
        resolved_date = _resolve_date(self.spec, ctx.metadata)

        # Cache key folds in the *resolved* values so identical-looking
        # specs with different metadata produce different outputs, and
        # today's date naturally invalidates day-over-day.
        extra = (
            f"title:{prefix}:"
            f"{resolved_title}:"
            f"{resolved_author or ''}:"
            f"{resolved_date or ''}"
        ).encode()
        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=(),
            extra=extra,
        )
        cached = ctx.cache.get(key)
        if cached is not None:
            return _result(cached, dest_name, self.spec.in_toc, resolved_title,
                            self.spec.front_matter)

        out = ctx.tmp_pdf("title")
        render_to_pdf(
            "title.html",
            {
                "title": resolved_title,
                "subtitle": self.spec.subtitle,
                "author": resolved_author,
                "date": resolved_date,
                "page_size": defaults.page_size,
                "margin": defaults.margin,
            },
            out,
            base_url=ctx.project_root,
        )
        out = ctx.cache.put(key, out)
        return _result(out, dest_name, self.spec.in_toc, resolved_title,
                       self.spec.front_matter)


# -- field resolution ------------------------------------------------------ #


def _resolve_title(spec: TitleSection, metadata: Metadata) -> str:
    """Section wins if set, else metadata, else error."""
    if "title" in spec.model_fields_set and spec.title is not None:
        return spec.title
    if metadata.title is not None:
        return metadata.title
    raise ValueError(
        "title section: no title provided "
        "(set the section's `title` or `metadata.title`)"
    )


def _resolve_author(spec: TitleSection, metadata: Metadata) -> str | None:
    """Section wins (None = explicitly hidden); else fall back to metadata."""
    if "author" in spec.model_fields_set:
        return spec.author  # may be None — explicit opt-out
    return metadata.author


def _resolve_date(spec: TitleSection, metadata: Metadata) -> str | None:
    """Section overrides metadata; if neither is set, default to today.

    Returns the date as an ISO 8601 string, or ``None`` to mean "no date".
    """
    if "date" in spec.model_fields_set:
        d = spec.date  # None = explicit `date: none`
    elif "date" in metadata.model_fields_set:
        d = metadata.date
    else:
        d = _dt.date.today()
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


# -- result wrapping ------------------------------------------------------- #


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
