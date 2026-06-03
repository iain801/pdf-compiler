"""Image downsampling: cap embedded raster resolution to a PPI ceiling.

Sections embed images at whatever resolution they were handed — a phone photo
in a gallery or a 600-dpi scan inside an embedded PDF can carry many times the
pixels the page actually shows. This pass measures each image's *effective*
resolution at its largest placement and resamples anything above the ceiling.

The hard part is the measurement: an image XObject's pixel dimensions
(``/Width`` × ``/Height``) say nothing about how big it renders. That comes
from the current transformation matrix in effect when the image is painted
(``... cm /Im Do``). So :func:`_scan_placements` walks every page content
stream — and recurses into form XObjects, composing their ``/Matrix`` — to
recover the on-page size of every ``Do``. The most demanding placement (the
*largest* physical size, i.e. the lowest pixels-per-inch) sets the target: we
resample so that placement lands at ``max_ppi``; any smaller placement of the
same image then sits comfortably above the ceiling, which is fine.

The pass is lossy but conservative. It runs in memory on the assembled PDF,
only when ``ImagePolicy.max_ppi`` is set, never upscales, and keeps a
re-encoded image only when it is genuinely smaller than the original.
"""

from __future__ import annotations

import io
import math
import zlib
from dataclasses import dataclass

import pikepdf
from pikepdf import Name
from PIL import Image

from pdf_compiler.spec import ImagePolicy

# Row-vector affine identity; matrices are 6-tuples (a, b, c, d, e, f).
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
# Bound recursion into nested form XObjects (also cycle-guarded per chain).
_MAX_FORM_DEPTH = 12


@dataclass
class ImageStats:
    """What the image-downsampling pass did, for reporting to the user."""

    enabled: bool = False
    examined: int = 0
    downsampled: int = 0
    bytes_before: int = 0
    bytes_after: int = 0

    def summary(self) -> str | None:
        """One-line human summary, or None when there is nothing to report."""
        if not self.enabled or not self.examined:
            return None
        if not self.downsampled:
            return f"images: {self.examined} examined, none over ceiling"
        saved = max(0, self.bytes_before - self.bytes_after)
        return f"images: downsampled {self.downsampled}/{self.examined} (-{_kb(saved)})"


def _kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def downsample_images(pdf: pikepdf.Pdf, policy: ImagePolicy) -> ImageStats:
    """Resample over-resolution images in ``pdf`` in place. Lossy; opt-in.

    No-op (and reports ``enabled=False``) unless ``policy.max_ppi`` is set.
    """
    stats = ImageStats(enabled=policy.max_ppi is not None)
    if policy.max_ppi is None:
        return stats

    ceiling = float(policy.max_ppi)
    threshold = ceiling * policy.tolerance
    placements = _scan_placements(pdf)

    for img in _iter_image_xobjects(pdf):
        placed = placements.get(img.objgen)
        if placed is None:
            continue  # never actually painted (e.g. an unused / mask-only image)
        w_pt, h_pt = placed
        if w_pt <= 0 or h_pt <= 0:
            continue
        width = int(img.Width)
        height = int(img.Height)
        ppi = max(width * 72.0 / w_pt, height * 72.0 / h_pt)
        stats.examined += 1
        if ppi <= threshold:
            continue
        # Uniform scale so the most-demanding axis lands exactly at the ceiling
        # (preserves the image's own pixel aspect ratio).
        scale = ceiling / ppi
        new_w = max(1, round(width * scale))
        new_h = max(1, round(height * scale))
        sizes = _rewrite_image(img, new_w, new_h, policy)
        if sizes is not None:
            stats.downsampled += 1
            stats.bytes_before += sizes[0]
            stats.bytes_after += sizes[1]
    return stats


# -- placement measurement (content-stream walk) --------------------------- #


def _compose(m: tuple, n: tuple) -> tuple:
    """Return the matrix for "apply ``m`` then ``n``" (``m · n``, row-vector).

    This matches PDF's ``cm`` semantics: ``cm M`` prepends ``M`` to the CTM, so
    the new CTM is ``M`` composed with the old one.
    """
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _page_resources(page: pikepdf.Page):
    """Resolve a page's ``/Resources``, honouring page-tree inheritance.

    ``/Resources`` is an inheritable attribute: a page may omit its own and
    inherit one from an ancestor ``/Pages`` node (common in scanner output and
    other embedded PDFs). ``page.get('/Resources')`` only sees the page's own
    dict, so we walk up ``/Parent`` when it's absent — otherwise images on such
    pages are never measured and silently escape the ceiling.
    """
    node = page.obj
    seen: set[tuple[int, int]] = set()
    while node is not None and node.objgen not in seen:
        seen.add(node.objgen)
        res = node.get("/Resources")
        if res is not None:
            return res
        node = node.get("/Parent")
    return None


