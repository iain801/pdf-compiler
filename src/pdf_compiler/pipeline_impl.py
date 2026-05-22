"""Pipeline implementation: compile → reserve deferred → render deferred → assemble.

Kept separate from :mod:`pdf_compiler.pipeline` so the public API surface
(used by the CLI) stays tiny and unmistakable.

"Deferred" sections are those whose page content depends on the global
page layout: the main :class:`TocSection` and any :class:`HeaderSection`
with ``subtoc: true``. They share the same two-pass treatment — compile
everything else first, reserve N pages each, render against the known
offsets, replan once if any of them overflows.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pdf_compiler.assemble import assemble
from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.sections import impl_for
from pdf_compiler.sections._common import dest_prefix
from pdf_compiler.sections.base import CompiledSection, TocEntry
from pdf_compiler.sections.toc import (
    estimate_toc_pages,
    render_subtoc_header,
    render_toc,
    subtoc_header_compiled_section,
    toc_compiled_section,
)
from pdf_compiler.spec import HeaderSection, Spec, TocSection


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    """Per-section page offsets and reserved deferred sizes for one planning pass."""

    offsets: dict[int, int]      # section index -> first page (0-based global)
    deferred_pages: dict[int, int]  # deferred section index -> reserved page count
    total: int                   # total document page count under this plan


def run_pipeline(spec: Spec, ctx: BuildContext, output: Path) -> int:
    """Run the full pipeline and write the final PDF. Returns total pages."""
    work: list[tuple[int, object]] = []
    deferred_indices: list[int] = []
    for i, sec in enumerate(spec.sections):
        if _is_deferred(sec):
            deferred_indices.append(i)
        else:
            work.append((i, impl_for(sec, i, spec.defaults)))

    compiled_map = (
        _compile_parallel(work, ctx) if ctx.jobs > 1 and len(work) > 1
        else {idx: impl.compile(ctx) for idx, impl in work}
    )

    plan = _plan_layout(spec, compiled_map, deferred_indices)
    front_matter_pages = _front_matter_set(spec, plan, compiled_map)

    # First-pass deferred render. If any deferred section overflows its
    # reservation we widen the plan and re-render every deferred against
    # the corrected offsets.
    deferred_compiled: dict[int, CompiledSection] = {}
    overflowed = False
    for di in deferred_indices:
        pdf, actual_pages = _render_deferred(
            ctx, spec, plan, compiled_map, di, front_matter_pages,
            suffix=str(di),
        )
        if actual_pages > plan.deferred_pages[di]:
            plan.deferred_pages[di] = actual_pages
            overflowed = True
        deferred_compiled[di] = _wrap_deferred(spec.sections[di], pdf, actual_pages, di, ctx)

    if overflowed:
        plan = _replan(spec, compiled_map, plan.deferred_pages)
        front_matter_pages = _front_matter_set(spec, plan, compiled_map)
        for di in deferred_indices:
            pdf, actual_pages = _render_deferred(
                ctx, spec, plan, compiled_map, di, front_matter_pages,
                suffix=f"final-{di}",
            )
            deferred_compiled[di] = _wrap_deferred(spec.sections[di], pdf, actual_pages, di, ctx)

    final_sections = [
        deferred_compiled[i] if i in deferred_compiled else compiled_map[i]
        for i in range(len(spec.sections))
    ]
    return assemble(
        final_sections, output, _interpolate_metadata(spec.metadata, ctx.vars),
        page_numbering=spec.defaults.page_numbering,
        margin=spec.defaults.margin,
    ).page_count


def _interpolate_metadata(md, vars):
    return md.model_copy(update={
        "title": interpolate(md.title, vars),
        "author": interpolate(md.author, vars),
        "subject": interpolate(md.subject, vars),
        "keywords": tuple(interpolate(k, vars) for k in md.keywords),
    })


# -- deferred dispatch ----------------------------------------------------- #


def _is_deferred(sec) -> bool:
    return isinstance(sec, TocSection) or (
        isinstance(sec, HeaderSection) and sec.subtoc
    )


def _wrap_deferred(
    sec, pdf_path: Path, page_count: int, idx: int, ctx: BuildContext,
) -> CompiledSection:
    title = interpolate(sec.title, ctx.vars)
    if isinstance(sec, TocSection):
        return toc_compiled_section(pdf_path, page_count, sec, title=title)
    assert isinstance(sec, HeaderSection)
    return subtoc_header_compiled_section(
        pdf_path, page_count, sec, f"{dest_prefix(idx)}-header", title=title,
    )


def _render_deferred(
    ctx: BuildContext,
    spec: Spec,
    plan: LayoutPlan,
    compiled_map: dict[int, CompiledSection],
    idx: int,
    front_matter_pages: set[int],
    *,
    suffix: str,
) -> tuple[Path, int]:
    sec = spec.sections[idx]
    if isinstance(sec, TocSection):
        entries = _entries_in_scope(spec, plan, compiled_map, scope=range(len(spec.sections)))
        out = ctx.tmp_pdf(f"toc-{suffix}")
        n = render_toc(ctx, sec, entries, out_path=out, front_matter_pages=front_matter_pages)
        return out, n
    assert isinstance(sec, HeaderSection)
    scope = _subtoc_scope(spec, idx)
    entries = _entries_in_scope(spec, plan, compiled_map, scope=scope)
    out = ctx.tmp_pdf(f"header-{suffix}")
    n = render_subtoc_header(
        ctx, sec, entries,
        out_path=out, front_matter_pages=front_matter_pages,
        dest_name=f"{dest_prefix(idx)}-header",
    )
    return out, n


def _subtoc_scope(spec: Spec, header_idx: int) -> range:
    """Indices covered by a subtoc header: from this header to the next header."""
    end = len(spec.sections)
    for j in range(header_idx + 1, len(spec.sections)):
        if isinstance(spec.sections[j], HeaderSection):
            end = j
            break
    return range(header_idx + 1, end)


# -- planning -------------------------------------------------------------- #


def _plan_layout(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    deferred_indices: list[int],
) -> LayoutPlan:
    """Initial estimate: deferred-section sizes derived from entry counts."""
    deferred_pages: dict[int, int] = {}
    for di in deferred_indices:
        sec = spec.sections[di]
        if isinstance(sec, TocSection):
            n_entries = sum(
                sum(1 for e in cs.toc_entries if e.depth <= sec.depth)
                for cs in compiled_map.values()
            )
            deferred_pages[di] = estimate_toc_pages(n_entries)
        else:  # subtoc HeaderSection — one divider page plus the mini ToC
            assert isinstance(sec, HeaderSection)
            scope = _subtoc_scope(spec, di)
            n_entries = sum(
                sum(1 for e in compiled_map[i].toc_entries if e.depth <= sec.subtoc_depth)
                for i in scope if i in compiled_map
            )
            deferred_pages[di] = 1 + estimate_toc_pages(n_entries)
    return _replan(spec, compiled_map, deferred_pages)


def _replan(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    deferred_pages: dict[int, int],
) -> LayoutPlan:
    offsets: dict[int, int] = {}
    page = 0
    for i in range(len(spec.sections)):
        offsets[i] = page
        page += deferred_pages.get(i) or compiled_map[i].page_count
    return LayoutPlan(
        offsets=offsets, deferred_pages=dict(deferred_pages), total=page,
    )


def _entries_in_scope(
    spec: Spec,
    plan: LayoutPlan,
    compiled_map: dict[int, CompiledSection],
    *,
    scope,
) -> list[tuple[TocEntry, int]]:
    """Collect (entry, global_page) pairs from compiled sections in ``scope``."""
    out: list[tuple[TocEntry, int]] = []
    for i in scope:
        if i not in compiled_map:
            continue  # skip deferred sections — they don't contribute entries
        cs = compiled_map[i]
        offset = plan.offsets[i]
        for e in cs.toc_entries:
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
            n_pages = plan.deferred_pages.get(i) or compiled_map[i].page_count
            for p in range(offset, offset + n_pages):
                fm.add(p)
    return fm


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
