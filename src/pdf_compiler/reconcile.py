"""Font reconciliation: shrink the assembled PDF by coalescing duplicate
embedded fonts without ever breaking its navigation structure.

Three tiers, escalating in power and (for the external ones) risk:

* ``dedupe`` — built-in, lossless, zero-dependency. Coalesces byte-identical
  embedded font-program streams (``/FontFile{,2,3}``) and the auxiliary
  streams hanging off font dicts (``/ToUnicode``, ``/CIDSet``) so identical
  data is stored once and referenced many times. Optionally drops embedded
  programs for standard-14 fonts. Operates in memory on the combined PDF.
* ``merge`` — ``dedupe`` plus a lossless structural recompaction by an
  external tool (``qpdf``), if one is available.
* ``deep`` — additionally tries the most aggressive optimizer present
  (Ghostscript), which can merge divergent subsets but is structurally
  destructive; it is only accepted if it survives the verification gate.

Every external pass runs behind :func:`_verify`: the candidate output must
preserve page count, named destinations, GoTo links, page labels, and the
outline, and must actually be smaller, or it is discarded and the safe file
is kept. This is what makes ``deep`` safe to offer at all — Ghostscript, for
example, silently flattens our ``/Names/Dests`` tree and every internal link,
and the gate catches exactly that.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from pdf_compiler.spec import FontPolicy

# Font-related stream slots we coalesce. Keyed by the dict key under which the
# stream hangs; the key is part of the dedup identity so a /FontFile (Type1)
# can never merge with a /FontFile2 (TrueType) even on a byte collision.
_FONT_STREAM_KEYS = ("/FontFile", "/FontFile2", "/FontFile3", "/CIDSet", "/ToUnicode")

# Metadata keys folded into the dedup hash alongside the decoded bytes, so two
# streams only merge when their length-segment markers and subtype agree too.
_STREAM_META_KEYS = ("/Subtype", "/Length1", "/Length2", "/Length3")

# The PDF standard-14 base font names (viewers guarantee a built-in for these).
_STANDARD_14 = frozenset(
    {
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Helvetica-BoldOblique",
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Times-BoldItalic",
        "Courier",
        "Courier-Bold",
        "Courier-Oblique",
        "Courier-BoldOblique",
        "Symbol",
        "ZapfDingbats",
    }
)


@dataclass
class ReconcileStats:
    """What a reconciliation pass accomplished, for reporting to the user."""

    mode: str = "off"
    merged_streams: int = 0
    bytes_freed: int = 0
    stripped_standard_14: int = 0
    external_tool: str | None = None
    external_applied: bool = False
    external_reason: str = ""
    size_before: int = 0
    size_after: int = 0

    def summary(self) -> str | None:
        """One-line human summary, or None when nothing happened."""
        parts: list[str] = []
        if self.merged_streams:
            parts.append(f"merged {self.merged_streams} duplicate font streams")
        if self.stripped_standard_14:
            parts.append(f"unembedded {self.stripped_standard_14} standard-14 fonts")
        if self.external_applied and self.external_tool:
            saved = max(0, self.size_before - self.size_after)
            parts.append(f"{self.external_tool} recompaction (-{_kb(saved)})")
        elif self.external_tool and self.external_reason:
            parts.append(f"{self.external_tool} skipped ({self.external_reason})")
        if not parts:
            return None
        return "fonts: " + "; ".join(parts)


def _kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


# -- Tier 1: in-memory, lossless ------------------------------------------- #


def reconcile_in_memory(pdf: pikepdf.Pdf, policy: FontPolicy) -> ReconcileStats:
    """Run the built-in (Tier 1) pass on ``pdf`` in place. Always lossless."""
    stats = ReconcileStats(mode=policy.reconcile)
    if policy.reconcile == "off":
        return stats
    merged, freed = _dedupe_font_streams(pdf)
    stats.merged_streams = merged
    stats.bytes_freed = freed
    if not policy.embed_standard_14:
        stats.stripped_standard_14 = _strip_standard_14(pdf)
    return stats


def _stream_identity(ref: pikepdf.Object, key: str, data: bytes) -> bytes:
    meta = [key]
    for mk in _STREAM_META_KEYS:
        v = ref.get(mk)
        meta.append(f"{mk}={v}" if v is not None else "")
    h = hashlib.blake2b(digest_size=16)
    h.update("\x00".join(meta).encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(data)
    return h.digest()


def _dedupe_font_streams(pdf: pikepdf.Pdf) -> tuple[int, int]:
    """Coalesce byte-identical font streams. Returns (merged_count, bytes_freed).

    For each duplicate we repoint the holder's reference at the first
    (canonical) copy; the now-orphaned stream is garbage-collected on save.

    Identity is the stream's *stored* (filter-encoded) bytes: equal stored
    bytes imply equal content, so we never inflate the program — important
    because this pass runs on every compile by default and most font streams
    are unique. ``bytes_freed`` therefore reflects the compressed bytes that
    actually leave the file, not the decoded size.
    """
    canonical: dict[bytes, pikepdf.Object] = {}
    merged = 0
    freed = 0
    for obj in list(pdf.objects):
        for key in _FONT_STREAM_KEYS:
            try:
                ref = obj.get(key)
            except (TypeError, AttributeError):
                continue  # not a dict-like object; .get returns None normally
            if ref is None or not isinstance(ref, pikepdf.Stream):
                continue
            try:
                data = ref.read_raw_bytes()
            except pikepdf.PdfError:
                continue
            ident = _stream_identity(ref, key, data)
            keeper = canonical.get(ident)
            if keeper is None:
                canonical[ident] = ref
            elif keeper.objgen != ref.objgen:
                obj[key] = keeper
                merged += 1
                freed += len(data)
    return merged, freed


def _base_name(font: pikepdf.Object) -> str | None:
    bf = font.get("/BaseFont")
    if bf is None:
        return None
    name = str(bf).lstrip("/")
    # Subset fonts are tagged "ABCDEF+RealName"; strip the 6-letter prefix.
    if len(name) > 7 and name[6] == "+" and name[:6].isupper() and name[:6].isalpha():
        name = name[7:]
    return name


def _strip_standard_14(pdf: pikepdf.Pdf) -> int:
    """Drop embedded programs for simple fonts named exactly a standard-14.

    Leaves widths/encoding intact so metrics are preserved; the viewer
    substitutes its built-in. Skips Type0 (CID) fonts entirely.
    """
    stripped = 0
    for obj in list(pdf.objects):
        try:
            if obj.get("/Type") != pikepdf.Name.Font:
                continue
            if obj.get("/Subtype") == pikepdf.Name("/Type0"):
                continue
        except (TypeError, AttributeError):
            continue
        if _base_name(obj) not in _STANDARD_14:
            continue
        desc = obj.get("/FontDescriptor")
        if desc is None:
            continue
        removed = False
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            if key in desc:
                del desc[key]
                removed = True
        if removed:
            stripped += 1
    return stripped


# -- External tiers: lossless (merge) / aggressive (deep), both gated ------ #


def _tool_path(name: str) -> str | None:
    return shutil.which("gs" if name == "ghostscript" else name)


def _candidate_tools(policy: FontPolicy) -> list[str]:
    """Ordered tool preferences for the active tier, filtered to what's installed."""
    if policy.external_tool == "none":
        return []
    if policy.external_tool != "auto":
        chosen = policy.external_tool
        return [chosen] if _tool_path(chosen) else []
    # auto: merge wants only lossless tools; deep may try the aggressive one.
    order = ["qpdf", "mutool"] if policy.reconcile == "merge" else ["ghostscript", "qpdf", "mutool"]
    return [t for t in order if _tool_path(t)]


