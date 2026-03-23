"""Document parser registry -- auto-discovery via @register_parser decorator."""

from collections.abc import Callable

_PARSERS: dict[str, Callable] = {}
_EXTENSION_MAP: dict[str, list[str]] = {}
_SNIFFERS: dict[str, Callable] = {}


def register_parser(
    format_name: str,
    extensions: list[str],
    *,
    sniffer: Callable | None = None,
) -> Callable[[Callable], Callable]:
    """Register a document format parser.

    Use as a decorator on parser functions:

        @register_parser("markdown", [".md", ".markdown", ".mdx"])
        def parse_markdown(content: str, doc_path: str, repo: str) -> list[Section]:
            ...

    When a *sniffer* is provided the parser is content-gated: the extension
    is claimed but the parser is only invoked when the sniffer returns True.
    Sniffer-gated parsers are tried before unguarded ones, allowing a more
    specific parser (e.g. OpenAPI) to take priority over a generic one
    (e.g. JSON) for the same extension.

    Args:
        format_name: Human-readable format name (e.g., 'markdown', 'rst').
        extensions: File extensions this parser handles (e.g., ['.md', '.markdown']).
        sniffer: Optional callable ``(content, ext) -> bool`` that returns True
            when the content matches this format.

    Returns:
        Decorator function that registers the parser.
    """

    def decorator(func: Callable) -> Callable:
        """Register the parser function and map its extensions."""
        _PARSERS[format_name] = func
        for ext in extensions:
            ext_lower = ext.lower()
            _EXTENSION_MAP.setdefault(ext_lower, [])
            if sniffer is not None:
                _EXTENSION_MAP[ext_lower].insert(0, format_name)
            else:
                _EXTENSION_MAP[ext_lower].append(format_name)
        if sniffer is not None:
            _SNIFFERS[format_name] = sniffer
        return func

    return decorator


def get_parser_for_extension(
    ext: str,
    content: str | None = None,
) -> Callable | None:
    """Look up the parser function for a file extension.

    When *content* is provided, sniffer-gated parsers registered for the
    extension are evaluated first.  If no sniffer matches (or content is
    not provided) the first unguarded parser wins.

    Args:
        ext: File extension including the dot (e.g., '.md').
        content: Optional raw file content used for sniffer-gated parsers.

    Returns:
        The parser function, or None if no parser handles this extension.
    """
    ext_lower = ext.lower()
    candidates = _EXTENSION_MAP.get(ext_lower)
    if not candidates:
        return None

    fallback: Callable | None = None
    for fmt in candidates:
        sniffer = _SNIFFERS.get(fmt)
        if sniffer is not None:
            if content is not None and sniffer(content, ext_lower):
                return _PARSERS[fmt]
        elif fallback is None:
            fallback = _PARSERS.get(fmt)

    return fallback


def list_supported_formats() -> dict[str, list[str]]:
    """List all registered formats and their extensions.

    Returns:
        Dict mapping format names to their supported extensions.
    """
    result: dict[str, list[str]] = {}
    for ext, format_names in sorted(_EXTENSION_MAP.items()):
        for format_name in format_names:
            result.setdefault(format_name, []).append(ext)
    return result