def _scan_placements(pdf: pikepdf.Pdf) -> dict[tuple[int, int], tuple[float, float]]:
    """Map each image XObject's objgen to its largest on-page size in points."""
    placements: dict[tuple[int, int], tuple[float, float]] = {}
    for page in pdf.pages:
        try:
            instrs = pikepdf.parse_content_stream(page)
        except (pikepdf.PdfError, ValueError):
            continue
        _walk(instrs, _page_resources(page), _IDENTITY, placements, 0, frozenset())
    return placements


def _walk(
    instrs,
    resources,
    ctm: tuple,
    placements: dict[tuple[int, int], tuple[float, float]],
    depth: int,
    seen_forms: frozenset,
) -> None:
    xobjects = resources.get("/XObject") if resources is not None else None
    stack: list[tuple] = []
    cur = ctm
    for instr in instrs:
        op = str(instr.operator)
        if op == "q":
            stack.append(cur)
        elif op == "Q":
            cur = stack.pop() if stack else cur
        elif op == "cm" and len(instr.operands) == 6:
            try:
                cur = _compose(tuple(float(x) for x in instr.operands), cur)
            except (TypeError, ValueError):
                continue
        elif op == "Do" and xobjects is not None and instr.operands:
            xo = xobjects.get(str(instr.operands[0]))
            if not isinstance(xo, pikepdf.Stream):
                continue
            sub = xo.get("/Subtype")
            if sub == Name.Image:
                _record(xo, cur, placements)
            elif sub == Name.Form and depth < _MAX_FORM_DEPTH and xo.objgen not in seen_forms:
                _walk_form(xo, cur, placements, depth, seen_forms)


def _walk_form(
    form: pikepdf.Stream,
    ctm: tuple,
    placements: dict[tuple[int, int], tuple[float, float]],
    depth: int,
    seen_forms: frozenset,
) -> None:
    matrix = _IDENTITY
    fm = form.get("/Matrix")
    if fm is not None and len(fm) == 6:
        try:
            matrix = tuple(float(x) for x in fm)
        except (TypeError, ValueError):
            matrix = _IDENTITY
    try:
        instrs = pikepdf.parse_content_stream(form)
    except (pikepdf.PdfError, ValueError):
        return
    _walk(
        instrs,
        form.get("/Resources"),
        _compose(matrix, ctm),
        placements,
        depth + 1,
        seen_forms | {form.objgen},
    )


def _record(
    xo: pikepdf.Stream,
    ctm: tuple,
    placements: dict[tuple[int, int], tuple[float, float]],
) -> None:
    # The image's unit square maps to device space through the CTM; the painted
    # width is the length of the transformed x-axis vector, height the y-axis.
    w_pt = math.hypot(ctm[0], ctm[1])
    h_pt = math.hypot(ctm[2], ctm[3])
    prev = placements.get(xo.objgen)
    if prev is None:
        placements[xo.objgen] = (w_pt, h_pt)
    else:
        # Keep the largest physical size per axis (the lowest-ppi demand).
        placements[xo.objgen] = (max(prev[0], w_pt), max(prev[1], h_pt))


# -- image rewriting -------------------------------------------------------- #


def _iter_image_xobjects(pdf: pikepdf.Pdf):
    """Yield each unique drawable image XObject (skipping stencil masks)."""
    seen: set[tuple[int, int]] = set()
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Stream):
            continue
        try:
            if obj.get("/Subtype") != Name.Image or obj.get("/ImageMask"):
                continue
        except (TypeError, AttributeError):
            continue
        if "/Width" not in obj or "/Height" not in obj:
            continue
        if obj.objgen in seen:
            continue
        seen.add(obj.objgen)
        yield obj


