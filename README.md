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

Requires Python ≥ 3.14. WeasyPrint pulls in cairo/pango — on macOS
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
  regularize_pages: false    # scale embedded PDFs to fit page_size
  page_numbering:
    enabled: false           # stamp page numbers on each page
    front_matter: roman      # roman | arabic | none
    body: arabic
    position: bottom-center  # bottom-{center,left,right}, top-…

vars:                        # see "Variables" below
  petitioner: "Jane Smith"
  filing_no:  "I-751"

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
  subtoc: false                      # add a mini-ToC for this part
  subtoc_depth: 3
```

Set `subtoc: true` to follow the divider with a mini table-of-contents
listing every entry from this header up to the next `header` section
(or the end of the document). Useful for multi-part documents where
each part deserves its own overview page.

#### `markdown` — chapter rendered from a `.md` file

```yaml
- type: markdown
  path: chapters/intro.md
  title: "Introduction"      # optional; else the first H1 in the file
  index_headers: true        # optional; else inherits defaults.index_headers
```

When `index_headers` is on, every heading in the markdown becomes a
nested ToC entry. The heading hierarchy maps to ToC depth.

Markdown rendering uses CommonMark with GFM-style pipe tables,
strikethrough (`~~gone~~`), and URL autolinking enabled.

#### `pdf` — embed an existing PDF

```yaml
- type: pdf
  path: vendor/q1-report.pdf
  pages: "1-10,15,20-"       # 1-based, inclusive; "20-" = to end
  title: "Q1 Vendor Report"  # optional; else the file stem
  rotate: 0                  # 0 | 90 | 180 | 270
  preserve_bookmarks: true   # merge included PDF's outline under this entry
  regularize_pages: null     # null=inherit defaults.regularize_pages; true/false to override
  in_toc: true
```

Set `regularize_pages: true` (or enable it on `defaults`) when the
embedded PDFs come from a mix of sources — letter scans, A4 PDFs, and
oversized originals. Each source page is scaled & centered onto a
target-sized blank page so the final document has uniform on-screen
dimensions. Pages that already match the target are passed through
untouched.

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
  per_page: 4                # images per page (grid layout)
  layout: grid               # grid | autopack
  captions: below            # below | above | overlay | none
  variable_heights: false    # proportional row heights, preserve order
  optimize_packing: false    # sort by aspect ratio + proportional heights
  images:
    - { path: site/a.jpg, caption: "Entrance, looking north" }
    - { path: site/b.jpg, caption: "South wall, post-repair" }
    - { path: site/c.jpg, caption: "Portrait shot", rotate: 90 }
```

**Layout modes:**

- **`grid`** places exactly `per_page` images per page on a √N grid
  (e.g. `per_page: 4` → 2×2; `per_page: 6` → 2×3). By default each
  row gets an equal share of the page height.
- **`autopack`** uses a justified-rows algorithm: images fill each row
  to the page width, rows stack until the page is full. Variable images
  per page, non-overlapping by construction.

**Packing options (grid layout):**

- **`variable_heights: true`** — row heights are proportional to the
  natural dimensions of the images in that row rather than equal
  fractions. A page with one portrait and one landscape image fills
  edge-to-edge instead of leaving up to 40% whitespace. Image order is
  preserved.
- **`optimize_packing: true`** — implies `variable_heights` and also
  sorts images widest-first before assigning pages, grouping similar
  aspect ratios together for the most uniform pages. Image order is
  **not** preserved.

**Per-image rotation:**

EXIF orientation is applied automatically. For manual corrections, set
`rotate` (degrees clockwise) on any image:

```yaml
images:
  - { path: photo.jpg, caption: "Normal" }
  - { path: sideways.jpg, caption: "Rotated CW", rotate: 90 }
  - { path: upside_down.jpg, rotate: 180 }
```

---

## Variables

Any user-facing string — titles, subtitles, captions, image captions,
markdown content, header bodies, and PDF metadata fields — can
reference `{{ name }}` placeholders. Names resolve from a merged dict
of user-defined `vars:` and a set of builtins:

| name         | value                                  |
|---|---|
| `today`      | today's date in ISO format (`2026-05-21`) |
| `year`       | four-digit year (`2026`)               |
| `month`      | zero-padded month (`05`)               |
| `day`        | zero-padded day (`21`)                 |
| `month_name` | full English month name (`May`)        |

User entries in `vars:` override builtins with the same name.

```yaml
vars:
  petitioner: "Jane Smith"
  case_no:    "MSC-2026-0421"

sections:
  - type: title
    title:    "Petition by {{petitioner}}"
    subtitle: "Filed {{today}} — Case {{case_no}}"

  - type: markdown
    path: cover_letter.md   # may also use {{petitioner}}, {{today}}, …
```

Unknown names render as the literal source (`{{nothere}}`) — existing
documents that happen to contain double-brace text are not broken by
the feature. Values are stringified with `str()`, so YAML ints,
floats, and bools work as expected. Changing a variable invalidates
the section cache for any section that interpolated it.

---

## How it works

