"""Per-language import extraction from source files."""

from sylvan._rust import extract_imports as _rust_extract_imports
from sylvan._rust import import_supported_languages as _rust_import_languages

_RUST_LANGUAGES: frozenset[str] = frozenset(_rust_import_languages())


def extract_imports(content: str, file_path: str, language: str) -> list[dict]:
    """Extract import statements from source code.

    Routes Rust-supported languages through the Rust extractor; falls
    back to the legacy Python plugin for everything else, plus the
    JSON-specific extractor for JSON files.

    Args:
        content: Source file content.
        file_path: Relative file path (used by JSON extractor).
        language: Language identifier for selecting the correct extractor.

    Returns:
        List of dicts with "specifier" (str) and "names" (list[str]) keys.
    """
    if language in _RUST_LANGUAGES:
        try:
            return list(_rust_extract_imports(content, file_path, language))
        except Exception:
            return []

    if language == "json":
        try:
            from sylvan.indexing.source_code.json_extractor import extract_json_imports

            return extract_json_imports(content, file_path)
        except Exception:
            return []

    from sylvan.indexing.languages import get_import_extractor

    extractor = get_import_extractor(language)
    if extractor is None:
        return []

    try:
        return extractor.extract_imports(content)
    except Exception:
        return []
