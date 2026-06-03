from __future__ import annotations

import shutil

import pikepdf
import pytest

from pdf_compiler import reconcile as rc
from pdf_compiler.reconcile import (
    ReconcileStats,
    _count_name_tree,
    _Fingerprint,
    reconcile_in_memory,
    run_external,
)
from pdf_compiler.spec import FontPolicy

_PROGRAM = b"\x00\x01OpenType-ish program bytes \xde\xad\xbe\xef" * 40


def _add_embedded_font(pdf: pikepdf.Pdf, program: bytes, base: str, *, cid: bool = False):
    """Attach a fresh embedded font (own stream objects) to a new page.

    Returns the FontDescriptor so tests can inspect its program reference.
    """
    page = pdf.add_blank_page(page_size=(612, 792))
    ff = pdf.make_stream(program, Length1=len(program))
    desc = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.FontDescriptor,
            FontName=pikepdf.Name(f"/{base}"),
            FontFile2=ff,
        )
    )
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name("/Type0" if cid else "/TrueType"),
            BaseFont=pikepdf.Name(f"/{base}"),
            FontDescriptor=desc,
        )
    )
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F0=font))
    return desc


def test_dedupe_collapses_identical_font_streams():
    pdf = pikepdf.Pdf.new()
    d1 = _add_embedded_font(pdf, _PROGRAM, "ABCDEF+Test")
    d2 = _add_embedded_font(pdf, _PROGRAM, "GHIJKL+Test")
    # Two distinct stream objects going in.
    assert d1.FontFile2.objgen != d2.FontFile2.objgen

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="dedupe"))

    assert stats.merged_streams == 1
    assert stats.bytes_freed == len(_PROGRAM)
    # Now both descriptors share one program object.
    assert d1.FontFile2.objgen == d2.FontFile2.objgen


def test_dedupe_keeps_distinct_streams():
    pdf = pikepdf.Pdf.new()
    d1 = _add_embedded_font(pdf, _PROGRAM, "ABCDEF+A")
    d2 = _add_embedded_font(pdf, _PROGRAM + b"different", "GHIJKL+B")

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="dedupe"))

    assert stats.merged_streams == 0
    assert d1.FontFile2.objgen != d2.FontFile2.objgen


def test_reconcile_off_is_noop():
    pdf = pikepdf.Pdf.new()
    _add_embedded_font(pdf, _PROGRAM, "ABCDEF+Test")
    _add_embedded_font(pdf, _PROGRAM, "GHIJKL+Test")

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="off"))

    assert stats.merged_streams == 0
    assert stats.mode == "off"


def test_strip_standard_14_removes_program():
    pdf = pikepdf.Pdf.new()
    helv = _add_embedded_font(pdf, _PROGRAM, "Helvetica")  # exact std-14 name
    arial = _add_embedded_font(pdf, _PROGRAM, "Arial")  # not std-14

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="dedupe", embed_standard_14=False))

    assert stats.stripped_standard_14 == 1
    assert "/FontFile2" not in helv  # Helvetica un-embedded
    assert "/FontFile2" in arial  # Arial left alone


def test_strip_standard_14_default_keeps_program():
    pdf = pikepdf.Pdf.new()
    helv = _add_embedded_font(pdf, _PROGRAM, "Helvetica")

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="dedupe"))

    assert stats.stripped_standard_14 == 0
    assert "/FontFile2" in helv


def test_strip_standard_14_skips_cid_fonts():
    pdf = pikepdf.Pdf.new()
    # A Type0 font even if named Helvetica must not be stripped.
    cid = _add_embedded_font(pdf, _PROGRAM, "Helvetica", cid=True)

    stats = reconcile_in_memory(pdf, FontPolicy(reconcile="dedupe", embed_standard_14=False))

    assert stats.stripped_standard_14 == 0
    assert "/FontFile2" in cid


# -- verification gate ----------------------------------------------------- #


