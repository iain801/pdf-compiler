"""Render HTML templates to PDF via Jinja2 + WeasyPrint.

This module is the *only* place WeasyPrint is invoked. Sections build a
Jinja2 context dict and call :func:`render_to_pdf`; we render the template,
hand the HTML to WeasyPrint, write a PDF to disk.

WeasyPrint is imported lazily because it pulls in cairo/pango at import time
and we want fast `--help` / `validate`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import jinja2

from pdf_compiler.util import css_font_family

TEMPLATE_DIR = Path(__file__).parent / "templates"


def root_vars(
    page_size: str,
    margin: str,
    *,
    font_family: str | None = None,
    font_size: str | None = None,
) -> str:
    """Build the inline ``:root`` declaration consumed by every template.

    Variables that aren't set are omitted so base.css's ``var(..., default)``
    fallback kicks in. Keeps the per-template Jinja noise to a single field.
    """
    parts = [f"--page-size: {page_size};", f"--margin: {margin};"]
    family = css_font_family(font_family)
    if family:
        parts.append(f"--body-font: {family};")
    if font_size:
        parts.append(f"--body-font-size: {font_size};")
    return ":root { " + " ".join(parts) + " }"


@lru_cache(maxsize=1)
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        undefined=jinja2.StrictUndefined,
    )


@lru_cache(maxsize=1)
def _base_css() -> str:
    return (TEMPLATE_DIR / "base.css").read_text(encoding="utf-8")


def render_html(template: str, context: dict) -> str:
    env = _env()
    style = root_vars(
        context.get("page_size", "letter"),
        context.get("margin", "0.75in"),
        font_family=context.get("font_family"),
        font_size=context.get("font_size"),
    )
    ctx = {**context, "base_css": _base_css(), "root_style": style}
    return env.get_template(template).render(**ctx)


def render_to_pdf(template: str, context: dict, output: Path, *, base_url: Path) -> Path:
    from weasyprint import HTML  # lazy

    html = render_html(template, context)
    HTML(string=html, base_url=str(base_url)).write_pdf(target=str(output))
    return output
