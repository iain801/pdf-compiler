"""Bits shared across section implementations."""
from __future__ import annotations

from dataclasses import dataclass

from pdf_compiler.spec import Defaults


@dataclass(frozen=True, slots=True)
class SectionMeta:
    """Per-section info computed by the pipeline before compilation.

    ``index`` is the position in the spec (used to namespace destinations);
    ``defaults`` are the global defaults, possibly overridden by the section.
    """

    index: int
    defaults: Defaults


def dest_prefix(meta: SectionMeta) -> str:
    return f"sec-{meta.index:04d}"


def page_count_of(pdf_path) -> int:
    import pikepdf
    with pikepdf.open(pdf_path) as p:
        return len(p.pages)
