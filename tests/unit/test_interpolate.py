"""Tests for the ``{{name}}`` variable substitution."""
from __future__ import annotations

import datetime as _dt

from pdf_compiler.interpolate import (
    builtin_vars,
    interpolate,
    resolve_vars,
    vars_hash,
)


def test_builtin_vars_for_known_date():
    bv = builtin_vars(_dt.date(2026, 5, 21))
    assert bv["today"] == "2026-05-21"
    assert bv["year"] == "2026"
    assert bv["month"] == "05"
    assert bv["day"] == "21"
    assert bv["month_name"] == "May"


def test_user_vars_override_builtins():
    v = resolve_vars({"today": "FOREVER"})
    assert v["today"] == "FOREVER"


def test_interpolate_basic():
    assert interpolate("hi {{name}}", {"name": "world"}) == "hi world"


def test_interpolate_whitespace_inside_braces():
    assert interpolate("{{  name  }}", {"name": "v"}) == "v"


def test_interpolate_unknown_passes_through():
    """Unknown vars must NOT raise — keeps existing docs that happen to use {{}}
    intact when the feature is unused."""
    assert interpolate("hi {{unknown}}", {"name": "v"}) == "hi {{unknown}}"


def test_interpolate_none_input():
    assert interpolate(None, {"x": "1"}) is None


def test_interpolate_no_braces_is_passthrough():
    assert interpolate("no vars here", {"x": "1"}) == "no vars here"


def test_interpolate_multiple_occurrences():
    out = interpolate("{{a}} and {{a}} and {{b}}", {"a": "x", "b": "y"})
    assert out == "x and x and y"


def test_vars_hash_is_stable_across_key_order():
    a = vars_hash({"a": "1", "b": "2"})
    b = vars_hash({"b": "2", "a": "1"})
    assert a == b


def test_vars_hash_changes_on_value_change():
    assert vars_hash({"a": "1"}) != vars_hash({"a": "2"})


def test_resolve_vars_coerces_non_strings():
    v = resolve_vars({"n": 42, "f": 3.14, "b": True})
    assert v["n"] == "42"
    assert v["f"] == "3.14"
    assert v["b"] == "True"


# --- markdown=True newline handling ---------------------------------------- #


def test_interpolate_markdown_converts_newline_to_hard_break():
    """A newline in a var value must become a CommonMark hard line break."""
    result = interpolate("{{addr}}", {"addr": "Line1\nLine2"}, markdown=True)
    assert result == "Line1  \nLine2"


def test_interpolate_markdown_multiple_newlines():
    result = interpolate("{{x}}", {"x": "a\nb\nc"}, markdown=True)
    assert result == "a  \nb  \nc"


def test_interpolate_non_markdown_leaves_newlines_unchanged():
    """Without markdown=True newlines in var values pass through as-is."""
    result = interpolate("{{addr}}", {"addr": "Line1\nLine2"})
    assert result == "Line1\nLine2"


def test_interpolate_markdown_no_newline_unchanged():
    """Var values without newlines are unaffected by markdown=True."""
    assert interpolate("{{x}}", {"x": "hello"}, markdown=True) == "hello"
