from __future__ import annotations

from pathlib import Path

import pikepdf

from pdf_compiler.render.html import render_html, render_to_pdf


def test_render_title_html():
    html = render_html("title.html", {
        "title": "Hello",
        "subtitle": "Sub",
        "author": "Me",
        "date": "2026-05-21",
        "page_size": "letter",
        "margin": "0.75in",
    })
    assert "<h1>Hello</h1>" in html
    assert "Sub" in html
    assert "Me" in html


def test_render_to_pdf_works(tmp_path: Path):
    out = tmp_path / "title.pdf"
    render_to_pdf(
        "title.html",
        {
            "title": "Hello",
            "subtitle": None,
            "author": None,
            "date": None,
            "page_size": "letter",
            "margin": "0.75in",
        },
        out,
        base_url=tmp_path,
    )
    assert out.is_file()
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) >= 1


def test_strict_undefined():
    """Missing template vars must raise loudly, not silently render empty."""
    import jinja2

    try:
        render_html("title.html", {"title": "T"})  # missing other vars
    except jinja2.UndefinedError:
        pass
    else:
        raise AssertionError("expected StrictUndefined to raise")
