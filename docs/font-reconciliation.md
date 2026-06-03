# Font reconciliation — design notes

Rationale and measurements behind the `fonts:` feature. User-facing usage
lives in the README ([Font reconciliation](../README.md#font-reconciliation));
this document is the *why*.

## The problem

Each section is rendered or embedded independently:

- Every markdown/title/toc/header section is a separate WeasyPrint render,
  and WeasyPrint subsets each font **per document** — so a family used in 30
  sections is embedded as 30 independent subsets.
- Every embedded source PDF carries its own font programs; exported/scanned
  PDFs routinely re-embed the same base fonts.

On a large packet (the motivating case: a ~381-page I-751 evidence
submission) this duplication dominates file size.

There are two *distinct* duplication modes, and they need different fixes:

| Mode | Cause | Fix |
|---|---|---|
| **A. Byte-identical programs** | Repeated source PDFs re-embedding the same base fonts; identical boilerplate | Hash + repoint (cheap, lossless) |
| **B. Subset fragmentation** | WeasyPrint subsets the same family once *per section* | Subset merge (hard) or architectural |

## Measurements (examples/report.yaml, 9 pages)

```
baseline file:        462,791 bytes
embedded font bytes:  117,964 bytes (~25% of the file)
font dicts:           29
unique FontDescriptors: 14
embedded program streams: 14   unique-by-content: 14   → 0 byte-identical dups
BaseFont histogram:   PT-Serif-Bold ×6, Hiragino-Sans ×6, …  ← Mode B
```

So even this tiny doc embeds the same two families six times each, as
*different subsets* (Mode B). Pure hash dedup (Mode A) finds nothing here —
the win on this doc requires subset merging.

External optimizers on the baseline:

```
mutool clean -gggg:   458,141 (99%)  — barely helps
qpdf (objstm+flate):  437,082 (94%)  — lossless
ghostscript /prepress: 352,285 (76%) — biggest, but…
```

…Ghostscript is **structurally destructive**:

```
                pages  dests  gotoLinks  pageLabels  outline
baseline          9     15       21        yes          5
ghostscript       9      0        0        yes          5   ← dests + links GONE
qpdf              9     15       21        yes          5   ← intact
```

Ghostscript flattens the `/Names/Dests` tree and every internal link. That
is the single most important constraint on this feature: **the biggest size
win silently breaks navigation.** It cannot be a default, and can only be
offered at all behind a hard verification gate.

## What shipped (`reconcile.py`)

Three tiers, escalating in power and (for the external ones) risk:

1. **`dedupe`** (default) — built-in, lossless, zero-dependency. Walks the
   combined object graph and coalesces byte-identical font-related streams
   (`/FontFile{,2,3}`, `/ToUnicode`, `/CIDSet`) to a single shared object,
   repointing references; orphans are GC'd on save. The dedup identity folds
   in the holding key and length/subtype markers so a Type1 `/FontFile` can
   never merge with a TrueType `/FontFile2` on a byte collision. Solves Mode A.
   Optionally (`embed_standard_14: false`) drops embedded programs for simple
   fonts named exactly a standard-14, keeping widths/encoding.

2. **`merge`** — `dedupe` + a lossless structural recompaction via `qpdf`
   (`--object-streams=generate --recompress-flate`), verified.

3. **`deep`** — additionally tries the most aggressive optimizer present
   (Ghostscript → mutool → qpdf), which can fuse divergent subsets (Mode B),
   behind the same gate.

### The verification gate

Every external candidate is accepted only if `_Fingerprint.preserves()`
holds — page count equal; named destinations, GoTo links, and outline-top
count not decreased; page labels retained — **and** the file is smaller.
Otherwise the candidate is discarded and the safe file kept. This is what
makes `deep` safe to offer: it tries Ghostscript, the gate catches the
destroyed dests/links, and it falls back to lossless `qpdf`. Verified by
`tests/integration/test_end_to_end.py::test_deep_rejects_ghostscript_when_it_breaks_links`
and the structure-breaking-tool unit test.

External tools are optional; absent them, `merge`/`deep` degrade cleanly to
built-in `dedupe`.

## Deliberately deferred: single-WeasyPrint-render (the Mode-B fix at source)

The *cleanest* fix for Mode B is not post-hoc font surgery — it is to stop
fragmenting in the first place: render all WeasyPrint-backed sections in **one
WeasyPrint document**, then slice the pages back into sections. WeasyPrint
then subsets each family exactly once, for free, with no font-program
rewriting.

This is **not implemented**, on purpose. It is a substantial rewrite of the
pipeline that cuts against two load-bearing invariants:

- **Per-section content-addressed caching** (`cache.py`) — a single combined
  render is one cache unit, so editing one markdown file would rebuild every
  section.
- **The two-pass deferred ToC** (`pipeline_impl.py`) — the main ToC and
  `subtoc` headers are rendered *after* layout is known; folding them into one
  up-front render is incompatible with the reserve-then-render approach.

Given the regression risk to working ToC/links/caching, and that `merge`
already captures the lossless win, this is left as a separate, explicitly
opt-in effort rather than bundled in. Hand-rolled subset merging via fontTools
(union-glyph re-subset + content-stream operand remapping) was also considered
and rejected for the same reason: too large and too fragile to ship without
extensive real-world testing.
