"""Extension loader -- discovers and imports user extensions from ~/.sylvan/extensions/."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

from sylvan.logging import get_logger

logger = get_logger(__name__)

EXTENSION_DIRS = ("languages", "parsers", "providers", "tools")


def load_extensions() -> int:
    """Load native extensions and user extensions.

    Native extensions ship with sylvan (e.g. kubernetes support).
    User extensions live in ~/.sylvan/extensions/.

    Returns:
        Number of extension files successfully loaded.
    """
    from sylvan.config import get_config

    config = get_config()
    if not config.extensions.enabled:
        logger.debug("extensions_disabled")
        return 0

    # Load native extensions first
    native_count = _load_native_extensions(config)

    # Then user extensions

    base = Path.home() / ".sylvan" / "extensions"
    if not base.exists():
        logger.debug("extensions_dir_missing", path=str(base))
        return 0

    excluded = set(config.extensions.exclude)
    loaded = 0

    for subdir in EXTENSION_DIRS:
        ext_dir = base / subdir
        if not ext_dir.is_dir():
            continue

        for py_file in sorted(ext_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            relative = f"{subdir}/{py_file.name}"
            if relative in excluded:
                logger.debug("extension_excluded", file=relative)
                continue

            if not _validate(py_file, relative):
                continue

            if _import(py_file, subdir, relative):
                loaded += 1

    if loaded:
        logger.info("user_extensions_loaded", count=loaded)

    return native_count + loaded


def _validate(py_file: Path, relative: str) -> bool:
    """Check that a Python file has valid syntax.

    Args:
        py_file: Absolute path to the extension file.
        relative: Relative path for logging.

    Returns:
        True if the file compiles without errors.
    """
    try:
        py_compile.compile(str(py_file), doraise=True)
        return True
    except py_compile.PyCompileError as e:
        logger.warning("extension_syntax_error", file=relative, error=str(e))
        return False


def _import(py_file: Path, subdir: str, relative: str) -> bool:
    """Import an extension file so its decorators fire.

    Args:
        py_file: Absolute path to the extension file.
        subdir: Subdirectory name (languages, parsers, etc.).
        relative: Relative path for logging.

    Returns:
        True if the import succeeded.
    """
    module_name = f"sylvan_ext_{subdir}_{py_file.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            logger.warning("extension_no_spec", file=relative)
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logger.info("extension_loaded", file=relative)
        return True
    except Exception as e:
        logger.warning("extension_load_failed", file=relative, error=str(e))
        return False


def _load_native_extensions(config) -> int:
    """Load native extensions that ship with sylvan.

    Returns:
        Number of native extensions loaded.
    """
    count = 0

    try:
        import sylvan.extensions.native.kubernetes  # noqa: F401

        count += 1
        logger.info("native_extension_loaded", name="kubernetes")
    except Exception as e:
        logger.debug("native_extension_failed", name="kubernetes", error=str(e))

    if count:
        logger.info("native_extensions_loaded", count=count)

    return count
