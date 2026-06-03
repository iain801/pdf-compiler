from __future__ import annotations

import pikepdf
import pytest
from pikepdf import Name

from pdf_compiler import images as im
from pdf_compiler.images import ImageStats, _encode, _scan_placements, downsample_images
from pdf_compiler.spec import ImagePolicy


def _samples(w: int, h: int, ncomp: int) -> bytes:
    # Deterministic *high-entropy* content: the raw image barely compresses, so
    # a smaller re-encode is always a genuine size win (mirrors a real photo and
    # never trips the "no improvement → skip" guard the way flat data would).
    import hashlib

    n = w * h * ncomp
    out = bytearray()
    i = 0
    while len(out) < n:
        out += hashlib.blake2b(i.to_bytes(8, "little"), digest_size=64).digest()
        i += 1
    return bytes(out[:n])


def _add_image(
    pdf: pikepdf.Pdf,
    px: tuple[int, int],
    place_pt: tuple[float, float],
    *,
    mode: str = "RGB",
    with_smask: bool = False,
    mask_array: bool = False,
) -> pikepdf.Object:
    """Attach a raw (Flate) image of ``px`` pixels, drawn at ``place_pt`` points
    on a fresh page, and return the image XObject."""
    import zlib

    w, h = px
    ncomp = 3 if mode == "RGB" else 1
    raw = _samples(w, h, ncomp)
    xobj = pdf.make_stream(zlib.compress(raw))
    xobj.Type = Name.XObject
    xobj.Subtype = Name.Image
    xobj.Width = w
    xobj.Height = h
    xobj.ColorSpace = Name.DeviceRGB if mode == "RGB" else Name.DeviceGray
    xobj.BitsPerComponent = 8
    xobj.Filter = Name.FlateDecode
    if with_smask:
        sm = pdf.make_stream(zlib.compress(_samples(w, h, 1)))
        sm.Type = Name.XObject
        sm.Subtype = Name.Image
        sm.Width = w
        sm.Height = h
        sm.ColorSpace = Name.DeviceGray
        sm.BitsPerComponent = 8
        sm.Filter = Name.FlateDecode
        xobj.SMask = sm
    if mask_array:
        xobj.Mask = pikepdf.Array([0, 10])  # colour-key mask: needs exact samples
    pw, ph = place_pt
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobj))
    page.Contents = pdf.make_stream(f"q {pw} 0 0 {ph} 0 0 cm /Im0 Do Q".encode())
    return xobj


def _policy(**kw) -> ImagePolicy:
    return ImagePolicy(**kw)


# -- placement measurement ------------------------------------------------- #


def test_scan_placements_recovers_on_page_size():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (144.0, 96.0))
    placements = _scan_placements(pdf)
    w_pt, h_pt = placements[xobj.objgen]
    assert round(w_pt) == 144
    assert round(h_pt) == 96


def test_scan_placements_through_form_matrix():
    """An image painted inside a form XObject must be measured through the
    form's /Matrix, not just the page CTM."""
    import zlib

    pdf = pikepdf.Pdf.new()
    img = pdf.make_stream(zlib.compress(_samples(400, 400, 3)))
    img.Type = Name.XObject
    img.Subtype = Name.Image
    img.Width = 400
    img.Height = 400
    img.ColorSpace = Name.DeviceRGB
    img.BitsPerComponent = 8
    img.Filter = Name.FlateDecode
    # Form draws the unit image; its /Matrix scales by 2. The page draws the
    # form under a 36pt cm, so the image lands at 72pt on the page.
    form = pdf.make_stream(b"q 36 0 0 36 0 0 cm /Im0 Do Q")
    form.Type = Name.XObject
    form.Subtype = Name.Form
    form.BBox = pikepdf.Array([0, 0, 1, 1])
    form.Matrix = pikepdf.Array([2, 0, 0, 2, 0, 0])
    form.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=img))
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm0=form))
    page.Contents = pdf.make_stream(b"q 1 0 0 1 0 0 cm /Fm0 Do Q")

    placements = _scan_placements(pdf)
    w_pt, _ = placements[img.objgen]
    assert round(w_pt) == 72  # 36 (page cm) × 2 (form matrix)


