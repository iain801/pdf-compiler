"""Pipeline implementation: compile → reserve ToC → render ToC → assemble.

Kept separate from :mod:`pdf_compiler.pipeline` so the public API surface
(used by the CLI) stays tiny and unmistakable.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterable

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


def run_pipeline(spec: Spec, ctx: BuildContext, output: Path) -> int:
    """Run the full pipeline and write the final PDF. Returns total pages."""

    # Step 1: compile every non-ToC section. Parallel if jobs > 1.
    work: list[tuple[int, object]] = []
    toc_indices: list[int] = []
    for i, sec in enumerate(spec.sections):
        if isinstance(sec, TocSection):
            toc_indices.append(i)
        else:
            work.append((i, impl_for(sec, i, spec.defaults)))

    compiled_map: dict[int, CompiledSection] = {}
    if ctx.jobs > 1 and len(work) > 1:
        compiled_map = _compile_parallel(work, ctx)
    else:
        for idx, impl in work:
            compiled_map[idx] = impl.compile(ctx)

    # Step 2: figure out where each section sits, including ToCs that haven't
    # been rendered yet. ToC page counts are estimated from how many entries
    # they'll contain.
    plan = _plan_layout(spec, compiled_map, toc_indices)

    # Step 3: render each ToC section now that page numbers are known.
    front_matter_pages = _front_matter_set(spec, plan, compiled_map)
    toc_compiled: dict[int, CompiledSection] = {}
    needs_redo = False
    for toc_idx in toc_indices:
        toc_spec = spec.sections[toc_idx]
        entries_with_pages = _toc_entries_with_pages(spec, plan, compiled_map, toc_spec)
        toc_pdf = ctx.tmp_pdf(f"toc-{toc_idx}")
        actual_pages = render_toc(
            ctx, toc_spec, entries_with_pages,
            out_path=toc_pdf, section_index=toc_idx,
            front_matter_pages=front_matter_pages,
        )
        reserved = plan["toc_pages"][toc_idx]
        if actual_pages > reserved:
            # We under-estimated. Update plan with the real count and re-render
            # once so destinations resolve to correct pages.
            plan["toc_pages"][toc_idx] = actual_pages
            plan = _replan(spec, compiled_map, toc_indices, plan["toc_pages"])
            front_matter_pages = _front_matter_set(spec, plan, compiled_map)
            needs_redo = True
        toc_compiled[toc_idx] = toc_compiled_section(toc_pdf, actual_pages, toc_spec)

    if needs_redo:
        # Render any earlier ToCs again with the corrected plan.
        for toc_idx in toc_indices:
            toc_spec = spec.sections[toc_idx]
            entries_with_pages = _toc_entries_with_pages(spec, plan, compiled_map, toc_spec)
            toc_pdf = ctx.tmp_pdf(f"toc-final-{toc_idx}")
            actual_pages = render_toc(
                ctx, toc_spec, entries_with_pages,
                out_path=toc_pdf, section_index=toc_idx,
                front_matter_pages=front_matter_pages,
            )
            toc_compiled[toc_idx] = toc_compiled_section(toc_pdf, actual_pages, toc_spec)

    # Step 4: assemble in spec order.
    final_sections: list[CompiledSection] = []
    for i in range(len(spec.sections)):
        if i in toc_compiled:
            final_sections.append(toc_compiled[i])
        else:
            final_sections.append(compiled_map[i])
    result = assemble(final_sections, output, spec.metadata)
    return result.page_count


# -- planning -------------------------------------------------------------- #


def _plan_layout(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    toc_indices: list[int],
) -> dict:
    """Estimate per-section page offsets including reserved ToC pages."""
    # First pass: estimate ToC sizes from how many entries each will hold.
    toc_pages: dict[int, int] = {}
    for toc_idx in toc_indices:
        toc_spec = spec.sections[toc_idx]
        n_entries = sum(
            sum(1 for e in cs.toc_entries if e.depth <= toc_spec.depth)
            for cs in compiled_map.values()
        )
        toc_pages[toc_idx] = estimate_toc_pages(n_entries)
    return _replan(spec, compiled_map, toc_indices, toc_pages)


def _replan(
    spec: Spec,
    compiled_map: dict[int, CompiledSection],
    toc_indices: list[int],
    toc_pages: dict[int, int],
) -> dict:
    offsets: dict[int, int] = {}
    page = 0
    for i, sec in enumerate(spec.sections):
        offsets[i] = page
        if i in toc_pages:
            page += toc_pages[i]
        else:
            page += compiled_map[i].page_count
    return {"offsets": offsets, "toc_pages": dict(toc_pages), "total": page}


def _toc_entries_with_pages(
    spec: Spec,
    plan: dict,
    compiled_map: dict[int, CompiledSection],
    toc_spec: TocSection,
) -> list[tuple[TocEntry, int]]:
    out: list[tuple[TocEntry, int]] = []
    for i, sec in enumerate(spec.sections):
        if isinstance(sec, TocSection):
            continue
        cs = compiled_map[i]
        offset = plan["offsets"][i]
        for e in cs.toc_entries:
            if e.depth <= toc_spec.depth:
                out.append((e, offset + e.local_page))
    return out


def _front_matter_set(
    spec: Spec,
    plan: dict,
    compiled_map: dict[int, CompiledSection],
) -> set[int]:
    """Return the set of 0-based global page indices in front matter."""
    fm: set[int] = set()
    for i, sec in enumerate(spec.sections):
        offset = plan["offsets"][i]
        is_fm = getattr(sec, "front_matter", None)
        if is_fm is None and i in compiled_map:
            is_fm = compiled_map[i].front_matter
        if is_fm:
            n_pages = plan["toc_pages"].get(i) or compiled_map[i].page_count
            for p in range(offset, offset + n_pages):
                fm.add(p)
    return fm


# -- parallel compilation -------------------------------------------------- #


def _compile_parallel(work: list, ctx: BuildContext) -> dict[int, CompiledSection]:
    """Compile sections in worker processes. Each worker gets a fresh import."""
    # WeasyPrint is not thread-safe; we use processes. Each worker re-imports
    # everything, but that overhead is small relative to a render.
    results: dict[int, CompiledSection] = {}
    with ProcessPoolExecutor(max_workers=ctx.jobs) as pool:
        futures = {pool.submit(_compile_one, idx, impl, ctx): idx for idx, impl in work}
        for fut in futures:
            idx = futures[fut]
            results[idx] = fut.result()
    return results


def _compile_one(idx: int, impl, ctx: BuildContext) -> CompiledSection:
    return impl.compile(ctx)
