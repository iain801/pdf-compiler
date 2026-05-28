# Patch Notes

All notable changes to `pdf-compiler` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`font_family` and `font_size` on `Defaults` and `MarkdownSection`.**
  Body-text typography is now configurable per-spec or per-markdown
  section. `font_family` accepts any font installed on the rendering
  host (resolved via fontconfig / Core Text) — single names auto-quote,
  comma-separated stacks pass through. `font_size` accepts any CSS
  length (`11pt`, `1.05em`, …). Headings keep their own font stack.
  Implemented via CSS variables on `:root`; `base.css` uses
  `var(--body-font, …)` / `var(--body-font-size, 11pt)` with the
  original Helvetica/11pt as fallback.

### Changed
- Refactored the per-template `:root { … }` style block into a single
  `render.html.root_vars()` helper that builds the declaration from
  context; all five templates now share one `{{ root_style|safe }}`
  injection point.

## [0.4.0] — 2026-05-27

### Added
- **`/PageLabels` for PDF viewers.** Every assembled document now
  carries a `/Catalog/PageLabels` number tree so viewers (Preview,
  Acrobat, Chrome) show the document's logical labels (`i`, `ii`,
  `1`, `2`, …) in the sidebar / page indicator — not just the
  sequential page index. Installed unconditionally; independent of
  on-page stamping.
- **`flatten_annotations`** on `Defaults` and `PdfSection`: bake form
  fields, sticky-note comments, highlights, freetext, and stamps from
  embedded PDFs into the page content stream. Internal `/Link`
  annotations are preserved (ToC links and outline destinations
  continue to work).
- **`in_toc` and `preserve_bookmarks` on `Defaults`.** Both fields are
  now inheritable per the existing `regularize_pages` /
  `flatten_annotations` pattern: section value (if not `null`) wins,
  otherwise the `defaults` value applies. `TitleSection.in_toc` keeps
  its historical default of `False` (titles are a special case).
- **GitHub Actions CI/CD.** A `CI` workflow runs ruff lint, ruff
  format check, and pytest on Python 3.12 + 3.13 on every push/PR to
  `main`, then builds sdist + wheel. A `Release` workflow publishes
  to PyPI (via OIDC trusted publishing) and creates a GitHub Release
  on `v*` tags.

### Changed
- **Strict ruff lint + format across the codebase.** Hoisted lazy
  imports to module top in `pack.py`, `images.py`, `watcher.py`, and
  `cli.py`; replaced `F821` suppression in `sections/base.py` with a
  `TYPE_CHECKING` guard; narrowed broad `except Exception` clauses in
  `validate.py`, `watcher.py`, and `pack.py` to their actually-expected
  error types; renamed the CLI handler from `compile` to `compile_cmd`
  (via `@app.command("compile")`) so it no longer shadows a builtin.
  Per-file `B008` ignore for `cli.py` only — Typer requires
  `Argument(...)`/`Option(...)` as defaults by design.
- **Markdown rendering** now enables `breaks: true` and `html: true`
  in markdown-it: single newlines render as hard line breaks (no more
  address-block collapse to one line), and raw `<br>`/HTML in markdown
  source passes through to the PDF.

### Fixed
- **Python 3.12 compatibility.** Ruff's `target-version` was set to
  `py314`, which let it strip parens from `except (A, B):` clauses
  (bare-comma form is only valid on Python 3.14+ via PEP 758) and
  pushed `batched(..., strict=False)` (the `strict` kwarg arrived in
  3.13). Both broke imports on 3.12 despite `requires-python =
  ">=3.12"`. Target dropped to `py312`, parens restored,
  `batched()` call reverted to its 2-arg form.
- **Bare-comma `except` clauses** in `loader.py` and `md_ast.py`
  parenthesised — semantically identical on 3.14+ but only valid as
  a tuple in 3.12 / 3.13.

## [0.3.1] — 2026-05-25

- Read `__version__` from installed package metadata so the CLI's
  `--version` flag matches whatever's actually installed, not a
  hard-coded constant.
- Preserve newlines inside `{{ var }}` substitutions as CommonMark
  hard line breaks (`  \n`) when interpolating into markdown content.

## [0.3.0] — 2026-05-23

- **Clickable ToC and subtoc links** in the final PDF. Self-referencing
  `<a href="#id">` annotations emitted by WeasyPrint inside ToC pages
  are rewritten as cross-document `/GoTo` actions pointing at the real
  destinations.

## [0.2.0] — 2026-05-22

- **Image gallery: `optimize_packing` and `variable_heights`** modes
  for justified-rows / variable-height grid layouts; per-image
  `rotate` field; EXIF orientation handling.
- **Watcher: scoped file watch.** `pdfc watch` now only reacts to the
  spec's actual input files instead of every change under the
  directory; fixes the infinite recompile loop triggered by writing
  the output back into a watched dir.
- **GFM extras**: pipe tables, strikethrough, URL autolinking enabled
  in markdown sections.
- **Variable substitution.** `{{ name }}` placeholders in titles,
  subtitles, captions, header bodies, markdown content, and PDF
  metadata, sourced from a merged dict of user `vars:` and builtins
  (`today`, `year`, `month`, `day`, `month_name`).
- **Global page-number stamps** and per-header `subtoc:` mini-ToCs.
- **`regularize_pages`**: scale & center embedded PDF pages onto a
  target-sized blank page so mixed-source documents come out at
  uniform dimensions.