def test_scan_placements_resolves_inherited_resources():
    """A page that inherits /Resources from an ancestor /Pages node (no
    /Resources of its own) must still have its images measured — otherwise
    they silently escape the ceiling."""
    import zlib

    pdf = pikepdf.Pdf.new()
    img = pdf.make_stream(zlib.compress(_samples(400, 400, 3)))
    img.Type = Name.XObject
    img.Subtype = Name.Image
    img.Width = 400
    img.Height = 400
    img.ColorSpace = Name.DeviceRGB
    img.BitsPerComponent = 8
    img.Filter = Name.FlateDecode
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Contents = pdf.make_stream(b"q 72 0 0 72 0 0 cm /Im0 Do Q")
    # Strip the page's own /Resources and place it on the page-tree root.
    if "/Resources" in page.obj:
        del page.obj.Resources
    pdf.Root.Pages.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=img))

    placements = _scan_placements(pdf)
    assert img.objgen in placements
    assert round(placements[img.objgen][0]) == 72


def test_scan_placements_keeps_largest_of_multiple():
    """When an image is drawn more than once, the largest physical placement
    (lowest required ppi) wins, so we never under-resolve it."""
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    # Draw the same image a second time, larger, on a new page.
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobj))
    page.Contents = pdf.make_stream(b"q 144 0 0 144 0 0 cm /Im0 Do Q")

    placements = _scan_placements(pdf)
    w_pt, h_pt = placements[xobj.objgen]
    assert round(w_pt) == 144
    assert round(h_pt) == 144


# -- downsampling ---------------------------------------------------------- #


def test_downsample_shrinks_oversized_image():
    pdf = pikepdf.Pdf.new()
    # 400px drawn at 72pt → 400 ppi. Ceiling 100 → target 100px.
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    before = len(xobj.read_raw_bytes())

    stats = downsample_images(pdf, _policy(max_ppi=100))

    assert stats.enabled and stats.examined == 1 and stats.downsampled == 1
    assert int(xobj.Width) == 100 and int(xobj.Height) == 100
    assert len(xobj.read_raw_bytes()) < before
    assert stats.bytes_after < stats.bytes_before


def test_downsample_target_uses_largest_placement():
    """With the image drawn at 72pt and 144pt, downsampling targets the 144pt
    placement: 400px → 200px (ceiling 100), not 100px."""
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobj))
    page.Contents = pdf.make_stream(b"q 144 0 0 144 0 0 cm /Im0 Do Q")

    downsample_images(pdf, _policy(max_ppi=100))
    assert int(xobj.Width) == 200


def test_under_ceiling_not_touched():
    pdf = pikepdf.Pdf.new()
    # 400px drawn at 300pt → 96 ppi, under a 150 ceiling.
    xobj = _add_image(pdf, (400, 400), (300.0, 300.0))
    stats = downsample_images(pdf, _policy(max_ppi=150))
    assert stats.examined == 1 and stats.downsampled == 0
    assert int(xobj.Width) == 400


def test_tolerance_band_skips_marginal_overshoot():
    pdf = pikepdf.Pdf.new()
    # 400px at ~180pt → 160 ppi. Ceiling 150, tolerance 1.1 → threshold 165.
    xobj = _add_image(pdf, (400, 400), (180.0, 180.0))
    stats = downsample_images(pdf, _policy(max_ppi=150, tolerance=1.1))
    assert stats.examined == 1 and stats.downsampled == 0
    assert int(xobj.Width) == 400


def test_off_when_max_ppi_unset():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    stats = downsample_images(pdf, _policy())
    assert not stats.enabled and stats.examined == 0 and stats.downsampled == 0
    assert int(xobj.Width) == 400


