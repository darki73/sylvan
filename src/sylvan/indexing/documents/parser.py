"""Document format router -- dispatches to the appropriate parser via the registry."""

import sylvan.indexing.documents.formats.asciidoc as _asciidoc  # noqa: F401
import sylvan.indexing.documents.formats.html as _html  # noqa: F401
import sylvan.indexing.documents.formats.json_parser as _json  # noqa: F401
import sylvan.indexing.documents.formats.markdown as _markdown  # noqa: F401
import sylvan.indexing.documents.formats.notebook as _notebook  # noqa: F401
import sylvan.indexing.documents.formats.openapi as _openapi  # noqa: F401
import sylvan.indexing.documents.formats.rst as _rst  # noqa: F401
import sylvan.indexing.documents.formats.text as _text  # noqa: F401
import sylvan.indexing.documents.formats.xml_parser as _xml  # noqa: F401
import sylvan.indexing.documents.formats.yaml_parser as _yaml  # noqa: F401
from sylvan.database.validation import Section
from sylvan.indexing.documents.registry import get_parser_for_extension


def parse_document(content: str, file_path: str, repo: str) -> list[Section]:
    """Parse a documentation file and return structured sections.

    The parser is chosen by looking up the file extension in the parser
    registry.  Sniffer-gated parsers (e.g. OpenAPI) are tried first for
    shared extensions; the first unguarded match is used otherwise.
    Unknown extensions fall back to the plain-text parser.

    Args:
        content: Raw file content as a string.
        file_path: Path to the file (used for extension detection).
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects.
    """
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    parser = get_parser_for_extension(ext, content=content)
    if parser is None:
        from sylvan.indexing.documents.formats.text import parse_text

        return parse_text(content, file_path, repo)
    return parser(content, file_path, repo)
