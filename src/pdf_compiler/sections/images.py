"""Image gallery section."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from pdf_compiler.cache import hash_section
from pdf_compiler.context import BuildContext
from pdf_compiler.interpolate import interpolate
from pdf_compiler.layout.pack import (
    autopack_layout,
    grid_layout,
    probe_image,
    variable_row_heights,
)
from pdf_compiler.lengths import page_size_pt, parse_length_pt
from pdf_compiler.render.html import render_to_pdf
from pdf_compiler.sections._common import SectionMeta, dest_prefix, page_count_of
from pdf_compiler.sections.base import CompiledSection, OutlineNode, TocEntry
from pdf_compiler.spec import ImagesSection

# Space reserved for a one- or two-line caption below/above each image.
_CAPTION_H_PT = 36.0
# Horizontal padding on each cell (left+right = 2× this).
_CELL_H_PAD_PT = 6.0


@dataclass(frozen=True, slots=True)
class ImagesImpl:
    spec: ImagesSection
    meta: SectionMeta

    def compile(self, ctx: BuildContext) -> CompiledSection:
        defaults = self.meta.defaults
        prefix = dest_prefix(self.meta)
        dest_name = f"{prefix}-images"

        raw_paths = [ctx.resolve(img.path) for img in self.spec.images]
        rotations = [img.rotate for img in self.spec.images]
        captions = [interpolate(img.caption, ctx.vars) for img in self.spec.images]
        title = interpolate(self.spec.title, ctx.vars)

        # Pre-process: apply EXIF transpose + user rotation, saving corrected
        # temp files only when a transformation is actually needed.
        prepared_paths = [
            _prepare_image(p, r, ctx.tmpdir) for p, r in zip(raw_paths, rotations, strict=True)
        ]

        # Use corrected dimensions for layout calculations.
        infos = [
            probe_image(p, c, rotate=r)
            for p, c, r in zip(raw_paths, captions, rotations, strict=True)
        ]

        optimize = self.spec.optimize_packing
        use_variable_heights = self.spec.variable_heights or optimize
        layout_infos = (
            sorted(infos, key=lambda img: img.aspect, reverse=True) if optimize else infos
        )

        if self.spec.layout == "grid":
            per_page = self.spec.per_page or 4
            pages_layout = grid_layout(layout_infos, per_page)
        else:
            pages_layout = autopack_layout(layout_infos)

        # Compute page geometry for explicit cell sizing.
        pw, ph = page_size_pt(defaults.page_size)
        margin_pt = parse_length_pt(defaults.margin)
        content_w_pt = pw - 2 * margin_pt
        content_h_pt = ph - 2 * margin_pt

        # Caption space: 0 for overlay (caption drawn on image) and none.
        captions_mode = self.spec.captions
        caption_h = _CAPTION_H_PT if captions_mode not in ("none", "overlay") else 0.0

        # Map each ImageInfo back to its prepared path URL.
        prepared_url = {
            id(info): prepared.as_uri()
            for info, prepared in zip(infos, prepared_paths, strict=True)
        }

        template_pages = []
        for pg in pages_layout:
            rows, cols = pg.rows, pg.cols

            if use_variable_heights:
                page_infos = [cell.image for cell in pg.cells]
                row_h_list = variable_row_heights(page_infos, cols, content_h_pt)
            else:
                row_h_list = [content_h_pt / rows] * rows

            cells_flat = [
                {
                    "path_url": prepared_url[id(cell.image)],
                    "caption": cell.image.caption,
                }
                for cell in pg.cells
            ]

            rows_data = []
            for r in range(rows):
                cell_h = row_h_list[r]
                img_h = max(cell_h - caption_h - 6.0, cell_h * 0.6)
                row = []
                for c in range(cols):
                    idx = r * cols + c
                    if idx < len(cells_flat):
                        row.append(
                            {
                                **cells_flat[idx],
                                "cell_h_pt": round(cell_h, 1),
                                "img_h_pt": round(img_h, 1),
                            }
                        )
                    else:
                        row.append(None)
                rows_data.append(row)

            template_pages.append(
                {
                    "rows_data": rows_data,
                    "rows": rows,
                    "cols": cols,
                    "caption_h_pt": round(_CAPTION_H_PT, 1),
                    # Uniform fallback for the non-optimize path (template can use either).
                    "cell_h_pt": round(content_h_pt / rows, 1),
                }
            )

        key = hash_section(
            self.spec.model_dump(mode="json"),
            defaults_dump=defaults.model_dump(mode="json"),
            input_files=tuple(raw_paths),
            extra=f"images:{prefix}:{ctx.vars_hash}".encode(),
        )
        cached = ctx.cache.get(key)
        out = cached if cached is not None else ctx.tmp_pdf("images")
        if cached is None:
            render_to_pdf(
                "gallery.html",
                {
                    "title": title,
                    "dest_name": dest_name,
                    "pages": template_pages,
                    "captions": captions_mode,
                    "gallery_css": "",
                    "page_size": defaults.page_size,
                    "margin": defaults.margin,
                    "content_h_pt": round(content_h_pt, 1),
                    "content_w_pt": round(content_w_pt, 1),
                },
                out,
                base_url=ctx.project_root,
            )
            out = ctx.cache.put(key, out)

        n = page_count_of(out)
        label = title or "Gallery"
        toc = (
            (TocEntry(depth=1, label=label, dest_name=dest_name, local_page=0),)
            if self.spec.in_toc
            else ()
        )
        outline = (
            (OutlineNode(title=label, dest_name=dest_name, local_page=0),)
            if self.spec.in_toc
            else ()
        )
        return CompiledSection(
            pdf_path=out,
            page_count=n,
            toc_entries=toc,
            outline=outline,
            destinations={dest_name: 0},
        )


def _prepare_image(path: Path, rotate: int, tmpdir: Path) -> Path:
    """Return path to an image with EXIF orientation corrected and user
    rotation applied.  Returns the original path unchanged when no
    transformation is needed so the cache stays efficient."""
    with Image.open(path) as im:
        corrected = ImageOps.exif_transpose(im)
        changed = corrected.size != im.size or corrected.mode != im.mode
        if rotate:
            # User rotation is clockwise degrees; PIL rotate() is CCW.
            corrected = corrected.rotate(-rotate, expand=True)
            changed = True
        if not changed:
            # Quick check: if transpose didn't change size/mode and no user
            # rotation, pixel data is also unchanged — skip the write.
            return path
        corrected = corrected.copy()

    ext = path.suffix.lower()
    fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
    out = tmpdir / f"{path.stem}-rot{rotate}{path.suffix}"
    save_kw = {"quality": 92, "optimize": True} if fmt == "JPEG" else {}
    corrected.save(out, format=fmt, **save_kw)
    return out
