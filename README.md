# pdf-compiler

Stitch large PDFs from a YAML spec. Title pages, clickable tables of
contents, markdown sections with auto-indexed headings, embedded PDFs
with page-range selection, and packed image galleries — all from one
declarative file.

```bash
uv run pdfc compile spec.yaml -o out.pdf
```

---

## Install

```bash
# clone, then:
uv sync
```

The console script `pdfc` is installed into the project venv. Run it
with `uv run pdfc ...` or activate the venv with `source .venv/bin/activate`
and call `pdfc` directly.

Requires Python ≥ 3.11. WeasyPrint pulls in cairo/pango — on macOS
`brew install cairo pango gdk-pixbuf libffi` is the usual prerequisite;
on Debian/Ubuntu, `apt install libcairo2 libpango-1.0-0 libpangoft2-1.0-0`.

---

## Quickstart

A minimal spec:

```yaml
# minimal.yaml
output: out.pdf
metadata:
  title: My Document

sections:
  - type: title
    title: My Document
    subtitle: A demonstration
    date: 2026-05-21

  - type: toc

  - type: markdown
    path: intro.md
```

Compile it:

```bash
uv run pdfc compile minimal.yaml
```

The output PDF has a title page, a clickable ToC pointing at every
markdown heading, and the rendered markdown body.

---

## CLI

```
pdfc compile  SPEC [--out OUT] [-j N] [--no-cache]
pdfc validate SPEC
pdfc watch    SPEC [--out OUT]
pdfc cache    clear
pdfc --version
```

- **`compile`** runs the full pipeline and writes the output PDF.
  `-j N` sets the worker count for parallel section compilation
  (default: `cpu_count() - 1`). `--no-cache` forces a fresh build.
- **`validate`** parses the spec and checks every referenced input
  (markdown files exist, PDFs open, page ranges are in bounds, image
  files decode) without producing any output. Exits non-zero on
  problems — useful in CI.
- **`watch`** runs an initial compile, then re-runs on every change
  under the spec's directory. Errors don't kill the watcher.
- **`cache clear`** wipes every cached compiled-section PDF from the
  user cache directory (`$XDG_CACHE_HOME/pdf-compiler` or
  `~/.cache/pdf-compiler`).

---

## The YAML spec

The top-level keys are `output`, `metadata`, `defaults`, and
`sections`. Only `sections` is required.

```yaml
output: build/report.pdf

metadata:
  title:   "Annual Report 2025"
  author:  "Ivan Weissburg"
  subject: "Fiscal year summary"
  keywords: [report, 2025, demo]

defaults:
  index_headers: true        # markdown headings become ToC entries
  page_size: letter          # letter | legal | a4 | a5 | tabloid
  margin: 0.75in
  page_numbering:
    front_matter: roman      # roman | arabic | none
    body: arabic
    position: bottom-center  # bottom-{center,left,right}, top-…

sections:
  - …                        # see below
```

Unknown keys are rejected with a YAML line number — typos surface
immediately instead of being silently ignored.

### Section types

Each section has a `type` field that selects its schema. Sections
appear in the output in the order they're listed.

#### `title` — cover page

```yaml
- type: title
  title:    "Annual Report 2025"      # optional; falls back to metadata.title
  subtitle: "Fiscal Year Summary"     # optional
  author:   "Author Name"             # optional; falls back to metadata.author
  date:     2026-05-21                # optional; see below
  front_matter: true                  # use roman numerals for this page
  in_toc:   false                     # default: don't list in ToC
```

`title`, `author`, and `date` all fall back to the top-level
`metadata` block when omitted on the section, so a minimal cover can
be as short as:

```yaml
metadata:
  title: "Annual Report 2025"
  author: "Author Name"
sections:
  - type: title
```

`date` resolves in this order: section wins → else metadata → else
today's date. Setting `date: ~` (YAML null) at either level
explicitly disables the date.

#### `toc` — table of contents

```yaml
- type: toc
  title: "Table of Contents"   # optional, default shown
  depth: 3                     # max heading level to include (1–6)
  front_matter: true
```

The ToC is rendered with dotted leaders and resolved page numbers.
Every entry is a clickable internal link. Place it anywhere in the
section list; you can include multiple ToCs (e.g., one per part).

#### `header` — divider page

```yaml
- type: header
  title:    "Part II — Financials"
  subtitle: "Detailed breakdowns"    # optional
  body: |                            # optional markdown shown below
    Introductory paragraph in **markdown**.
  in_toc: true
```

#### `markdown` — chapter rendered from a `.md` file

```yaml
- type: markdown
  path: chapters/intro.md
  title: "Introduction"      # optional; else the first H1 in the file
  index_headers: true        # optional; else inherits defaults.index_headers
```

When `index_headers` is on, every heading in the markdown becomes a
nested ToC entry. The heading hierarchy maps to ToC depth.

#### `pdf` — embed an existing PDF

```yaml
- type: pdf
  path: vendor/q1-report.pdf
  pages: "1-10,15,20-"       # 1-based, inclusive; "20-" = to end
  title: "Q1 Vendor Report"  # optional; else the file stem
  rotate: 0                  # 0 | 90 | 180 | 270
  preserve_bookmarks: true   # merge included PDF's outline under this entry
  in_toc: true
```

