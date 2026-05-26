"""BuildContext: the read-only environment a section sees while compiling.

Holds: project root (for resolving relative paths), defaults, cache, tmpdir,
worker count, version. Immutable. Passed by value into worker processes.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pdf_compiler.cache import Cache, default_cache_dir
from pdf_compiler.interpolate import resolve_vars, vars_hash
from pdf_compiler.spec import Defaults, Metadata, Spec


@dataclass(frozen=True, slots=True)
class BuildContext:
    project_root: Path  # directory of the spec file
    defaults: Defaults
    metadata: Metadata
    cache: Cache
    tmpdir: Path
    jobs: int
    # Resolved ``{{name}}`` substitutions (builtins merged with user vars).
    vars: dict[str, str] = field(default_factory=dict)
    # Stable hash of ``vars`` — folded into section cache keys so changing
    # a variable value invalidates everything that interpolates it.
    vars_hash: str = ""

    def resolve(self, path: Path) -> Path:
        """Resolve a (possibly relative) path against the project root."""
        p = Path(path)
        return p if p.is_absolute() else (self.project_root / p).resolve()

    def tmp_pdf(self, hint: str = "section") -> Path:
        # NamedTemporaryFile would auto-delete; we just want a unique path.
        fd, name = tempfile.mkstemp(suffix=".pdf", prefix=f"{hint}-", dir=self.tmpdir)
        os.close(fd)
        return Path(name)


def build_context(
    spec_path: Path,
    spec: Spec,
    *,
    jobs: int = 0,
    use_cache: bool = True,
    cache_dir: Path | None = None,
    tmpdir: Path | None = None,
) -> BuildContext:
    project_root = spec_path.parent.resolve()
    cache = Cache(root=cache_dir or default_cache_dir(), enabled=use_cache)
    tmp = tmpdir or Path(tempfile.mkdtemp(prefix="pdfc-"))
    tmp.mkdir(parents=True, exist_ok=True)
    vars_resolved = resolve_vars(spec.vars)
    return BuildContext(
        project_root=project_root,
        defaults=spec.defaults,
        metadata=spec.metadata,
        cache=cache,
        tmpdir=tmp,
        jobs=jobs or max(1, (os.cpu_count() or 2) - 1),
        vars=vars_resolved,
        vars_hash=vars_hash(vars_resolved),
    )