def _command(tool: str, src: Path, dst: Path) -> list[str]:
    exe = _tool_path(tool) or tool
    if tool == "qpdf":
        return [
            exe,
            "--object-streams=generate",
            "--compress-streams=y",
            "--recompress-flate",
            str(src),
            str(dst),
        ]
    if tool == "mutool":
        return [exe, "clean", "-gggg", "-z", str(src), str(dst)]
    if tool == "ghostscript":
        return [
            exe,
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=pdfwrite",
            "-dPDFSETTINGS=/prepress",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            f"-sOutputFile={dst}",
            str(src),
        ]
    raise ValueError(f"unknown tool: {tool}")


@dataclass
class _Fingerprint:
    pages: int = 0
    dests: int = 0
    goto_links: int = 0
    page_labels: bool = False
    # Total outline nodes at every depth (not just the top level) so a tool
    # that flattens nested bookmarks is caught even if the top-level count
    # is unchanged.
    outline_items: int = 0

    def preserves(self, before: _Fingerprint) -> bool:
        """True if this (post-pass) fingerprint keeps everything ``before`` had."""
        return (
            self.pages == before.pages
            and self.dests >= before.dests
            and self.goto_links >= before.goto_links
            and (self.page_labels or not before.page_labels)
            and self.outline_items >= before.outline_items
        )