def test_image_mask_is_ignored():
    """Stencil (/ImageMask) images are 1-bit shape masks, not photos; skip."""
    import zlib

    pdf = pikepdf.Pdf.new()
    xobj = pdf.make_stream(zlib.compress(bytes(400 * 50)))
    xobj.Type = Name.XObject
    xobj.Subtype = Name.Image
    xobj.Width = 400
    xobj.Height = 400
    xobj.ImageMask = True
    xobj.BitsPerComponent = 1
    xobj.Filter = Name.FlateDecode
    page = pdf.add_blank_page(page_size=(612, 792))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobj))
    page.Contents = pdf.make_stream(b"q 72 0 0 72 0 0 cm /Im0 Do Q")

    stats = downsample_images(pdf, _policy(max_ppi=100))
    assert stats.examined == 0


def test_smask_downsampled_to_match_base():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0), with_smask=True)
    downsample_images(pdf, _policy(max_ppi=100))
    assert int(xobj.Width) == 100
    assert int(xobj.SMask.Width) == 100 and int(xobj.SMask.Height) == 100


# -- encoding choices ------------------------------------------------------ #


def test_auto_uses_jpeg_for_opaque_rgb():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    downsample_images(pdf, _policy(max_ppi=100, compression="auto"))
    assert xobj.Filter == Name.DCTDecode


def test_flate_forces_lossless():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    downsample_images(pdf, _policy(max_ppi=100, compression="flate"))
    assert xobj.Filter == Name.FlateDecode


def test_masked_image_stays_lossless_under_auto():
    """A colour-key /Mask depends on exact sample values; JPEG would corrupt
    it, so even 'auto' must keep such an image lossless."""
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0), mask_array=True)
    stats = downsample_images(pdf, _policy(max_ppi=100, compression="auto"))
    # The high-entropy image always shrinks, so it is resampled; with a
    # colour-key /Mask present, 'auto' must still pick the lossless path.
    assert stats.downsampled == 1
    assert int(xobj.Width) == 100
    assert xobj.Filter == Name.FlateDecode


def test_encode_grayscale_jpeg_is_devicegray():
    from PIL import Image

    data, filt, cs, bpc = _encode(
        Image.new("L", (32, 32)), _policy(max_ppi=100, compression="jpeg"), allow_lossy=True
    )
    assert filt == Name.DCTDecode and cs == Name.DeviceGray and bpc == 8 and data


# -- guards ---------------------------------------------------------------- #


def test_rewrite_never_upscales():
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (100, 100), (72.0, 72.0))
    # Asking for larger-than-stored dimensions must be refused.
    assert im._rewrite_image(xobj, 999, 999, _policy(max_ppi=100)) is None
    assert int(xobj.Width) == 100


def test_no_size_win_leaves_image_untouched(monkeypatch):
    pdf = pikepdf.Pdf.new()
    xobj = _add_image(pdf, (400, 400), (72.0, 72.0))
    before = xobj.read_raw_bytes()
    # Force the encoder to "succeed" but produce a larger stream.
    monkeypatch.setattr(
        im, "_encode", lambda *a, **k: (b"x" * 10_000_000, Name.FlateDecode, Name.DeviceRGB, 8)
    )
    stats = downsample_images(pdf, _policy(max_ppi=100))
    assert stats.downsampled == 0
    assert xobj.read_raw_bytes() == before
    assert int(xobj.Width) == 400


# -- reporting ------------------------------------------------------------- #


def test_summary_strings():
    assert ImageStats(enabled=False).summary() is None
    assert ImageStats(enabled=True, examined=0).summary() is None
    assert "none over ceiling" in ImageStats(enabled=True, examined=3).summary()
    s = ImageStats(
        enabled=True, examined=4, downsampled=2, bytes_before=200_000, bytes_after=50_000
    ).summary()
    assert "downsampled 2/4" in s and "KB" in s


@pytest.mark.parametrize("bad", [0, 5, 17])
def test_policy_rejects_tiny_ceiling(bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ImagePolicy(max_ppi=bad)
