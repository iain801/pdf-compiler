"""Tests for ToC clickable link annotations."""

from __future__ import annotations

from pathlib import Path

import pikepdf

from pdf_compiler.context import build_context
from pdf_compiler.sections.base import TocEntry
from pdf_compiler.sections.toc import render_toc
from pdf_compiler.spec import Defaults, Spec, TitleSection, TocSection


def _ctx(tmp_path: Path):
    spec = Spec(sections=(TitleSection(title="x"),), defaults=Defaults())
    sp = tmp_path / "spec.yaml"
    sp.write_text("")
    (tmp_path / "tmp").mkdir(exist_ok=True)
    return build_context(sp, spec, jobs=1, use_cache=False, tmpdir=tmp_path / "tmp")


def _render_toc(tmp_path, entries_raw):
    """Render a ToC and return the PDF path."""
    ctx = _ctx(tmp_path)
    entries = [
        (TocEntry(depth=d, label=lbl, dest_name=dest, local_page=0), pg)
        for d, lbl, dest, pg in entries_raw
    ]
    out = tmp_path / "toc.pdf"
    render_toc(ctx, TocSection(), entries, out_path=out, front_matter_pages=set())
    return out


def _link_dests(pdf_path: Path) -> list[str]:
    """Return the GoTo destination names of all Link annotations in the PDF."""
    dests = []
    with pikepdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            for annot in page.obj.get("/Annots", []):
                if annot.get("/Subtype") != pikepdf.Name("/Link"):
                    continue
                action = annot.get("/A", {})
                d = action.get("/D")
                if d is not None:
                    dests.append(str(d))
    return dests


def test_toc_emits_link_annotations(tmp_path):
    out = _render_toc(
        tmp_path,
        [
            (1, "Chapter 1", "sec-0001-top", 2),
            (2, "Section 1.1", "sec-0002-h2-intro", 4),
        ],
    )
    dests = _link_dests(out)
    assert len(dests) == 2


def test_toc_links_point_to_content_destinations(tmp_path):
    out = _render_toc(
        tmp_path,
        [
            (1, "Chapter 1", "sec-0001-top", 2),
            (2, "Section 1.1", "sec-0002-h2-intro", 4),
            (1, "Chapter 2", "sec-0003-top", 10),
        ],
    )
    dests = _link_dests(out)
    assert dests == ["sec-0001-top", "sec-0002-h2-intro", "sec-0003-top"]


def test_toc_links_not_self_referential(tmp_path):
    """Links must not point back to the ToC page — they must point to content."""
    out = _render_toc(
        tmp_path,
        [
            (1, "Intro", "sec-0001-top", 1),
        ],
    )
    dests = _link_dests(out)
    assert dests == ["sec-0001-top"]
    # Verify the annotation action is GoTo, not a local dest array.
    with pikepdf.open(out) as pdf:
        for page in pdf.pages:
            for annot in page.obj.get("/Annots", []):
                if annot.get("/Subtype") == pikepdf.Name("/Link"):
                    action = annot.get("/A", {})
                    assert action.get("/S") == pikepdf.Name("/GoTo")
                    # /D must be a String (named dest), not an Array (local dest).
                    d = action.get("/D")
                    assert isinstance(d, pikepdf.String), (
                        "destination should be a named string, not a local array"
                    )


def test_empty_toc_no_annotations(tmp_path):
    out = _render_toc(tmp_path, [])
    assert _link_dests(out) == []