The pipeline is functional and runs in four phases:

```
parse → validate → resolve paths →
  compile non-deferred sections (parallel) →
  reserve pages for ToC + subtoc headers →
  render deferred sections against resolved offsets →
  assemble + metadata + outline + page-number stamps → out.pdf
```

- **Sections** speak in *named destinations* (`sec-0003-intro-h2-foo`),
  never in page numbers. Each section's `compile()` returns a temp
  PDF plus a list of destination names. Assembly remaps them to global
  page references via a `/Catalog/Names/Dests` name tree. As a free
  consequence, every `<a href="#anchor">` link WeasyPrint emits in a
  markdown body or in the ToC becomes a working PDF link — no link
  rewriting needed.

- **Two-pass deferred rendering, no iteration.** Step 1 compiles
  every non-deferred section so we know its page count. Step 2
  reserves `N` blank pages at each deferred slot (main ToC, plus any
  header with `subtoc: true`) based on entry count, then renders each
  deferred section with the resolved page labels. If anything
  overflows, the pipeline widens the plan once and re-renders.
  Named destinations mean page numbers in any ToC always resolve
  correctly regardless of where it lands.

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

- **Global page numbers.** Set `defaults.page_numbering.enabled: true`
  to stamp the resolved label onto every page during the final
  assembly step. The stamp uses the same roman/arabic split as the
  ToC, so a Part II divider page reads "1" while a title page reads
  "i". A single shared Helvetica resource keeps the per-page overhead
  to one small content-stream object.

- **Page-size regularization.** With `regularize_pages: true` the
  embedder wraps each source page onto a fresh target-sized page via
  pikepdf's overlay primitive, scaling & centering to fit while
  preserving aspect ratio. Pages already at the target size are kept
  in place (no overhead) — only oversized or undersized inputs pay
  the wrap cost.

---

## Development

```bash
uv sync                       # install deps + dev tools
uv run pytest                 # 158 tests; runs in ~4s
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
├── assemble.py             # pikepdf concat + named-destinations + page-number stamps
├── md_ast.py               # markdown-it AST → headings + anchor injection
├── numbering.py            # roman / arabic page-number formatting
├── page_range.py           # "1-10,15,20-" parser
├── lengths.py              # CSS length parser + page-size table
├── interpolate.py          # {{name}} variable substitution + builtins
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
│   └── toc.py              # two-pass ToC renderer (also: subtoc headers)
├── render/
│   ├── html.py             # jinja2 + WeasyPrint
│   └── templates/*.{html,css}
└── layout/
    └── pack.py             # grid + justified-rows image packers

tests/
├── unit/                   # ~135 unit tests, table-driven + hypothesis
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
two markdown chapters, a header divider with a subtoc, and a 5-image
gallery), with stamped page numbers and roman/arabic front-matter
numbering enabled:

```bash
uv run pdfc compile examples/report.yaml
```

`examples/minimal.yaml` is the smallest possible spec.

### Real-world: an evidence packet

Bundling dozens of scanned-and-non-scanned PDFs into a single
navigable document (immigration evidence, legal exhibits, audit
binders) is what motivated the three "uniform-output" features —
global page numbers, subtoc parts, and page-size regularization.

```yaml
output: evidence.pdf

metadata:
  title: "I-751 Joint Petition Evidence"
  author: "Petitioner Name"

defaults:
  page_size: letter
  regularize_pages: true          # scanned A4/legal pages → letter
  page_numbering:
    enabled: true                 # stamp global numbers on every page
    body: arabic
    position: bottom-center

sections:
  - type: title
    subtitle: "Supporting Documentation"

  - type: toc
    depth: 2

  - type: header
    title: "Identity & Status"
    subtitle: "Petitioner and beneficiary identity documents"
    subtoc: true
  - type: pdf
    path: "[Main Form] I-751.pdf"
  - type: pdf
    path: "Green Card.pdf"
  - type: pdf
    path: "Iain Passport.pdf"

  - type: header
    title: "Financial Co-mingling"
    subtitle: "Joint accounts, tax returns, shared expenses"
    subtoc: true
  - type: pdf
    path: "2025 Tax Return.pdf"
  - type: pdf
    path: "Joint Checking Opening.pdf"
  - type: pdf
    path: "Apple Card Statements - First Pages.pdf"

  - type: header
    title: "Joint Residence"
    subtoc: true
  - type: pdf
    path: "6629 Fathom Way Goleta Lease Weissburg Moreno Jun 2024 signed.pdf"
  - type: pdf
    path: "PGE Bills - First Pages.pdf"

  - type: images
    title: "Photographs"
    layout: autopack
    captions: below
    images:
      - { path: photos/wedding.jpg,    caption: "Wedding, June 2024" }
      - { path: photos/anniversary.jpg, caption: "Anniversary, June 2025" }
```

Every embedded PDF — whether the original was 8.5×11", scanned at
A4, or a phone-photographed image — comes out at uniform letter size.
Every page bears a sequential arabic page number that matches the
top-level ToC and the per-section subtoc.
