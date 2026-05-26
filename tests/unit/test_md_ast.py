from __future__ import annotations

from pdf_compiler.md_ast import first_h1_text, render_with_headings


def test_extracts_headings_in_order():
    html, hs = render_with_headings("# A\n\n## A.1\n\n# B\n", id_prefix="sec1")
    assert [h.text for h in hs] == ["A", "B"]
    assert [h.text for h in hs[0].children] == ["A.1"]


def test_anchor_ids_are_injected():
    html, _ = render_with_headings("# Hello World\n", id_prefix="sec1")
    assert 'id="sec1-hello-world"' in html


def test_duplicate_headings_disambiguated():
    html, hs = render_with_headings("# Intro\n\n# Intro\n", id_prefix="sec3")
    ids = [h.anchor_id for h in hs]
    assert ids == ["sec3-intro", "sec3-intro-1"]


def test_first_h1_text():
    _, hs = render_with_headings("## not me\n\n# yes\n", id_prefix="s")
    assert first_h1_text(hs) == "yes"


def test_first_h1_text_none():
    _, hs = render_with_headings("## just sub\n", id_prefix="s")
    assert first_h1_text(hs) is None


def test_max_depth_filter():
    _, hs = render_with_headings(
        "# a\n\n## b\n\n### c\n\n#### d\n",
        id_prefix="s",
        max_depth=2,
    )

    # Should drop ### and #### entirely (not as children either).
    def walk(h):
        yield h
        for c in h.children:
            yield from walk(c)

    levels = sorted({n.level for r in hs for n in walk(r)})
    assert levels == [1, 2]


def test_tree_handles_jump_levels():
    """A jump from H1 to H3 should still nest sensibly (H3 under H1)."""
    _, hs = render_with_headings("# A\n\n### A.1.1\n", id_prefix="s")
    assert hs[0].text == "A"
    assert hs[0].children[0].text == "A.1.1"


def test_gfm_pipe_tables_render():
    """| header | ... | should produce a <table>, not appear as literal pipes."""
    md = "| Dates | Address |\n|---|---|\n| 2024 | 6629 Fathom Way |\n| 2025 | 3380 20th St |\n"
    html, _ = render_with_headings(md, id_prefix="s")
    assert "<table>" in html
    assert "<th>Dates</th>" in html
    assert "<td>6629 Fathom Way</td>" in html
    # And the literal pipe row text must not have leaked into the body.
    assert "| Dates |" not in html


def test_strikethrough_renders():
    html, _ = render_with_headings("~~gone~~\n", id_prefix="s")
    assert "<s>gone</s>" in html
