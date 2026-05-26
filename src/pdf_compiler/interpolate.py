"""Variable substitution for user-facing strings.

``{{ name }}`` placeholders in titles, headers, captions, and markdown
content are replaced from a merged dict of user-supplied vars and a small
set of builtins (today, year, etc.). Unknown names pass through unchanged
so existing documents that happen to contain ``{{...}}`` are not broken
by the feature.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def builtin_vars(today: _dt.date | None = None) -> dict[str, str]:
    """Variables always available without a ``vars:`` block."""
    today = today or _dt.date.today()
    return {
        "today": today.isoformat(),
        "year": str(today.year),
        "month": f"{today.month:02d}",
        "day": f"{today.day:02d}",
        "month_name": today.strftime("%B"),
    }


def resolve_vars(user_vars: Mapping[str, Any] | None) -> dict[str, str]:
    """Merge user vars over the builtins; coerce values to strings."""
    out = builtin_vars()
    if user_vars:
        for k, v in user_vars.items():
            out[k] = "" if v is None else str(v)
    return out


def interpolate(
    text: str | None,
    vars: Mapping[str, str],
    *,
    markdown: bool = False,
) -> str | None:
    """Replace ``{{ name }}`` references in ``text`` using ``vars``.

    Unknown names render as their literal source (``{{ name }}``).

    When *markdown* is ``True``, newlines in substituted values are
    converted to CommonMark hard line breaks (``  \\n``) so that a
    multi-line var value produces actual line breaks in the rendered PDF
    rather than collapsing to a space.  Pass ``markdown=True`` when
    interpolating into markdown file content or header body text;
    leave it ``False`` for titles, captions, and other HTML-rendered
    strings where whitespace is handled by the browser/renderer.
    """
    if not text or "{{" not in text:
        return text

    def _repl(m: re.Match) -> str:
        val = vars.get(m.group(1), m.group(0))
        if markdown and "\n" in val:
            # Two trailing spaces = CommonMark hard line break.
            val = val.replace("\n", "  \n")
        return val

    return _VAR_RE.sub(_repl, text)


def vars_hash(vars: Mapping[str, str]) -> str:
    """Stable short hash of a vars dict — feeds into section cache keys."""
    blob = json.dumps(sorted(vars.items()), separators=(",", ":")).encode("utf-8")
    return hashlib.blake2s(blob, digest_size=8).hexdigest()
