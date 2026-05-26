"""YAML → Spec loader with line-number-aware error reporting.

ruamel.yaml preserves source positions; we lift them into pydantic
ValidationError messages so users see ``spec.yaml:14`` instead of
``__root__.sections.2.path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from pdf_compiler.spec import Spec

_YAML = YAML(typ="rt")  # round-trip parser preserves source line numbers


class SpecError(ValueError):
    """User-facing error for invalid specs."""


def load_spec(path: str | Path) -> Spec:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = _YAML.load(text)
    except YAMLError as e:
        raise SpecError(f"{path}: YAML parse error: {e}") from e
    if data is None:
        raise SpecError(f"{path}: spec is empty")
    if not isinstance(data, dict):
        raise SpecError(f"{path}: top-level YAML must be a mapping")
    try:
        return Spec.model_validate(data)
    except ValidationError as e:
        raise SpecError(_format_validation(path, data, e)) from e


def _format_validation(path: Path, data: Any, e: ValidationError) -> str:
    lines = [f"{path}: spec is invalid:"]
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        line = _locate(data, err["loc"])
        loc_str = f"line {line}, " if line is not None else ""
        lines.append(f"  - {loc_str}{loc}: {err['msg']}")
    return "\n".join(lines)


def _locate(data: Any, loc: tuple) -> int | None:
    """Walk a ruamel CommentedMap/CommentedSeq to find the source line.

    pydantic's discriminated-union errors include the tag name as a fake
    path element (e.g. ``sections.1.title.bogus`` for an extra key inside
    a TitleSection). We walk as far as we can and return the deepest line
    we landed on rather than failing on the synthetic step.
    """
    node = data
    last_line: int | None = _line_of(node)
    for part in loc:
        nxt: Any = None
        if isinstance(part, int):
            try:
                nxt = node[part]
            except (TypeError, IndexError, KeyError):
                nxt = None
        elif isinstance(node, dict) and part in node:
            # Prefer the value's line, but try to grab the key's line first
            # (better for "extra field" errors that point at a missing key).
            key_line = _key_line(node, part)
            if key_line is not None:
                last_line = key_line
            nxt = node[part]
        if nxt is None:
            return last_line
        node = nxt
        nl = _line_of(node)
        if nl is not None:
            last_line = nl
    return last_line


def _line_of(node: Any) -> int | None:
    lc = getattr(node, "lc", None)
    if lc is None or lc.line is None:
        return None
    return lc.line + 1


def _key_line(node: Any, key: Any) -> int | None:
    lc = getattr(node, "lc", None)
    if lc is None:
        return None
    try:
        info = lc.key(key)
    except (KeyError, AttributeError):
        return None
    if info is None:
        return None
    return info[0] + 1
