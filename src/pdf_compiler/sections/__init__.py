"""Section registry — maps each spec section type to an impl."""
from __future__ import annotations

from pdf_compiler.sections._common import SectionMeta
from pdf_compiler.sections.base import (
    CompiledSection,
    OutlineNode,
    Section,
    TocEntry,
)
from pdf_compiler.spec import (
    Defaults,
    HeaderSection,
    ImagesSection,
    MarkdownSection,
    PdfSection,
    TitleSection,
    TocSection,
)


def impl_for(spec_section, index: int, defaults: Defaults):
    """Dispatch a pydantic spec section to its compiling impl.

    The ToC section is a sentinel here — the pipeline handles it specially
    (it has to be rendered after every other section is compiled).
    """
    meta = SectionMeta(index=index, defaults=defaults)
    if isinstance(spec_section, TitleSection):
        from pdf_compiler.sections.title import TitleImpl
        return TitleImpl(spec=spec_section, meta=meta)
    if isinstance(spec_section, HeaderSection):
        from pdf_compiler.sections.header import HeaderImpl
        return HeaderImpl(spec=spec_section, meta=meta)
    if isinstance(spec_section, MarkdownSection):
        from pdf_compiler.sections.markdown_doc import MarkdownImpl
        return MarkdownImpl(spec=spec_section, meta=meta)
    if isinstance(spec_section, PdfSection):
        from pdf_compiler.sections.pdf_ref import PdfRefImpl
        return PdfRefImpl(spec=spec_section, meta=meta)
    if isinstance(spec_section, ImagesSection):
        from pdf_compiler.sections.images import ImagesImpl
        return ImagesImpl(spec=spec_section, meta=meta)
    if isinstance(spec_section, TocSection):
        return None  # rendered separately, see pipeline_impl
    raise TypeError(f"no impl for section type: {type(spec_section).__name__}")


__all__ = [
    "CompiledSection",
    "OutlineNode",
    "Section",
    "TocEntry",
    "SectionMeta",
    "impl_for",
]
