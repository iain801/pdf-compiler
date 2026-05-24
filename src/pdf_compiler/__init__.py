"""pdf-compiler: stitch large PDFs from a YAML spec."""

from importlib.metadata import version as _v, PackageNotFoundError as _E

try:
    __version__ = _v("pdf-compiler")
except _E:
    __version__ = "0.0.0"
