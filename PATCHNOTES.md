# Patch Notes

All notable changes to `pdf-compiler` are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Image downsampling (`images:` block + `--max-ppi`).** A
  post-assembly pass that caps embedded raster resolution to a
  pixels-per-inch ceiling. For each image it walks the page content
  streams (recursing into form XObjects) to recover the matrix the
  image is painted with, computes its effective resolution at its
  *largest* placement, and resamples anything above the ceiling. The
  pass is opt-in and lossy — off unless `images.max_ppi` is set:
  - `compression: auto` (default) re-encodes opaque RGB/grayscale
    photos as JPEG and keeps palette/CMYK/1-bit/masked images lossless
    (Flate); `jpeg`/`flate` force a path. `jpeg_quality` (default 82)
    tunes the lossy path; `tolerance` (default 1.1) skips images barely
    over the ceiling.
  - Soft-mask (alpha) planes are downsampled to match their base image,
    always losslessly. Stencil image-masks are skipped, images are
    never upscaled, and an image is rewritten only when the result is
    genuinely smaller.

  `pdfc compile --max-ppi N` overrides the spec per run, and the
  compile summary reports how many images were resampled and the bytes
  saved.
- **Font reconciliation (`fonts:` block + `--reconcile`).** A
  post-assembly pass that shrinks the output by coalescing duplicate
  embedded fonts, with three escalating tiers:
  - `dedupe` (new default): built-in, lossless, zero-dependency —
    coalesces byte-identical font-program streams
    (`/FontFile{,2,3}`) and their `/ToUnicode` / `/CIDSet` streams so
    identical data is stored once and referenced many times.
  - `merge`: adds a lossless structural recompaction via `qpdf`.
  - `deep`: additionally tries Ghostscript (can fuse divergent
    subsets), behind a verification gate.

  Every external pass is accepted only if the result preserves page
  count, named destinations, GoTo links, page labels, and the
  outline — *and* is smaller; otherwise it is discarded and the safe
  file kept. (Ghostscript, the strongest optimizer, flattens our
  `/Names/Dests` tree and every internal link; the gate catches this
  and falls back to `qpdf`.) External tools are optional — every tier
  degrades cleanly to built-in `dedupe` when they're absent.

  `embed_standard_14: false` additionally unembeds standard-14 fonts
  (Helvetica/Times/Courier/Symbol/ZapfDingbats), preserving
  widths/encoding so metrics are unchanged; CID and custom families
  are left alone. `external_tool` pins or forbids the helper binary.
  `pdfc compile --reconcile {off,dedupe,merge,deep}` overrides the
  spec per run, and the compile summary reports what the pass did.

## [0.5.1] — 2026-05-31

## [0.5.0] — 2026-05-30

### Fixed
- **Markdown heading clicks in the ToC now land on the heading itself.**
  Previously every markdown-heading entry in the ToC resolved to the
  section's first page (and the page-number column showed the same page
  for every heading in the section). The compile step now reads
  WeasyPrint's `/Names/Dests` tree from the rendered section PDF to
  recover the real `(page, x, y)` for each heading, and assembly emits
  `/XYZ x y` destinations so clicks land exactly at the anchor — both
  in the main ToC and in PDF outline bookmarks.
- **ToC links are rewritten by entry index, not position.** The old
  positional matching bailed out silently whenever a ToC row straddled
  a page break (WeasyPrint emits two annotations for it), leaving every
  link pointing back at the ToC page. Links are now matched by the
  `__toc_N` / `__stoc_N` index already on each annotation.
- **Page labels restart correctly when front-matter and body share a
  numbering style.** With both set to `arabic`, the body counter now
  restarts at 1 instead of continuing the front-matter count.
- **`extract_named_dests` no longer crashes on a malformed destination**
  (null page reference) and preserves the top-of-page fallback when a
  destination coordinate is absent rather than forcing it to the page
  edge.

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
