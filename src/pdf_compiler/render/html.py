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

TEMPLATE_DIR = Path(__file__).parent / "templates"


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
    ctx = {**context, "base_css": _base_css()}
    return env.get_template(template).render(**ctx)


def render_to_pdf(template: str, context: dict, output: Path, *, base_url: Path) -> Path:
    from weasyprint import HTML  # lazy

    html = render_html(template, context)
    HTML(string=html, base_url=str(base_url)).write_pdf(target=str(output))
    return output
