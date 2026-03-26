"""Sylvan - code intelligence engine for AI agents and Python scripts."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sylvan")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from sylvan.api import Sylvan

__all__ = ["Sylvan", "__version__"]
