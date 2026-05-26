"""pdf-compiler: stitch large PDFs from a YAML spec."""

from importlib.metadata import PackageNotFoundError as _E
from importlib.metadata import version as _v

try:
    __version__ = _v("pdf-compiler")
except _E:
    __version__ = "0.0.0"
