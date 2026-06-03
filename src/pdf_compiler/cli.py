"""Typer-based CLI: compile, validate, watch, cache."""

from __future__ import annotations

import enum
import sys
import traceback
from pathlib import Path

import typer
from rich.console import Console

from pdf_compiler import __version__


class ReconcileChoice(enum.StrEnum):
    """CLI choices for ``--reconcile``; mirrors spec.ReconcileMode. Defining it
    as an Enum lets Typer validate the value and list the choices in --help,
    so a bad value yields a clean error instead of a deep pydantic traceback."""

    off = "off"
    dedupe = "dedupe"
    merge = "merge"
    deep = "deep"


app = typer.Typer(
    name="pdfc",
    help="Stitch large PDFs from a YAML spec.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
err = Console(stderr=True)
out = Console()


def _version_callback(value: bool) -> None:
    if value:
        out.print(f"pdfc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """pdfc — stitch PDFs from YAML."""


@app.command("compile")
def compile_cmd(
    spec: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_path: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Override the output path from the spec.",
    ),
    jobs: int = typer.Option(0, "--jobs", "-j", help="Parallel workers (0 = auto)."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the section cache."),
    reconcile: ReconcileChoice | None = typer.Option(
        None,
        "--reconcile",
        help="Font reconciliation: off | dedupe | merge | deep (overrides the spec).",
    ),
) -> None:
    """Compile a YAML spec into a single PDF."""
    from pdf_compiler.pipeline import compile_spec

    try:
        result = compile_spec(
            spec,
            out_path=out_path,
            jobs=jobs,
            use_cache=not no_cache,
            reconcile=reconcile.value if reconcile is not None else None,
        )
    except Exception as e:  # noqa: BLE001
        # CLI boundary: any unhandled error from the pipeline becomes a
        # friendly one-line error plus a dimmed traceback for debugging.
        msg = str(e) or type(e).__name__
        err.print(f"[red]error:[/red] {msg}")
        err.print()
        err.print("[dim]" + traceback.format_exc() + "[/dim]")
        raise typer.Exit(code=1) from e
    out.print(f"[green]wrote[/green] {result.output_path} ({result.page_count} pages)")
    if result.font_summary:
        out.print(f"[dim]{result.font_summary}[/dim]")


@app.command()
def validate(
    spec: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Validate a spec and all referenced inputs without producing a PDF."""
    from pdf_compiler.pipeline import validate_spec

    problems = validate_spec(spec)
    if problems:
        for p in problems:
            err.print(f"[red]✗[/red] {p}")
        raise typer.Exit(code=1)
    out.print("[green]✓[/green] spec is valid")


@app.command()
def watch(
    spec: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out_path: Path | None = typer.Option(None, "--out", "-o"),
) -> None:
    """Recompile on changes to the spec or any referenced file."""
    from pdf_compiler.pipeline import watch_spec

    watch_spec(spec, out_path=out_path)


cache_app = typer.Typer(help="Manage the section cache.")
app.add_typer(cache_app, name="cache")


@cache_app.command("clear")
def cache_clear() -> None:
    """Delete all cached compiled sections."""
    from pdf_compiler.cache import clear_cache, default_cache_dir

    n = clear_cache(default_cache_dir())
    out.print(f"[green]cleared[/green] {n} cache entries")


def main() -> None:  # pragma: no cover - thin wrapper
    sys.exit(app())
