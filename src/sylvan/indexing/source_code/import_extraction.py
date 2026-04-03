"""Per-language import extraction from source files."""


def extract_imports(content: str, file_path: str, language: str) -> list[dict]:
    """Extract import statements from source code.

    Delegates to the language plugin's import extractor if one is registered.
    Falls back to JSON-specific extraction for JSON files.

    Args:
        content: Source file content.
        file_path: Relative file path (used by JSON extractor).
        language: Language identifier for selecting the correct extractor.

    Returns:
        List of dicts with "specifier" (str) and "names" (list[str]) keys.
    """
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