Page-range syntax:

| token   | meaning |
|---|---|
| `5`     | only page 5 |
| `2-4`   | pages 2 through 4 (inclusive) |
| `5-`    | from page 5 to the end |
| `-3`    | from page 1 to page 3 |
| omitted | all pages |

#### `images` — packed image gallery

```yaml
- type: images
  title: "Site Photographs"
  per_page: 4                # used by grid layout
  layout: grid               # grid | autopack
  captions: below            # below | above | overlay | none
  images:
    - { path: site/a.jpg, caption: "Entrance, looking north" }
    - { path: site/b.jpg, caption: "South wall, post-repair" }
```

Two layout modes:

- **`grid`** packs exactly `per_page` images per page on a √N grid
  (e.g. `per_page: 4` → 2×2; `per_page: 6` → 2×3). Predictable, good
  when images share an aspect ratio.
- **`autopack`** uses a Flickr-style justified-rows algorithm: each
  page is filled with rows of images that justify to a target height.
  Pages break when vertical space runs out. Layout is non-overlapping
  by construction.

---

## How it works

The pipeline is functional and runs in four phases:

```
parse → validate → resolve paths →
  compile sections (parallel) →
  reserve ToC pages →
  render ToC →
  assemble + metadata + outline → out.pdf
```

- **Sections** speak in *named destinations* (`sec-0003-intro-h2-foo`),
  never in page numbers. Each section's `compile()` returns a temp
  PDF plus a list of destination names. Assembly remaps them to global
  page references via a `/Catalog/Names/Dests` name tree. As a free
  consequence, every `<a href="#anchor">` link WeasyPrint emits in a
  markdown body or in the ToC becomes a working PDF link — no link
  rewriting needed.

- **Two-pass ToC, no iteration.** Step 1 compiles every non-ToC
  section so we know its page count. Step 2 reserves `N` blank pages
  at each ToC position based on entry count, then renders the ToC
  with resolved page labels. If the rendered ToC overflows its
  reservation, the pipeline widens the plan once and re-renders.
  Named destinations mean page numbers in the ToC always resolve
  correctly regardless of where the ToC lands.

- **Content-addressed cache.** Each section's output is keyed by
  `blake3(spec_section + defaults + input_file_bytes + package_version)`.
  Re-running on the same inputs short-circuits to the cached PDF.
  Modify one markdown file and only that section recompiles.

- **Parallel compilation** uses `multiprocessing` (WeasyPrint isn't
  thread-safe). The pool is bypassed when `-j 1` or when there's
  only one section.

- **Front matter vs body numbering.** Sections marked
  `front_matter: true` produce roman-numeral page labels in the ToC;
  body sections get arabic numerals starting at 1.

---

## Development

```bash
uv sync                       # install deps + dev tools
uv run pytest                 # 103 tests; runs in ~2s
uv run pytest --cov           # with coverage
uv run ruff check src tests   # lint
```

Project layout:

```
src/pdf_compiler/
├── cli.py                  # typer CLI surface (lazy imports)
├── spec.py                 # pydantic models, discriminated union
├── loader.py               # ruamel.yaml → pydantic with line-number errors
├── pipeline.py             # public compile_spec / validate_spec / watch_spec
├── pipeline_impl.py        # orchestration (parallel compile + ToC + assemble)
├── context.py              # BuildContext (paths, cache, tmpdir, workers)
├── cache.py                # blake3 content-addressed section cache
├── assemble.py             # pikepdf concat + named-destinations + outline
├── md_ast.py               # markdown-it AST → headings + anchor injection
├── numbering.py            # roman / arabic page-number formatting
├── page_range.py           # "1-10,15,20-" parser
├── validate.py             # standalone input validation
├── watcher.py              # watchdog-based --watch
├── util.py                 # slugify
├── sections/
│   ├── base.py             # Section protocol, CompiledSection, TocEntry
│   ├── _common.py          # SectionMeta, helpers
│   ├── title.py            #   ↓
│   ├── header.py           #   each section type's impl
│   ├── markdown_doc.py     #   ↓
│   ├── pdf_ref.py          #   ↓
│   ├── images.py           #   ↓
│   └── toc.py              # two-pass ToC renderer
├── render/
│   ├── html.py             # jinja2 + WeasyPrint
│   └── templates/*.{html,css}
└── layout/
    └── pack.py             # grid + justified-rows image packers

tests/
├── unit/                   # 95 unit tests, table-driven + hypothesis
├── integration/            # full-pipeline assertions via pdfplumber
├── conftest.py             # shared fixtures (make_pdf, png_bytes)
└── fixtures/

examples/                   # demonstration specs
examples_content/           # markdown + images referenced by examples
```

The CLI module only imports heavy dependencies inside function
bodies; `pdfc --help` and `pdfc validate` start in well under 200 ms.

---

## Examples

`examples/report.yaml` exercises every section type (title, ToC,
two markdown chapters, a header divider, and a 5-image gallery):

```bash
uv run pdfc compile examples/report.yaml
```

`examples/minimal.yaml` is the smallest possible spec.