def _rewrite_image(
    img: pikepdf.Stream,
    new_w: int,
    new_h: int,
    policy: ImagePolicy,
) -> tuple[int, int] | None:
    """Resample ``img`` to ``new_w`` × ``new_h`` in place, re-encoding it.

    Returns ``(bytes_before, bytes_after)`` of the stored stream on success, or
    ``None`` if the image could not be decoded, would be upscaled, or did not
    actually get smaller (in which case it is left untouched). An optimization
    pass must never abort the build, so decode failures are swallowed.
    """
    try:
        pil = pikepdf.PdfImage(img).as_pil_image()
    except Exception:  # noqa: BLE001 - any unsupported colorspace/codec → skip
        return None
    if new_w >= pil.width or new_h >= pil.height:
        return None  # measured smaller than stored: never upscale

    before = len(img.read_raw_bytes())
    resized = pil.resize((new_w, new_h), Image.LANCZOS)
    # JPEG is only safe when no mask depends on exact sample values. A separate
    # /SMask (soft alpha) is fine — it's downsampled independently below.
    allow_lossy = "/Mask" not in img
    encoded = _encode(resized, policy, allow_lossy=allow_lossy)
    if encoded is None:
        return None
    data, filt, colorspace, bpc = encoded
    if len(data) >= before:
        return None  # no win — keep the original bytes untouched

    img.write(data, filter=filt)
    img.Width = new_w
    img.Height = new_h
    img.ColorSpace = colorspace
    img.BitsPerComponent = bpc
    for key in ("/DecodeParms", "/Decode", "/Interpolate"):
        if key in img:
            del img[key]
    after = len(data)  # == the raw stored bytes we just wrote; no need to re-read

    smask = img.get("/SMask")
    if isinstance(smask, pikepdf.Stream):
        _rewrite_mask(smask, new_w, new_h)
    return before, after


def _rewrite_mask(mask: pikepdf.Stream, new_w: int, new_h: int) -> None:
    """Downsample a soft-mask image to match its base, always lossless.

    A soft mask is a grayscale alpha plane scaled to the base image's area, so
    matching its pixel grid to the new base keeps the alpha aligned. Kept
    lossless (Flate) — JPEG artifacts on an alpha channel show as halos.
    """
    try:
        pil = pikepdf.PdfImage(mask).as_pil_image()
    except Exception:  # noqa: BLE001 - unreadable mask → leave it as-is
        return
    if new_w >= pil.width and new_h >= pil.height:
        return
    gray = pil.resize((new_w, new_h), Image.LANCZOS).convert("L")
    mask.write(zlib.compress(gray.tobytes()), filter=Name.FlateDecode)
    mask.Width = new_w
    mask.Height = new_h
    mask.ColorSpace = Name.DeviceGray
    mask.BitsPerComponent = 8
    for key in ("/DecodeParms", "/Decode"):
        if key in mask:
            del mask[key]


def _encode(
    pil: Image.Image,
    policy: ImagePolicy,
    *,
    allow_lossy: bool,
) -> tuple[bytes, pikepdf.Name, pikepdf.Name, int] | None:
    """Encode ``pil`` to ``(data, filter, colorspace, bits)`` per the policy.

    ``auto``/``jpeg`` take the DCTDecode path for opaque RGB / grayscale; every
    other mode (and ``flate``) falls back to lossless Flate. Returns ``None``
    only if the image cannot be expressed in a Device colorspace.
    """
    mode = pil.mode
    # Normalize odd modes into the four we can store as Device colorspaces.
    if mode in ("P", "PA", "RGBA"):
        pil = pil.convert("RGB")
        mode = "RGB"
    elif mode in ("1", "L", "LA", "I", "I;16", "F"):
        pil = pil.convert("L")
        mode = "L"
    elif mode not in ("RGB", "CMYK"):
        pil = pil.convert("RGB")
        mode = "RGB"

    want_jpeg = policy.compression in ("auto", "jpeg") and allow_lossy and mode in ("RGB", "L")
    if want_jpeg:
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=policy.jpeg_quality, optimize=True)
        colorspace = Name.DeviceRGB if mode == "RGB" else Name.DeviceGray
        return buf.getvalue(), Name.DCTDecode, colorspace, 8

    colorspace = {"RGB": Name.DeviceRGB, "L": Name.DeviceGray, "CMYK": Name.DeviceCMYK}[mode]
    return zlib.compress(pil.tobytes()), Name.FlateDecode, colorspace, 8
