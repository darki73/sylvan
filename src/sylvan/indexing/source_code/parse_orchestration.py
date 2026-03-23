"""Tree-sitter parse orchestration -- coordinates file parsing and symbol extraction."""

from dataclasses import dataclass, field

from sylvan.database.validation import Symbol
from sylvan.indexing.source_code.extractor import parse_file
from sylvan.indexing.source_code.language_specs import detect_language
from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class ParseResult:
    """Result of parsing a single file.

    Attributes:
        file_path: Relative path of the parsed file.
        language: Detected or overridden language identifier.
        symbols: List of extracted Symbol objects.
        error: Error message if parsing failed, None on success.
    """

    file_path: str
    language: str | None
    symbols: list[Symbol] = field(default_factory=list)
    error: str | None = None


def parse_source_file(
    file_path: str,
    content: str,
    language: str | None = None,
) -> ParseResult:
    """Parse a single source file and extract symbols.

    Args:
        file_path: Relative path of the file.
        content: File content as string.
        language: Language override (auto-detected from extension if None).

    Returns:
        A ParseResult containing extracted symbols or an error message.
    """
    if language is None:
        language = detect_language(file_path)

    if language is None:
        return ParseResult(file_path, None, error="unknown_language")

    try:
        symbols = parse_file(content, file_path, language)
        return ParseResult(file_path, language, symbols)
    except Exception as e:
        logger.warning("parse_error", file_path=file_path, error=str(e))
        return ParseResult(file_path, language, error=str(e))
