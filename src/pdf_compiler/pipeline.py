"""Orchestration stub — full implementation lands in task #8."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CompileResult:
    output_path: Path
    page_count: int
    # Human-readable one-line summary of the font-reconciliation pass, if any.
    font_summary: str | None = None


def compile_spec(
    spec_path: Path,
    *,
    out_path: Path | None = None,
    jobs: int = 0,
    use_cache: bool = True,
    reconcile: str | None = None,
) -> CompileResult:
    from pdf_compiler.context import build_context
    from pdf_compiler.loader import load_spec
    from pdf_compiler.pipeline_impl import run_pipeline

    spec = load_spec(spec_path)
    ctx = build_context(spec_path, spec, jobs=jobs, use_cache=use_cache)
    output = out_path or (spec_path.parent / spec.output)
    result = run_pipeline(spec, ctx, output, reconcile=reconcile)
    summary = result.font_reconcile.summary() if result.font_reconcile else None
    return CompileResult(output_path=output, page_count=result.page_count, font_summary=summary)


def validate_spec(spec_path: Path) -> list[str]:
    from pdf_compiler.loader import SpecError, load_spec
    from pdf_compiler.validate import validate_inputs

    try:
        spec = load_spec(spec_path)
    except SpecError as e:
        return [str(e)]
    return validate_inputs(spec, spec_path.parent)


def watch_spec(spec_path: Path, *, out_path: Path | None = None) -> None:
    from pdf_compiler.watcher import run_watch

    run_watch(spec_path, out_path=out_path)
