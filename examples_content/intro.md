# Introduction

This is a short demonstration document compiled by **pdf-compiler**.

## What this shows

The compiler stitches together:

- A title page
- A table of contents (clickable in the PDF)
- Markdown sections (this one) with auto-indexed headings
- A divider / header page
- A second markdown chapter
- An image gallery

## Why YAML

YAML keeps the build spec readable and lets you version it alongside the
content.

```yaml
sections:
  - type: title
    title: "Annual Report"
```

## A nested heading

This nested heading appears as a sub-entry in the ToC.
