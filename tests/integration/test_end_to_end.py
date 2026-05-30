from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from pdf_compiler.pipeline import compile_spec, validate_spec

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(scope="module")
def report_pdf(tmp_path_factory):
    out = tmp_path_factory.mktemp("e2e") / "report.pdf"
    result = compile_spec(EXAMPLES / "report.yaml", out_path=out, jobs=1)
    assert result.output_path == out
    return out


def test_validates(tmp_path):
    problems = validate_spec(EXAMPLES / "report.yaml")
    assert problems == []


def test_compiles_pages(report_pdf: Path):
    with pikepdf.open(report_pdf) as pdf:
        assert len(pdf.pages) >= 5  # title + toc + intro + part-divider + ...


def test_metadata_set(report_pdf: Path):
    with pikepdf.open(report_pdf) as pdf:
        info = pdf.docinfo
        assert "Annual Report" in str(info.get("/Title", ""))
        assert "pdf-compiler" in str(info.get("/Author", ""))


def test_outline_has_top_level_entries(report_pdf: Path):
    with pikepdf.open(report_pdf) as pdf, pdf.open_outline() as ol:
        titles = [str(r.title) for r in ol.root]
        # We expect at least one bookmark from the title, ToC, and
        # markdown sections (combined, in some order).
        assert any("Introduction" in t or "Part II" in t or "Financials" in t for t in titles)


def test_named_destinations_installed(report_pdf: Path):
    with pikepdf.open(report_pdf) as pdf:
        assert "/Names" in pdf.Root
        names = pdf.Root["/Names"]["/Dests"]["/Names"]
        # Flat name tree alternates (name, dest_array). At least one dest
        # should mention "intro" or "financial" or "part".
        names_list = [str(names[i]) for i in range(0, len(names), 2)]
        assert any("sec-" in n for n in names_list)


def test_internal_links_target_dests(report_pdf: Path):
    """Every link annotation that uses a named destination should point at
    a name that exists in the global /Dests tree."""
    with pikepdf.open(report_pdf) as pdf:
        names_dict = {}
        if "/Names" in pdf.Root and "/Dests" in pdf.Root["/Names"]:
            arr = pdf.Root["/Names"]["/Dests"]["/Names"]
            for i in range(0, len(arr), 2):
                names_dict[str(arr[i])] = arr[i + 1]
        # Walk annotations
        broken: list[str] = []
        for page in pdf.pages:
            for annot in page.get("/Annots", []) or []:
                if "/A" in annot and annot["/A"].get("/S") == pikepdf.Name.GoTo:
                    dest = annot["/A"].get("/D")
                    if isinstance(dest, pikepdf.String) and str(dest) not in names_dict:
                        broken.append(str(dest))
        # ToC link targets should resolve
        assert not broken, f"broken link destinations: {broken[:5]}"


def test_cache_round_trip(tmp_path):
    """Compile twice; the second run should produce a structurally identical
    PDF and be faster (cache hits). We test structural identity only."""
    out1 = tmp_path / "a.pdf"
    out2 = tmp_path / "b.pdf"
    compile_spec(EXAMPLES / "report.yaml", out_path=out1, jobs=1)
    compile_spec(EXAMPLES / "report.yaml", out_path=out2, jobs=1)
    with pikepdf.open(out1) as p1, pikepdf.open(out2) as p2:
        assert len(p1.pages) == len(p2.pages)
        # Same outline shape
        with p1.open_outline() as o1, p2.open_outline() as o2:
            assert [str(r.title) for r in o1.root] == [str(r.title) for r in o2.root]


def test_text_extraction(report_pdf: Path):
    """Use pdfplumber to confirm key strings made it into the rendered text."""
    import pdfplumber

    with pdfplumber.open(report_pdf) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "Annual Report" in text
    assert "Introduction" in text
    assert "Q1" in text  # from financials.md


def test_subtoc_header_renders_mini_toc(report_pdf: Path):
    """report.yaml's Part II header has subtoc: true — its page should list
    the financial headings that follow."""
    import pdfplumber

    with pdfplumber.open(report_pdf) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    # The subtoc header introduces this label and lists scoped entries.
    assert "In this section" in text
    # Entries from the next markdown section appear with page labels.
    assert "Financials Overview" in text


def test_subtoc_header_appears_in_main_toc(report_pdf: Path):
    """A subtoc: true header is itself deferred, but must still be listed on
    the main ToC page (regression: deferred headers were skipped entirely)."""
    import pdfplumber

    with pdfplumber.open(report_pdf) as pdf:
        toc_pages = [
            p.extract_text() or ""
            for p in pdf.pages
            if "Table of Contents" in (p.extract_text() or "")
        ]
    assert toc_pages, "main ToC page not found"
    # The Part II divider (subtoc: true) must appear on the main ToC itself,
    # not only on its own subtoc page.
    assert any("Part II — Financials" in t for t in toc_pages)


def test_page_numbers_stamped(report_pdf: Path):
    """report.yaml has page_numbering.enabled: true — pages should bear
    roman and arabic stamps as appropriate."""
    import pdfplumber

    with pdfplumber.open(report_pdf) as pdf:
        labels = []
        for page in pdf.pages:
            words = [w["text"] for w in page.extract_words() if w["top"] > page.height - 50]
            labels.append(words[-1] if words else "")
    # First two pages (title + ToC) are front matter (roman); body restarts at 1.
    assert labels[0] == "i"
    assert labels[1] == "ii"
    assert "1" in labels[2:]
