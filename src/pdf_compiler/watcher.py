"""`pdfc watch` — recompile on filesystem changes to the spec or its inputs."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from pdf_compiler.pipeline import compile_spec

_console = Console()


def run_watch(spec_path: Path, *, out_path: Path | None = None) -> None:
    """Block, recompiling on every change. Press Ctrl-C to stop."""

    def compile_once() -> None:
        try:
            r = compile_spec(spec_path, out_path=out_path)
            _console.print(f"[green]✓[/green] {r.output_path} ({r.page_count} pages)")
        except Exception as e:  # noqa: BLE001
            _console.print(f"[red]✗[/red] {e}")

    compile_once()
    handler = _Handler(compile_once)
    observer = Observer()
    observer.schedule(handler, str(spec_path.parent.resolve()), recursive=True)
    observer.start()
    _console.print(f"[blue]watching[/blue] {spec_path.parent.resolve()} — Ctrl-C to stop")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


class _Handler(FileSystemEventHandler):
    def __init__(self, callback, debounce: float = 0.3):
        self._cb = callback
        self._debounce = debounce
        self._last = 0.0

    def on_modified(self, event):
        if event.is_directory:
            return
        now = time.monotonic()
        if now - self._last < self._debounce:
            return
        self._last = now
        self._cb()

    on_created = on_modified
    on_moved = on_modified
