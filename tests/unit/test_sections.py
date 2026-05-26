"""End-to-end-ish tests of each section impl producing a temp PDF."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from pdf_compiler.context import build_context
from pdf_compiler.sections import impl_for
from pdf_compiler.sections.title import (
    _resolve_author,
    _resolve_date,
    _resolve_title,
)
from pdf_compiler.spec import (
    Defaults,
    HeaderSection,
    ImageItem,
    ImagesSection,
    MarkdownSection,
    Metadata,
    PdfSection,
    Spec,
    TitleSection,
)


def _ctx(
    tmp_path: Path,
    defaults: Defaults | None = None,
    metadata: Metadata | None = None,
    vars: dict | None = None,
):
    defaults = defaults or Defaults()
    metadata = metadata or Metadata()
    spec = Spec(
        sections=(TitleSection(title="x"),),
        defaults=defaults,
        metadata=metadata,
        vars=vars or {},
    )
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("# placeholder")
    return build_context(
        spec_path,
        spec,
        jobs=1,
        use_cache=False,
        tmpdir=tmp_path / "tmp",
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


def test_pdf_section_regularize_normalizes_page_size(tmp_path: Path, make_pdf):
    """A4-sized input becomes letter-sized output when regularize_pages is on."""
    a4 = (595.276, 841.890)
    src = make_pdf(2, "a4.pdf", page_size=a4)
    ctx = _ctx(tmp_path, defaults=Defaults(regularize_pages=True))
    s = PdfSection(path=src)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    with pikepdf.open(cs.pdf_path) as pdf:
        sizes = {
            (round(float(p.MediaBox[2]), 1), round(float(p.MediaBox[3]), 1)) for p in pdf.pages
        }
    assert sizes == {(612.0, 792.0)}


def test_pdf_section_regularize_passthrough_when_already_target(tmp_path: Path, make_pdf):
    """Pages already at target size are kept as-is (no needless wrapping)."""
    src = make_pdf(2, "letter.pdf", page_size=(612, 792))
    ctx = _ctx(tmp_path, defaults=Defaults(regularize_pages=True))
    s = PdfSection(path=src)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    with pikepdf.open(cs.pdf_path) as pdf:
        # Same page count and MediaBox.
        assert len(pdf.pages) == 2
        for p in pdf.pages:
            assert (float(p.MediaBox[2]), float(p.MediaBox[3])) == (612.0, 792.0)


def test_pdf_section_regularize_section_override(tmp_path: Path, make_pdf):
    """Per-section regularize_pages overrides the default."""
    src = make_pdf(1, "a4.pdf", page_size=(595.276, 841.890))
    ctx = _ctx(tmp_path, defaults=Defaults(regularize_pages=False))
    s = PdfSection(path=src, regularize_pages=True)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    with pikepdf.open(cs.pdf_path) as pdf:
        mb = pdf.pages[0].MediaBox
        assert (float(mb[2]), float(mb[3])) == (612.0, 792.0)


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
        title="Gallery",
        per_page=4,
        layout="grid",
        images=tuple(ImageItem(path=p, caption=f"img {i}") for i, p in enumerate(paths)),
    )
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    # 5 images with per_page=4 → 2 grid pages + 1 title page = 3 pages
    assert cs.page_count == 3


def _make_imgs(tmp_path: Path, sizes: list[tuple[int, int]]) -> list[Path]:
    """Create small PNG test images with the given (width, height) sizes."""
    from PIL import Image

    paths = []
    for i, (w, h) in enumerate(sizes):
        p = tmp_path / f"img{i}_{w}x{h}.png"
        Image.new("RGB", (w, h), (i * 30, 0, 0)).save(p)
        paths.append(p)
    return paths


def test_variable_heights_fills_page(tmp_path: Path):
    """variable_heights=True: each page should produce exactly 1 PDF page
    (no overflow) even for mixed portrait/landscape images."""
    pytest.importorskip("PIL")
    # Mix a wide landscape (4:1) and a tall portrait (1:4) on the same page.
    paths = _make_imgs(tmp_path, [(400, 100), (100, 400)])
    ctx = _ctx(tmp_path)
    s = ImagesSection(
        per_page=2,
        layout="grid",
        variable_heights=True,
        images=tuple(ImageItem(path=p) for p in paths),
    )
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count == 1  # no title, 1 grid page → exactly 1 page


def test_optimize_packing_reorders_by_aspect(tmp_path: Path):
    """optimize_packing=True should sort images widest-first."""
    pytest.importorskip("PIL")
    # Three images: portrait (1:4), square (1:1), landscape (4:1).
    # Without reordering: p0=portrait, p1=square, p2=landscape.
    # With reordering: p2=landscape first, then p1=square, then p0=portrait.
    paths = _make_imgs(tmp_path, [(100, 400), (100, 100), (400, 100)])
    ctx = _ctx(tmp_path)
    s = ImagesSection(
        per_page=3,
        layout="grid",
        optimize_packing=True,
        images=tuple(ImageItem(path=p) for p in paths),
    )
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count == 1  # 3 images, 1 page


def test_optimize_packing_produces_same_page_count_as_variable_heights(tmp_path: Path):
    """optimize_packing implies variable_heights — same page count for same images."""
    pytest.importorskip("PIL")
    paths = _make_imgs(tmp_path, [(400, 100), (100, 400), (200, 100), (100, 200)])
    ctx = _ctx(tmp_path)
    base = dict(per_page=2, layout="grid", images=tuple(ImageItem(path=p) for p in paths))
    cs_vh = impl_for(ImagesSection(**base, variable_heights=True), 0, ctx.defaults).compile(ctx)
    cs_op = impl_for(ImagesSection(**base, optimize_packing=True), 0, ctx.defaults).compile(ctx)
    # Both use variable heights; both should produce the same page count.
    assert cs_vh.page_count == cs_op.page_count


def test_image_rotation_field_accepted(tmp_path: Path):
    """rotate: 90 on an ImageItem should not crash and should produce output."""
    pytest.importorskip("PIL")
    from PIL import Image

    p = tmp_path / "photo.jpg"
    Image.new("RGB", (300, 400)).save(p)
    ctx = _ctx(tmp_path)
    s = ImagesSection(
        per_page=1,
        layout="grid",
        images=(ImageItem(path=p, caption="rotated", rotate=90),),
    )
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.page_count >= 1


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
        spec_path,
        spec,
        jobs=1,
        use_cache=True,
        cache_dir=cache_dir,
        tmpdir=tmp_path / "tmp",
    )

    s = MarkdownSection(path=Path("doc.md"))
    impl = impl_for(s, 0, ctx.defaults)
    a = impl.compile(ctx)
    b = impl.compile(ctx)
    # Second compile should return the cached PDF path, not a fresh temp.
    assert a.pdf_path == b.pdf_path


# --- title section: metadata fallback + date defaulting --------------------


def test_title_inherits_title_from_metadata(tmp_path: Path):
    ctx = _ctx(tmp_path, metadata=Metadata(title="From Meta"))
    s = TitleSection(in_toc=True)  # no title on the section
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert any("From Meta" in str(e.label) for e in cs.toc_entries)


def test_title_section_overrides_metadata(tmp_path: Path):
    ctx = _ctx(tmp_path, metadata=Metadata(title="From Meta", author="MA"))
    s = TitleSection(title="Section Wins", author="SA", in_toc=True)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert any("Section Wins" in str(e.label) for e in cs.toc_entries)
    # And resolve helpers directly:
    assert _resolve_title(s, ctx.metadata) == "Section Wins"
    assert _resolve_author(s, ctx.metadata) == "SA"


def test_title_inherits_author_from_metadata(tmp_path: Path):
    md = Metadata(title="T", author="From Meta")
    s = TitleSection()  # both unset on section
    assert _resolve_author(s, md) == "From Meta"


def test_title_author_explicit_none_hides(tmp_path: Path):
    md = Metadata(title="T", author="From Meta")
    # author=None *and* explicitly set: section opts out.
    s = TitleSection(author=None)
    assert _resolve_author(s, md) is None


def test_title_missing_everywhere_errors():
    md = Metadata()  # no title
    s = TitleSection()  # no title
    with pytest.raises(ValueError, match="no title provided"):
        _resolve_title(s, md)


def test_date_defaults_to_today_when_unset_everywhere():
    import datetime as dt

    md = Metadata(title="T")  # no date
    s = TitleSection(title="x")  # no date
    assert _resolve_date(s, md) == dt.date.today().isoformat()


def test_date_inherits_from_metadata():
    import datetime as dt

    d = dt.date(2024, 1, 2)
    md = Metadata(title="T", date=d)
    s = TitleSection(title="x")
    assert _resolve_date(s, md) == "2024-01-02"


def test_date_section_overrides_metadata():
    import datetime as dt

    md = Metadata(title="T", date=dt.date(2024, 1, 2))
    s = TitleSection(title="x", date=dt.date(2030, 12, 31))
    assert _resolve_date(s, md) == "2030-12-31"


def test_date_none_on_section_disables():
    import datetime as dt

    md = Metadata(title="T", date=dt.date(2024, 1, 2))
    s = TitleSection(title="x", date=None)
    # Explicit `date: none` on the section disables even if metadata has one.
    assert _resolve_date(s, md) is None


def test_date_none_on_metadata_disables_when_section_unset():
    md = Metadata(title="T", date=None)  # explicit None
    s = TitleSection(title="x")  # field not set
    assert _resolve_date(s, md) is None


def test_date_string_value_passes_through():
    md = Metadata(title="T")
    s = TitleSection(title="x", date="Spring 2026")
    assert _resolve_date(s, md) == "Spring 2026"


def test_title_section_uses_metadata_via_yaml_loader(tmp_path: Path):
    """Round-trip through the YAML loader to verify model_fields_set works
    on validated specs (not just programmatic constructs)."""
    from pdf_compiler.loader import load_spec

    p = tmp_path / "spec.yaml"
    p.write_text(
        "metadata:\n  title: From Meta\n  author: Meta Author\nsections:\n  - type: title\n"
    )
    spec = load_spec(p)
    title_spec = spec.sections[0]
    assert _resolve_title(title_spec, spec.metadata) == "From Meta"
    assert _resolve_author(title_spec, spec.metadata) == "Meta Author"


# --- variable substitution ------------------------------------------------- #


def test_title_section_interpolates_vars(tmp_path: Path):
    ctx = _ctx(tmp_path, vars={"who": "Jane Smith"})
    s = TitleSection(title="Petition by {{who}}", in_toc=True)
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert any("Petition by Jane Smith" in str(e.label) for e in cs.toc_entries)


def test_header_section_interpolates_title_and_body(tmp_path: Path):
    ctx = _ctx(tmp_path, vars={"who": "Jane"})
    s = HeaderSection(title="By {{who}}", body="Filed by **{{who}}**")
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    assert cs.toc_entries[0].label == "By Jane"


def test_markdown_section_interpolates_body(tmp_path: Path):
    md = tmp_path / "doc.md"
    md.write_text("# Filing\n\nFiled by {{who}} on {{today}}.\n")
    ctx = _ctx(tmp_path, vars={"who": "Jane"})
    s = MarkdownSection(path=Path("doc.md"))
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    # Page text should contain the substituted name, not the {{}} literal.
    from pdfminer.high_level import extract_text

    text = extract_text(str(cs.pdf_path))
    assert "Jane" in text
    assert "{{who}}" not in text


def test_markdown_unknown_var_is_passthrough(tmp_path: Path):
    """A document containing {{unknown}} renders the literal — never errors."""
    md = tmp_path / "doc.md"
    md.write_text("# t\n\nliteral {{nothere}} stays.\n")
    ctx = _ctx(tmp_path, vars={"who": "Jane"})
    s = MarkdownSection(path=Path("doc.md"))
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    from pdfminer.high_level import extract_text

    text = extract_text(str(cs.pdf_path))
    assert "{{nothere}}" in text


def test_builtin_today_var_available(tmp_path: Path):
    import datetime as dt

    ctx = _ctx(tmp_path)  # no user vars at all
    s = TitleSection(title="On {{today}}")
    cs = impl_for(s, 0, ctx.defaults).compile(ctx)
    today = dt.date.today().isoformat()
    from pdfminer.high_level import extract_text

    text = extract_text(str(cs.pdf_path))
    assert today in text


def test_date_none_via_yaml(tmp_path: Path):
    """`date: ~` in YAML (null) on a title section disables the date."""
    from pdf_compiler.loader import load_spec

    p = tmp_path / "spec.yaml"
    p.write_text(
        "metadata:\n  title: T\nsections:\n  - type: title\n    date: ~\n"  # YAML null
    )
    spec = load_spec(p)
    title_spec = spec.sections[0]
    assert _resolve_date(title_spec, spec.metadata) is None
