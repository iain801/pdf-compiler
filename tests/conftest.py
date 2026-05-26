"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest


@pytest.fixture
def make_pdf(tmp_path: Path):
    """Create a minimal multi-page PDF on disk for testing."""

    def _make(
        n_pages: int,
        name: str = "test.pdf",
        page_size: tuple[float, float] = (612, 792),
    ) -> Path:
        pdf = pikepdf.Pdf.new()
        for _ in range(n_pages):
            pdf.add_blank_page(page_size=page_size)
        out = tmp_path / name
        pdf.save(out)
        pdf.close()
        return out

    return _make


@pytest.fixture
def png_bytes() -> bytes:
    """A 1x1 transparent PNG."""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c63f8cfc0c00000000300010000fa55a4ec0000"
        "000049454e44ae426082"
    )