def test_fingerprint_preserves_detects_regressions():
    before = _Fingerprint(pages=10, dests=5, goto_links=20, page_labels=True, outline_items=3)
    assert before.preserves(before)
    # Any loss is rejected.
    assert not _Fingerprint(pages=9, dests=5, goto_links=20, page_labels=True).preserves(before)
    assert not _Fingerprint(pages=10, dests=0, goto_links=20, page_labels=True).preserves(before)
    assert not _Fingerprint(pages=10, dests=5, goto_links=0, page_labels=True).preserves(before)
    assert not _Fingerprint(pages=10, dests=5, goto_links=20, page_labels=False).preserves(before)
    # Nested-bookmark flattening (top-level unchanged but total drops) is caught.
    assert not _Fingerprint(
        pages=10, dests=5, goto_links=20, page_labels=True, outline_items=2
    ).preserves(before)
    # Gains are fine.
    assert _Fingerprint(
        pages=10, dests=6, goto_links=21, page_labels=True, outline_items=4
    ).preserves(before)


def test_count_name_tree_handles_flat_and_kids():
    """Dest counting must traverse both a flat /Names leaf and a /Kids tree,
    so an optimizer that rebuilds the tree form isn't misread as data loss."""
    pdf = pikepdf.Pdf.new()

    def leaf(n):
        pairs = []
        for i in range(n):
            pairs += [pikepdf.String(f"d{i}"), pikepdf.Array([])]
        return pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(pairs)))

    flat = leaf(3)
    assert _count_name_tree(flat) == 3

    tree = pdf.make_indirect(pikepdf.Dictionary(Kids=pikepdf.Array([leaf(2), leaf(4)])))
    assert _count_name_tree(tree) == 6

    # Node with neither key counts as zero (no crash).
    assert _count_name_tree(pdf.make_indirect(pikepdf.Dictionary())) == 0
    assert _count_name_tree(None) == 0


def test_run_external_no_tool_available(tmp_path, monkeypatch):
    p = tmp_path / "x.pdf"
    pikepdf.Pdf.new().save(p)
    monkeypatch.setattr(rc, "_candidate_tools", lambda policy: [])

    stats = run_external(p, FontPolicy(reconcile="merge"), ReconcileStats(mode="merge"))

    assert not stats.external_applied
    assert "no external optimizer" in stats.external_reason


def test_run_external_rejects_structure_breaking_tool(tmp_path, monkeypatch):
    """A tool whose output drops destinations must be discarded; the original
    file stays untouched."""
    src = tmp_path / "x.pdf"
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.Root["/Names"] = pikepdf.Dictionary(
        Dests=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("a"), pikepdf.Array([])]))
    )
    pdf.save(src)
    original = src.read_bytes()

    def fake_run(cmd, **kw):
        # "Optimize" by writing a structurally-empty PDF (no /Names tree) to
        # whatever output path the command was built with (qpdf: last arg).
        dst = cmd[-1]
        empty = pikepdf.Pdf.new()
        empty.add_blank_page(page_size=(612, 792))
        empty.save(dst)

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(rc, "_candidate_tools", lambda policy: ["qpdf"])
    monkeypatch.setattr(rc.subprocess, "run", fake_run)

    stats = run_external(src, FontPolicy(reconcile="merge"), ReconcileStats(mode="merge"))

    assert not stats.external_applied
    assert "structure" in stats.external_reason
    assert src.read_bytes() == original  # untouched
    # The unique temp file is cleaned up (no stragglers in the dir).
    assert not list(tmp_path.glob(".pdfc-reconcile-*"))


@pytest.mark.skipif(shutil.which("qpdf") is None, reason="qpdf not installed")
def test_run_external_merge_applies_qpdf(tmp_path):
    """With qpdf present, a real merge pass either shrinks the file (and is
    applied) or is skipped for no improvement — never breaks structure."""
    from pdf_compiler.assemble import assemble
    from pdf_compiler.sections.base import CompiledSection

    # Build something with redundant content qpdf can recompress.
    big = tmp_path / "big.pdf"
    pdf = pikepdf.Pdf.new()
    for _ in range(20):
        pg = pdf.add_blank_page(page_size=(612, 792))
        pg.Contents = pdf.make_stream(b"q 1 0 0 1 0 0 cm Q " * 200)
    pdf.save(big)

    out = tmp_path / "out.pdf"
    sec = CompiledSection(pdf_path=big, page_count=20, destinations={"top": 0})
    from pdf_compiler.spec import Metadata

    result = assemble([sec], out, Metadata(), fonts=FontPolicy(reconcile="merge"))
    fr = result.font_reconcile
    assert fr is not None
    # Destinations always survive.
    with pikepdf.open(out) as opened:
        assert "/Dests" in opened.Root["/Names"]
    if fr.external_applied:
        assert fr.size_after < fr.size_before
