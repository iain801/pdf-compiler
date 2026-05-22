"""Walk a markdown-it-py token stream to:

  1. Inject stable ``id`` attributes on every heading (so PDF anchors work).
  2. Produce a hierarchical heading tree for the ToC / outline.

We never touch a string-based regex on the markdown — we manipulate the token
list and let markdown-it render the HTML. Anchor IDs are deterministic
(slug + counter on collision) so re-runs produce identical PDFs and cache.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token

from pdf_compiler.util import slugify


@dataclass(slots=True)
class Heading:
    """A heading in a markdown document, hierarchical."""

    level: int
    text: str
    anchor_id: str
    children: list["Heading"] = field(default_factory=list)


def make_md() -> MarkdownIt:
    """The shared markdown-it configuration.

    Built on the CommonMark preset, plus GFM extras users actually expect in
    documents: pipe tables, strikethrough, and autolinking.
    """
    md = MarkdownIt("commonmark", {"breaks": False, "html": False, "linkify": True})
    md.enable(["table", "strikethrough"])
    return md


def render_with_headings(
    md_text: str,
    *,
    id_prefix: str,
    max_depth: int = 6,
) -> tuple[str, list[Heading]]:
    """Render markdown to HTML and extract a heading tree.

    Returns ``(html, headings)`` — headings is a list of top-level
    :class:`Heading` nodes with descendants nested.
    """
    md = make_md()
    tokens = md.parse(md_text)
    _inject_anchor_ids(tokens, id_prefix=id_prefix)
    flat = _extract_headings_flat(tokens, max_depth=max_depth)
    tree = _build_heading_tree(flat)
    html = md.renderer.render(tokens, md.options, {})
    return html, tree


def first_h1_text(headings: list[Heading]) -> str | None:
    """Return the text of the first top-level heading, if any."""
    for h in headings:
        if h.level == 1:
            return h.text
    return None


# -- internals -------------------------------------------------------------- #


def _inject_anchor_ids(tokens: list[Token], *, id_prefix: str) -> None:
    """Mutate ``tokens`` so each heading_open gets a unique ``id`` attribute."""
    used: dict[str, int] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            # The next token (inline) holds the text content.
            text_tok = tokens[i + 1] if i + 1 < len(tokens) else None
            text = text_tok.content if text_tok is not None else ""
            slug = slugify(text)
            count = used.get(slug, 0)
            used[slug] = count + 1
            suffix = f"-{count}" if count else ""
            anchor = f"{id_prefix}-{slug}{suffix}"
            tok.attrSet("id", anchor)
            # Stash the resolved anchor + plain text for the extractor.
            tok.meta = (tok.meta or {})
            tok.meta["__pdf_compiler_anchor__"] = anchor
            tok.meta["__pdf_compiler_text__"] = text
        i += 1


def _extract_headings_flat(tokens: list[Token], *, max_depth: int) -> list[Heading]:
    out: list[Heading] = []
    for tok in tokens:
        if tok.type != "heading_open":
            continue
        # markdown-it's tag is "h1".."h6".
        try:
            level = int(tok.tag[1:])
        except (ValueError, IndexError):
            continue
        if level > max_depth:
            continue
        meta = tok.meta or {}
        anchor = meta.get("__pdf_compiler_anchor__")
        text = meta.get("__pdf_compiler_text__", "")
        if anchor is None:
            continue
        out.append(Heading(level=level, text=text, anchor_id=anchor))
    return out


def _build_heading_tree(flat: list[Heading]) -> list[Heading]:
    """Convert a flat sequence into a parent/child tree by level."""
    roots: list[Heading] = []
    stack: list[Heading] = []
    for h in flat:
        # Pop until we find a strictly shallower parent.
        while stack and stack[-1].level >= h.level:
            stack.pop()
        if stack:
            stack[-1].children.append(h)
        else:
            roots.append(h)
        stack.append(h)
    return roots
