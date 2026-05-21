from __future__ import annotations

from pathlib import Path

import pytest

from pdf_compiler.loader import SpecError, load_spec
from pdf_compiler.spec import (
    HeaderSection,
    ImagesSection,
    MarkdownSection,
    PdfSection,
    Spec,
    TitleSection,
    TocSection,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "spec.yaml"
    p.write_text(content)
    return p


def test_minimal(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: title
    title: Hi
""")
    spec = load_spec(p)
    assert isinstance(spec, Spec)
    assert len(spec.sections) == 1
    assert isinstance(spec.sections[0], TitleSection)


def test_all_section_types(tmp_path: Path):
    p = _write(tmp_path, """
output: build/out.pdf
metadata:
  title: T
  author: A
  keywords: [a, b]
defaults:
  index_headers: false
  page_size: a4
sections:
  - type: title
    title: A
  - type: toc
    depth: 2
  - type: header
    title: Part 1
    body: "**bold**"
  - type: markdown
    path: intro.md
  - type: pdf
    path: report.pdf
    pages: "1-5,10"
  - type: images
    title: Gallery
    per_page: 4
    images:
      - { path: a.jpg, caption: A }
      - { path: b.jpg }
""")
    spec = load_spec(p)
    types = [type(s).__name__ for s in spec.sections]
    assert types == [
        "TitleSection", "TocSection", "HeaderSection",
        "MarkdownSection", "PdfSection", "ImagesSection",
    ]
    assert spec.defaults.index_headers is False
    assert spec.metadata.keywords == ("a", "b")


def test_unknown_keys_rejected(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: title
    title: A
    bogus_key: oops
""")
    with pytest.raises(SpecError, match="bogus_key"):
        load_spec(p)


def test_unknown_section_type(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: zombie
    title: x
""")
    with pytest.raises(SpecError):
        load_spec(p)


def test_empty_sections(tmp_path: Path):
    p = _write(tmp_path, "sections: []\n")
    with pytest.raises(SpecError, match="at least one section"):
        load_spec(p)


def test_empty_images(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: images
    images: []
""")
    with pytest.raises(SpecError, match="at least one image"):
        load_spec(p)


def test_yaml_syntax_error(tmp_path: Path):
    p = _write(tmp_path, "sections: [\n")
    with pytest.raises(SpecError, match="YAML parse error"):
        load_spec(p)


def test_line_number_in_error(tmp_path: Path):
    p = _write(tmp_path, """sections:
  - type: title
    title: ok
  - type: title
    title: ok
    bogus: bad
""")
    with pytest.raises(SpecError) as ei:
        load_spec(p)
    msg = str(ei.value)
    # Should pin the error to *somewhere in* the second section (lines 4-6),
    # not the first (lines 2-3).
    assert any(f"line {n}" in msg for n in (4, 5, 6))
    assert "line 2" not in msg and "line 3" not in msg


def test_pdf_section_pages_optional(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: pdf
    path: x.pdf
""")
    spec = load_spec(p)
    assert isinstance(spec.sections[0], PdfSection)
    assert spec.sections[0].pages is None


def test_defaults_round_trip(tmp_path: Path):
    p = _write(tmp_path, """
sections:
  - type: title
    title: A
""")
    spec = load_spec(p)
    assert spec.defaults.index_headers is True
    assert spec.defaults.page_numbering.front_matter == "roman"
    assert spec.defaults.page_numbering.body == "arabic"
