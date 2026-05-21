"""End-to-end-ish tests of each section impl producing a temp PDF."""
from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from pdf_compiler.context import build_context
from pdf_compiler.sections import impl_for
from pdf_compiler.spec import (
    Defaults,
    HeaderSection,
    ImageItem,
    ImagesSection,
    MarkdownSection,
    PdfSection,
    Spec,
    TitleSection,
)


def _ctx(tmp_path: Path, defaults: Defaults | None = None):
    defaults = defaults or Defaults()
    spec = Spec(sections=(TitleSection(title="x"),), defaults=defaults)
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("# placeholder")
    return build_context(
        spec_path, spec, jobs=1, use_cache=False, tmpdir=tmp_path / "tmp",
    )


def test_title_section(tmp_path: Path):
    ctx = _ctx(tmp_path)
    s = TitleSection(title="Hello", subtitle="Sub", author="Me", in_toc=True)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count >= 1
    assert any("Hello" in str(e.label) for e in cs.toc_entries)
    with pikepdf.open(cs.pdf_path) as pdf:
        assert len(pdf.pages) >= 1


def test_header_section_with_body(tmp_path: Path):
    ctx = _ctx(tmp_path)
    s = HeaderSection(title="Part 1", subtitle="Sub", body="**bold** intro")
    cs = impl_for(s, 1, ctx.defaults).compile(ctx)
    assert cs.page_count >= 1
    assert cs.toc_entries[0].label == "Part 1"
    assert "sec-0001-header" in cs.destinations


def test_markdown_section_extracts_headings(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("# Intro\n\nSome text\n\n## Sub\n\nMore\n\n# Outro\n")
    ctx = _ctx(tmp_path)
    s = MarkdownSection(path=Path("doc.md"))
    cs = impl_for(s, 2, ctx.defaults).compile(ctx)
    labels = [e.label for e in cs.toc_entries]
    # "Intro" used as section title (dedup'd from ToC entries), but "Sub"
    # and "Outro" should appear.
    assert "Sub" in labels
    assert "Outro" in labels


def test_markdown_index_headers_false(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("# A\n\n## B\n\n## C\n")
    ctx = _ctx(tmp_path)
    s = MarkdownSection(path=Path("doc.md"), index_headers=False)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    labels = [e.label for e in cs.toc_entries]
    # Only the section title — no nested headings.
    assert labels == ["A"]


def test_pdf_section_page_range(tmp_path: Path, make_pdf):
    src = make_pdf(10, "input.pdf")
    ctx = _ctx(tmp_path)
    s = PdfSection(path=src, pages="2-4,7", title="Q1")
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count == 4  # pages 2,3,4,7
    with pikepdf.open(cs.pdf_path) as pdf:
        assert len(pdf.pages) == 4


def test_pdf_section_all_pages(tmp_path: Path, make_pdf):
    src = make_pdf(3, "input.pdf")
    ctx = _ctx(tmp_path)
    s = PdfSection(path=src)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count == 3


def test_images_section_grid(tmp_path: Path):
    pytest.importorskip("PIL")
    from PIL import Image
    paths = []
    for i in range(5):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (100, 80), (i * 40, 0, 0)).save(p)
        paths.append(p)
    ctx = _ctx(tmp_path)
    s = ImagesSection(
        title="Gallery", per_page=4, layout="grid",
        images=tuple(ImageItem(path=p, caption=f"img {i}") for i, p in enumerate(paths)),
    )
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    # 5 images with per_page=4 → 2 pages
    assert cs.page_count == 2


def test_section_caches_output(tmp_path: Path):
    """Compiling the same section twice should hit the cache the second time."""
    md = tmp_path / "doc.md"
    md.write_text("# Same\n")
    cache_dir = tmp_path / "cache"
    defaults = Defaults()
    spec = Spec(sections=(TitleSection(title="x"),), defaults=defaults)
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("")
    ctx = build_context(
        spec_path, spec, jobs=1, use_cache=True,
        cache_dir=cache_dir, tmpdir=tmp_path / "tmp",
    )

    s = MarkdownSection(path=Path("doc.md"))
    impl = impl_for(s, 0, ctx.defaults)
    a = impl.compile(ctx)
    b = impl.compile(ctx)
    # Second compile should return the cached PDF path, not a fresh temp.
    assert a.pdf_path == b.pdf_path
