from __future__ import annotations

from pathlib import Path

from pdf_compiler.cache import Cache, clear_cache, hash_section


def test_hash_stable_for_same_inputs(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("hello")
    h1 = hash_section({"type": "markdown"}, defaults_dump={}, input_files=[f])
    h2 = hash_section({"type": "markdown"}, defaults_dump={}, input_files=[f])
    assert h1 == h2


def test_hash_changes_when_file_changes(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("hello")
    h1 = hash_section({"type": "markdown"}, defaults_dump={}, input_files=[f])
    f.write_text("hello world")
    h2 = hash_section({"type": "markdown"}, defaults_dump={}, input_files=[f])
    assert h1 != h2


def test_hash_changes_when_section_changes(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("hello")
    h1 = hash_section({"type": "markdown", "x": 1}, defaults_dump={}, input_files=[f])
    h2 = hash_section({"type": "markdown", "x": 2}, defaults_dump={}, input_files=[f])
    assert h1 != h2


def test_hash_changes_with_defaults(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("hello")
    h1 = hash_section({}, defaults_dump={"page_size": "letter"}, input_files=[f])
    h2 = hash_section({}, defaults_dump={"page_size": "a4"}, input_files=[f])
    assert h1 != h2


def test_cache_put_then_get(tmp_path: Path):
    c = Cache(root=tmp_path / "c")
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-fake\n")
    p = c.put("abcdef" * 11, src)
    got = c.get("abcdef" * 11)
    assert got == p
    assert got.read_bytes() == b"%PDF-fake\n"


def test_cache_miss_returns_none(tmp_path: Path):
    c = Cache(root=tmp_path / "c")
    assert c.get("deadbeef" * 8) is None


def test_disabled_cache_is_passthrough(tmp_path: Path):
    c = Cache(root=tmp_path / "c", enabled=False)
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-fake\n")
    assert c.get("k") is None
    assert c.put("k", src) == src  # disabled returns src untouched


def test_clear_cache(tmp_path: Path):
    c = Cache(root=tmp_path / "c")
    src = tmp_path / "in.pdf"
    src.write_bytes(b"x")
    c.put("a" * 64, src)
    c.put("b" * 64, src)
    n = clear_cache(c.root)
    assert n == 2
    assert c.get("a" * 64) is None


def test_clear_cache_missing_dir(tmp_path: Path):
    assert clear_cache(tmp_path / "nope") == 0
