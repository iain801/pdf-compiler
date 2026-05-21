"""Pipeline implementation: compile → reserve ToC → render ToC → assemble.

Kept separate from :mod:`pdf_compiler.pipeline` so the public API surface
(used by the CLI) stays tiny and unmistakable.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pdf_compiler.assemble import assemble
from pdf_compiler.context import BuildContext
from pdf_compiler.sections import impl_for
from pdf_compiler.sections.base import CompiledSection, TocEntry
from pdf_compiler.sections.toc import (
    estimate_toc_pages,
    render_toc,
    toc_compiled_section,
)
from pdf_compiler.spec import Spec, TocSection


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    """Per-section page offsets and reserved ToC sizes for one planning pass."""

    offsets: dict[int, int]      # section index -> first page (0-based global)
    toc_pages: dict[int, int]    # toc-section index -> reserved page count
    total: int                   # total document page count under this plan


def run_pipeline(spec: Spec, ctx: BuildContext, output: Path) -> int:
    """Run the full pipeline and write the final PDF. Returns total pages."""
    work: list[tuple[int, object]] = []
    toc_indices: list[int] = []
    for i, sec in enumerate(spec.sections):
        if isinstance(sec, TocSection):
            toc_indices.append(i)
        else:
            work.append((i, impl_for(sec, i, spec.defaults)))

    compiled_map = (
        _compile_parallel(work, ctx) if ctx.jobs > 1 and len(work) > 1
        else {idx: impl.compile(ctx) for idx, impl in work}
    )

    plan = _plan_layout(spec, compiled_map, toc_indices)
    front_matter_pages = _front_matter_set(spec, plan, compiled_map)

    # First-pass ToC render. If any ToC overflows its reservation we widen
    # the plan and re-render every ToC against the corrected offsets.
    toc_compiled: dict[int, CompiledSection] = {}
    overflowed = False
    for toc_idx in toc_indices:
        toc_pdf, actual_pages = _render_one_toc(
            ctx, spec, plan, compiled_map, toc_idx, front_matter_pages,
            suffix=str(toc_idx),
        )
        if actual_pages > plan.toc_pages[toc_idx]:
            plan.toc_pages[toc_idx] = actual_pages
            overflowed = True
        toc_compiled[toc_idx] = toc_compiled_section(
            toc_pdf, actual_pages, spec.sections[toc_idx],
        )

    if overflowed:
        plan = _replan(spec, compiled_map, plan.toc_pages)
        front_matter_pages = _front_matter_set(spec, plan, compiled_map)
        for toc_idx in toc_indices:
            toc_pdf, actual_pages = _render_one_toc(
                ctx, spec, plan, compiled_map, toc_idx, front_matter_pages,
                suffix=f"final-{toc_idx}",
            )
            toc_compiled[toc_idx] = toc_compiled_section(
                toc_pdf, actual_pages, spec.sections[toc_idx],
            )

    final_sections = [
        toc_compiled[i] if i in toc_compiled else compiled_map[i]
        for i in range(len(spec.sections))
    ]
    return assemble(final_sections, output, spec.metadata).page_count


# -- planning -------------------------------------------------------------- #


def _plan_layout(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    toc_indices: list[int],
) -> LayoutPlan:
    """Initial estimate: ToC sizes derived from entry counts."""
    toc_pages: dict[int, int] = {}
    for toc_idx in toc_indices:
        toc_spec = spec.sections[toc_idx]
        n_entries = sum(
            sum(1 for e in cs.toc_entries if e.depth <= toc_spec.depth)
            for cs in compiled_map.values()
        )
        toc_pages[toc_idx] = estimate_toc_pages(n_entries)
    return _replan(spec, compiled_map, toc_pages)


def _replan(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    toc_pages: dict[int, int],
) -> LayoutPlan:
    offsets: dict[int, int] = {}
    page = 0
    for i in range(len(spec.sections)):
        offsets[i] = page
        page += toc_pages.get(i) or compiled_map[i].page_count
    return LayoutPlan(offsets=offsets, toc_pages=dict(toc_pages), total=page)


def _toc_entries_with_pages(
    spec: Spec,
    plan: LayoutPlan,
    compiled_map: dict[int, CompiledSection],
    toc_spec: TocSection,
) -> list[tuple[TocEntry, int]]:
    out: list[tuple[TocEntry, int]] = []
    for i, sec in enumerate(spec.sections):
        if isinstance(sec, TocSection):
            continue
        cs = compiled_map[i]
        offset = plan.offsets[i]
        for e in cs.toc_entries:
            if e.depth <= toc_spec.depth:
                out.append((e, offset + e.local_page))
    return out


def _front_matter_set(
    spec: Spec,
    plan: LayoutPlan,
    compiled_map: dict[int, CompiledSection],
) -> set[int]:
    fm: set[int] = set()
    for i, sec in enumerate(spec.sections):
        offset = plan.offsets[i]
        is_fm = getattr(sec, "front_matter", None)
        if is_fm is None and i in compiled_map:
            is_fm = compiled_map[i].front_matter
        if is_fm:
            n_pages = plan.toc_pages.get(i) or compiled_map[i].page_count
            for p in range(offset, offset + n_pages):
                fm.add(p)
    return fm


def _render_one_toc(
    ctx: BuildContext,
    spec: Spec,
    plan: LayoutPlan,
    compiled_map: dict[int, CompiledSection],
    toc_idx: int,
    front_matter_pages: set[int],
    *,
    suffix: str,
) -> tuple[Path, int]:
    toc_spec = spec.sections[toc_idx]
    entries = _toc_entries_with_pages(spec, plan, compiled_map, toc_spec)
    toc_pdf = ctx.tmp_pdf(f"toc-{suffix}")
    actual_pages = render_toc(
        ctx, toc_spec, entries,
        out_path=toc_pdf, front_matter_pages=front_matter_pages,
    )
    return toc_pdf, actual_pages


# -- parallel compilation -------------------------------------------------- #


def _compile_parallel(work: list, ctx: BuildContext) -> dict[int, CompiledSection]:
    """Compile sections in worker processes. WeasyPrint is not thread-safe."""
    results: dict[int, CompiledSection] = {}
    with ProcessPoolExecutor(max_workers=ctx.jobs) as pool:
        futures = {pool.submit(_compile_one, impl, ctx): idx for idx, impl in work}
        for fut, idx in futures.items():
            results[idx] = fut.result()
    return results


def _compile_one(impl, ctx: BuildContext) -> CompiledSection:
    return impl.compile(ctx)
