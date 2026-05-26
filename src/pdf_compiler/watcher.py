"""`pdfc watch` — recompile only when spec inputs change."""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pdf_compiler.loader import SpecError, load_spec
from pdf_compiler.pipeline import compile_spec

_console = Console()


def run_watch(spec_path: Path, *, out_path: Path | None = None) -> None:
    """Block, recompiling whenever a known input file changes."""
    spec_path = spec_path.resolve()

    # Mutable state shared between compile_once and the event handler.
    inputs: set[Path] = _collect_inputs(spec_path)
    watched_dirs: set[Path] = set()

    observer = Observer()
    handler = _Handler(callback=None, get_inputs=lambda: inputs)

    def _schedule_new_dirs() -> None:
        for p in inputs:
            d = p.parent
            if d not in watched_dirs and d.is_dir():
                observer.schedule(handler, str(d), recursive=False)
                watched_dirs.add(d)

    def compile_once() -> None:
        nonlocal inputs
        try:
            r = compile_spec(spec_path, out_path=out_path)
            _console.print(f"[green]✓[/green] {r.output_path} ({r.page_count} pages)")
        except Exception as e:  # noqa: BLE001
            # Watcher boundary: any failure from the pipeline is reported and
            # then swallowed so the loop survives to the next file change.
            _console.print(f"[red]✗[/red] {e}")
        # Refresh inputs after every attempt — spec may have changed.
        inputs = _collect_inputs(spec_path)
        _schedule_new_dirs()

    handler._cb = compile_once  # type: ignore[attr-defined]

    # Schedule initial directories before starting the observer.
    _schedule_new_dirs()
    observer.start()
    compile_once()

    n = len(inputs)
    _console.print(f"[blue]watching[/blue] {n} input file{'s' if n != 1 else ''} — Ctrl-C to stop")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def _collect_inputs(spec_path: Path) -> set[Path]:
    """Return the resolved paths of every file that can affect the build."""
    base = spec_path.parent
    result: set[Path] = {spec_path}
    try:
        spec = load_spec(spec_path)
    except (SpecError, OSError):
        # Spec may be mid-edit and unparseable; keep watching the spec file.
        return result
    for sec in spec.sections:
        if (p := getattr(sec, "path", None)) is not None:
            result.add((base / p).resolve())
        if (imgs := getattr(sec, "images", None)) is not None:
            for img in imgs:
                result.add((base / img.path).resolve())
    return result


class _Handler(FileSystemEventHandler):
    def __init__(self, callback, get_inputs, debounce: float = 1.0):
        self._cb = callback
        self._get_inputs = get_inputs
        self._debounce = debounce
        self._last = 0.0

    def on_any_event(self, event) -> None:
        if event.is_directory:
            return
        # Only react to files we actually care about.
        if Path(event.src_path).resolve() not in self._get_inputs():
            return
        now = time.monotonic()
        if now - self._last < self._debounce:
            return
        self._last = now
        self._cb()
