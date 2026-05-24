"""`pdfc watch` — recompile on filesystem changes to the spec or its inputs."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pdf_compiler.pipeline import compile_spec

_console = Console()

# Extensions and names that never trigger a recompile.  These cover:
#   - The output PDF itself (matched by resolved path, see _Handler)
#   - iCloud Drive sync artefacts (.icloud placeholders, xattr helpers)
#   - OS and editor temp/meta files
_IGNORE_SUFFIXES = frozenset({
    ".icloud", ".tmp", ".swp", ".swo", ".pyc", ".pyo",
})
_IGNORE_NAMES = frozenset({
    ".DS_Store", "Thumbs.db", "desktop.ini",
})


def run_watch(spec_path: Path, *, out_path: Path | None = None) -> None:
    """Block, recompiling on every relevant change. Press Ctrl-C to stop."""

    # Resolve the output path now so the handler can ignore write events to it.
    try:
        from pdf_compiler.loader import load_spec
        _spec = load_spec(spec_path)
        output_path = (out_path or spec_path.parent / _spec.output).resolve()
    except Exception:  # noqa: BLE001
        output_path = out_path.resolve() if out_path else None

    def compile_once() -> None:
        try:
            r = compile_spec(spec_path, out_path=out_path)
            _console.print(f"[green]✓[/green] {r.output_path} ({r.page_count} pages)")
        except Exception as e:  # noqa: BLE001
            _console.print(f"[red]✗[/red] {e}")

    compile_once()
    handler = _Handler(compile_once, output_path=output_path)
    observer = Observer()
    observer.schedule(handler, str(spec_path.parent.resolve()), recursive=True)
    observer.start()
    _console.print(
        f"[blue]watching[/blue] {spec_path.parent.resolve()} — Ctrl-C to stop"
    )
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        callback,
        output_path: Path | None,
        debounce: float = 1.5,
    ):
        self._cb = callback
        self._debounce = debounce
        self._last = 0.0
        self._output = output_path

    def _should_ignore(self, src_path: str) -> bool:
        p = Path(src_path)
        name = p.name
        # Hidden files and editor temp files.
        if name.startswith(".") or name.startswith("~"):
            return True
        if name in _IGNORE_NAMES:
            return True
        if p.suffix.lower() in _IGNORE_SUFFIXES:
            return True
        # The output PDF: writing it must not re-trigger compilation.
        if self._output and p.resolve() == self._output:
            return True
        return False

    def on_any_event(self, event) -> None:
        if event.is_directory:
            return
        if self._should_ignore(event.src_path):
            return
        now = time.monotonic()
        if now - self._last < self._debounce:
            return
        self._last = now
        self._cb()
