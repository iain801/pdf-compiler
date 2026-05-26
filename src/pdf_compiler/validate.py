"""Standalone spec validation: check every referenced file exists and is usable."""

from __future__ import annotations

from pathlib import Path

import pikepdf
from PIL import Image, UnidentifiedImageError

from pdf_compiler.page_range import PageRangeError, parse_page_range
from pdf_compiler.spec import (
    ImagesSection,
    MarkdownSection,
    PdfSection,
    Spec,
)


def validate_inputs(spec: Spec, project_root: Path) -> list[str]:
    """Return a list of problem strings; empty list = OK."""
    problems: list[str] = []
    for i, sec in enumerate(spec.sections):
        if isinstance(sec, MarkdownSection):
            p = _resolve(project_root, sec.path)
            if not p.is_file():
                problems.append(f"section {i}: markdown file not found: {p}")
            elif p.suffix.lower() not in {".md", ".markdown", ".txt"}:
                problems.append(f"section {i}: not a markdown file: {p}")
        elif isinstance(sec, PdfSection):
            p = _resolve(project_root, sec.path)
            if not p.is_file():
                problems.append(f"section {i}: pdf file not found: {p}")
            else:
                try:
                    with pikepdf.open(p) as src:
                        n = len(src.pages)
                    if sec.pages:
                        try:
                            parse_page_range(sec.pages, n)
                        except PageRangeError as e:
                            problems.append(f"section {i}: {e}")
                except (pikepdf.PdfError, OSError) as e:
                    problems.append(f"section {i}: cannot open PDF {p}: {e}")
        elif isinstance(sec, ImagesSection):
            for j, img in enumerate(sec.images):
                p = _resolve(project_root, img.path)
                if not p.is_file():
                    problems.append(f"section {i}, image {j}: file not found: {p}")
                    continue
                try:
                    with Image.open(p) as im:
                        im.verify()
                except (UnidentifiedImageError, OSError) as e:
                    problems.append(f"section {i}, image {j}: not a readable image ({e})")
    return problems


def _resolve(root: Path, p: Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (root / p).resolve()