def _count_name_tree(node: pikepdf.Object | None) -> int:
    """Count entries in a PDF name tree, recursing through ``/Kids``.

    A name tree may be a single leaf with a flat ``/Names`` array, or a
    balanced tree of intermediate ``/Kids`` nodes — an external optimizer can
    rewrite one form into the other, so counting only the flat leaf would
    misread (and wrongly reject) a perfectly good output.
    """
    if node is None:
        return 0
    total = 0
    names = node.get("/Names")
    if names is not None:
        total += len(names) // 2
    kids = node.get("/Kids")
    if kids is not None:
        for kid in kids:
            total += _count_name_tree(kid)
    return total


def _count_outline(items) -> int:
    total = 0
    for item in items:
        total += 1 + _count_outline(item.children)
    return total


def _fingerprint(path: Path) -> _Fingerprint:
    with pikepdf.open(path) as pdf:
        fp = _Fingerprint(pages=len(pdf.pages))
        names = pdf.Root.get("/Names")
        if names is not None and "/Dests" in names:
            fp.dests = _count_name_tree(names["/Dests"])
        fp.page_labels = "/PageLabels" in pdf.Root
        for page in pdf.pages:
            for annot in page.get("/Annots", []) or []:
                action = annot.get("/A")
                if action is not None and action.get("/S") == pikepdf.Name.GoTo:
                    fp.goto_links += 1
        try:
            with pdf.open_outline() as ol:
                fp.outline_items = _count_outline(ol.root)
        except (pikepdf.PdfError, AttributeError, ValueError):
            fp.outline_items = 0
    return fp


def run_external(path: Path, policy: FontPolicy, stats: ReconcileStats) -> ReconcileStats:
    """Try the external recompaction tiers on ``path`` in place, gated by
    structure verification. Mutates and returns ``stats``."""
    if policy.reconcile not in ("merge", "deep"):
        return stats

    tools = _candidate_tools(policy)
    if not tools:
        stats.external_reason = "no external optimizer available"
        return stats

    stats.size_before = path.stat().st_size
    stats.size_after = stats.size_before
    before = _fingerprint(path)
    # A unique sibling temp (same directory → same filesystem, so the final
    # ``replace`` is atomic) avoids colliding with a concurrent build on the
    # same output path. mkstemp reserves the name with no TOCTOU window; each
    # tool overwrites the (initially empty) file, and an empty file after a
    # 0 return code is treated as "no output".
    fd, tmp_name = tempfile.mkstemp(prefix=".pdfc-reconcile-", suffix=".pdf", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        for tool in tools:
            stats.external_tool = tool
            tmp.write_bytes(b"")  # clear any prior iteration's output
            try:
                proc = subprocess.run(
                    _command(tool, path, tmp),
                    capture_output=True,
                    timeout=600,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                stats.external_reason = f"{type(e).__name__}"
                continue
            if proc.returncode != 0 or tmp.stat().st_size == 0:
                stats.external_reason = "tool failed"
                continue
            try:
                after = _fingerprint(tmp)
            except pikepdf.PdfError:
                stats.external_reason = "produced unreadable PDF"
                continue
            if not after.preserves(before):
                stats.external_reason = "would break navigation structure"
                continue
            new_size = tmp.stat().st_size
            if new_size >= stats.size_before:
                stats.external_reason = "no size improvement"
                continue
            # Accept: atomically replace the output with the smaller, verified copy.
            tmp.replace(path)
            stats.external_applied = True
            stats.external_reason = ""
            stats.size_after = new_size
            return stats
        return stats
    finally:
        _unlink(tmp)


def _unlink(p: Path) -> None:
    with contextlib.suppress(OSError):
        p.unlink()
