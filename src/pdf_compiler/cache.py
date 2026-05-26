"""Content-addressed cache for compiled section PDFs.

A section's cache key is a blake3 hash over:
  - the section's pydantic model dump (JSON, sorted keys)
  - the bytes of every input file the section references
  - the global defaults (so a font-size change invalidates everything)
  - the pdf_compiler version

On a hit we copy the cached PDF to the working tmpdir; on a miss the caller
compiles and calls :func:`put`.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from blake3 import blake3

from pdf_compiler import __version__

_HASH_CHUNK = 1 << 20  # 1 MiB


def default_cache_dir() -> Path:
    """Honour XDG_CACHE_HOME, else ~/.cache/pdf-compiler."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "pdf-compiler"


@dataclass(frozen=True, slots=True)
class Cache:
    root: Path
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Path | None:
        if not self.enabled:
            return None
        p = self._path(key)
        return p if p.is_file() else None

    def put(self, key: str, src: Path) -> Path:
        if not self.enabled:
            return src
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: copy to tmp in same dir, then rename.
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        return dst

    def _path(self, key: str) -> Path:
        # Fan out to keep directory sizes sane.
        return self.root / key[:2] / f"{key}.pdf"


def hash_section(
    section_dump: dict,
    *,
    defaults_dump: dict,
    input_files: Iterable[Path],
    extra: bytes = b"",
) -> str:
    """Compute the cache key for a section.

    ``section_dump`` and ``defaults_dump`` are pydantic ``model_dump()`` results
    (JSON-safe). ``input_files`` is the set of files whose bytes affect the
    output (markdown files, included PDFs, images...).
    """
    h = blake3()
    h.update(__version__.encode())
    h.update(b"\x00defaults\x00")
    h.update(json.dumps(defaults_dump, sort_keys=True, default=str).encode())
    h.update(b"\x00section\x00")
    h.update(json.dumps(section_dump, sort_keys=True, default=str).encode())
    h.update(b"\x00extra\x00")
    h.update(extra)
    h.update(b"\x00files\x00")
    for f in sorted(input_files):
        h.update(str(f).encode())
        h.update(b"\x00")
        _hash_file_into(h, f)
        h.update(b"\x00")
    return h.hexdigest()


def _hash_file_into(h: blake3, path: Path) -> None:
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            h.update(chunk)


def clear_cache(root: Path) -> int:
    """Remove all cached PDFs; return the count removed."""
    n = 0
    if not root.is_dir():
        return 0
    for p in root.rglob("*.pdf"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n
