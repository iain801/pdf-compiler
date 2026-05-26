from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from pdf_compiler.assemble import AssemblyError, assemble
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import Metadata, PageNumbering


def _section(pdf_path: Path, n: int, **kw) -> CompiledSection:
    return CompiledSection(pdf_path=pdf_path, page_count=n, **kw)


def test_concatenates_pages(tmp_path, make_pdf):
    a = _section(make_pdf(3, "a.pdf"), 3)
    b = _section(make_pdf(2, "b.pdf"), 2)
    out = tmp_path / "out.pdf"
    result = assemble([a, b], out, Metadata())
    assert result.page_count == 5
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 5


def test_installs_named_destinations(tmp_path, make_pdf):
    p = make_pdf(3, "x.pdf")
    sec = _section(
        p,
        3,
        destinations={"intro": 0, "middle": 1, "end": 2},
    )
    out = tmp_path / "out.pdf"
    result = assemble([sec], out, Metadata())
    assert result.destinations == {"intro": 0, "middle": 1, "end": 2}
    with pikepdf.open(out) as pdf:
        names = pdf.Root["/Names"]["/Dests"]["/Names"]
        # Flat name tree: [name, dest_array, name, dest_array, ...]
        keys = [str(names[i]) for i in range(0, len(names), 2)]
        assert keys == sorted(keys)
        assert set(keys) == {"intro", "middle", "end"}


def test_destinations_shifted_by_page_offset(tmp_path, make_pdf):
    a = _section(make_pdf(2, "a.pdf"), 2, destinations={"a-top": 0})
    b = _section(make_pdf(3, "b.pdf"), 3, destinations={"b-top": 0, "b-mid": 1})
    out = tmp_path / "out.pdf"
    r = assemble([a, b], out, Metadata())
    assert r.destinations == {"a-top": 0, "b-top": 2, "b-mid": 3}


def test_duplicate_destination_raises(tmp_path, make_pdf):
    a = _section(make_pdf(1, "a.pdf"), 1, destinations={"x": 0})
    b = _section(make_pdf(1, "b.pdf"), 1, destinations={"x": 0})
    with pytest.raises(AssemblyError, match="duplicate"):
        assemble([a, b], tmp_path / "out.pdf", Metadata())


def test_page_count_mismatch_raises(tmp_path, make_pdf):
    sec = CompiledSection(pdf_path=make_pdf(3, "a.pdf"), page_count=5)
    with pytest.raises(AssemblyError, match="declared 5 pages"):
        assemble([sec], tmp_path / "out.pdf", Metadata())


def test_outline_built(tmp_path, make_pdf):
    p = make_pdf(3, "x.pdf")
    sec = _section(
        p,
        3,
        outline=(
            OutlineNode(
                "Chapter 1",
                "ch1",
                local_page=0,
                children=(OutlineNode("Section 1.1", "ch1.1", local_page=1),),
            ),
            OutlineNode("Chapter 2", "ch2", local_page=2),
        ),
    )
    out = tmp_path / "out.pdf"
    assemble([sec], out, Metadata())
    with pikepdf.open(out) as pdf, pdf.open_outline() as outline:
        titles = [r.title for r in outline.root]
        assert titles == ["Chapter 1", "Chapter 2"]
        assert [c.title for c in outline.root[0].children] == ["Section 1.1"]


def test_metadata_written(tmp_path, make_pdf):
    sec = _section(make_pdf(1, "x.pdf"), 1)
    out = tmp_path / "out.pdf"
    assemble(
        [sec],
        out,
        Metadata(title="Hello", author="Tester", subject="Stuff", keywords=("a", "b")),
    )
    with pikepdf.open(out) as pdf:
        info = pdf.docinfo
        assert str(info["/Title"]) == "Hello"
        assert str(info["/Author"]) == "Tester"
        assert str(info["/Subject"]) == "Stuff"
        assert "a" in str(info["/Keywords"])


def test_empty_sections_raises(tmp_path):
    with pytest.raises(ValueError, match="no sections"):
        assemble([], tmp_path / "out.pdf", Metadata())


def test_page_numbers_stamped_when_enabled(tmp_path, make_pdf):
    """With ``enabled=True`` each page gets a stamped page-number label."""
    import pdfplumber

    front = _section(make_pdf(2, "fm.pdf"), 2, front_matter=True)
    body = _section(make_pdf(3, "body.pdf"), 3)
    out = tmp_path / "out.pdf"
    assemble(
        [front, body],
        out,
        Metadata(),
        page_numbering=PageNumbering(enabled=True),
        margin="0.5in",
    )
    with pdfplumber.open(out) as pdf:
        labels = []
        for page in pdf.pages:
            words = [w["text"] for w in page.extract_words() if w["top"] > page.height - 50]
            labels.append(words[-1] if words else "")
    # Front-matter pages get roman; body pages restart at arabic 1.
    assert labels == ["i", "ii", "1", "2", "3"]


def test_page_numbers_default_off(tmp_path, make_pdf):
    """Nothing is stamped when the config is left at its default."""
    import pdfplumber

    sec = _section(make_pdf(2, "x.pdf"), 2)
    out = tmp_path / "out.pdf"
    assemble([sec], out, Metadata())  # no page_numbering arg
    with pdfplumber.open(out) as pdf:
        text = "".join((p.extract_text() or "") for p in pdf.pages)
    assert text.strip() == ""


def test_page_numbers_position_right(tmp_path, make_pdf):
    """``position`` controls horizontal alignment of the label."""
    import pdfplumber

    sec = _section(make_pdf(1, "x.pdf"), 1)
    out = tmp_path / "out.pdf"
    assemble(
        [sec],
        out,
        Metadata(),
        page_numbering=PageNumbering(enabled=True, position="bottom-right"),
        margin="0.5in",
    )
    with pdfplumber.open(out) as pdf:
        page = pdf.pages[0]
        words = [w for w in page.extract_words() if w["top"] > page.height - 50]
        assert words, "expected a page-number stamp"
        # Right-aligned: word's x sits past the page midline.
        assert words[-1]["x0"] > page.width / 2


def test_toc_destinations_tracked(tmp_path, make_pdf):
    a = _section(
        make_pdf(3, "a.pdf"),
        3,
        toc_entries=(TocEntry(1, "Intro", "intro-anchor", local_page=0),),
    )
    b = _section(
        make_pdf(2, "b.pdf"),
        2,
        toc_entries=(TocEntry(1, "End", "end-anchor", local_page=1),),
    )
    r = assemble([a, b], tmp_path / "out.pdf", Metadata())
    assert r.toc_destinations == {"intro-anchor": 0, "end-anchor": 4}
