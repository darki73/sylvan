"""Symbol extraction from source code using tree-sitter.

Walks the AST using field-based navigation driven by LanguageSpec definitions.
Each language has a spec that maps AST node types to symbol kinds, with
field names for extracting names, parameters, return types, and docstrings.

Falls back gracefully: unknown languages return no symbols, parse errors
are caught and reported (never crash).
"""

import hashlib

from tree_sitter_language_pack import get_parser

from sylvan.database.validation import Symbol, make_symbol_id
from sylvan.indexing.source_code.complexity import compute_complexity
from sylvan.indexing.source_code.language_specs import LanguageSpec, get_spec
from sylvan.indexing.source_code.stylesheet_extractor import (
    extract_less_extras,
    extract_scss_extras,
    extract_stylus_extras,
)
from sylvan.indexing.source_code.symbol_details import (
    build_signature,
    extract_decorators,
    extract_docstring,
    extract_name,
)
from sylvan.indexing.source_code.symbol_enrichment import (
    classify_methods,
    disambiguate_overloads,
    extract_keywords,
    heuristic_summary,
    try_extract_python_constant,
    try_extract_variable_function,
)


def compute_content_hash(source_bytes: bytes) -> str:
    """SHA-256 of the raw source bytes for drift detection.

    Args:
        source_bytes: Raw source code bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(source_bytes).hexdigest()


def _extract_vue_script(content: str) -> tuple[str, str, int]:
    """Extract the <script> block from a Vue SFC.

    Args:
        content: Full Vue file content.

    Returns:
        Tuple of (script_content, effective_language, byte_offset).
        effective_language is 'typescript' if lang="ts", else 'javascript'.
        byte_offset is the byte position of the script content in the original file.
    """
    import re

    match = re.search(
        r"<script\b[^>]*>(.*?)</script>",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return "", "typescript", 0

    tag = content[match.start() : match.start(1)]
    lang = "typescript" if "ts" in tag.lower() else "javascript"
    byte_offset = len(content[: match.start(1)].encode("utf-8"))

    return match.group(1), lang, byte_offset


def parse_file(content: str, filename: str, language: str) -> list[Symbol]:
    """Parse source code and extract symbols.

    For Vue SFCs, extracts the ``<script>`` block and parses it as
    TypeScript/JavaScript. Symbol byte offsets are adjusted to point
    into the original file.

    Args:
        content: Source code text.
        filename: Relative file path.
        language: Language identifier (e.g., 'python', 'typescript').

    Returns:
        List of Symbol objects extracted from the file.
    """
    if language == "json":
        from sylvan.indexing.source_code.json_extractor import extract_json_symbols

        return extract_json_symbols(content, filename)

    if language == "blade":
        from sylvan.indexing.source_code.blade_extractor import extract_blade_symbols

        return extract_blade_symbols(content, filename)

    vue_byte_offset = 0
    if language == "vue":
        script_content, language, vue_byte_offset = _extract_vue_script(content)
        if not script_content:
            return []
        content = script_content

    spec = get_spec(language)
    if spec is None:
        return []

    source_bytes = content.encode("utf-8")

    try:
        parser = get_parser(spec.ts_language)
    except Exception as e:
        from sylvan.logging import get_logger

        get_logger(__name__).debug("parser_load_failed", language=spec.ts_language, error=str(e))
        return []

    try:
        tree = parser.parse(source_bytes)
    except Exception as e:
        from sylvan.logging import get_logger

        get_logger(__name__).debug("tree_parse_failed", language=spec.ts_language, error=str(e))
        return []

    symbols: list[Symbol] = []
    _walk_tree(
        node=tree.root_node,
        spec=spec,
        source_bytes=source_bytes,
        filename=filename,
        language=language,
        symbols=symbols,
        parent_symbol=None,
        scope_parts=[],
    )

    disambiguate_overloads(symbols)
    classify_methods(symbols)

    if language == "scss":
        extras, _ = extract_scss_extras(content, filename, symbols, tree=tree)
        symbols.extend(extras)
    elif language == "less":
        extras, _ = extract_less_extras(content, filename, symbols, tree=tree)
        symbols.extend(extras)
    elif language == "stylus":
        extras, _ = extract_stylus_extras(content, filename, symbols)
        symbols.extend(extras)

    if vue_byte_offset:
        for sym in symbols:
            sym.byte_offset += vue_byte_offset

    return symbols


_HANDLER_WRAPPERS = frozenset(
    {
        "defineEventHandler",
        "defineNuxtRouteMiddleware",
        "eventHandler",
        "defineNitroPlugin",
    }
)


def _try_extract_export_default(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
) -> None:
    """Extract export default defineEventHandler() as a named function.

    Nuxt server routes use ``export default defineEventHandler(...)``
    which produces no named symbol. This extracts it using the filename
    to generate a meaningful name (e.g., ``health.get.ts`` -> ``healthGet``).

    Args:
        node: The export_statement AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        symbols: Accumulator list for extracted symbols.
    """
    text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    if not any(w in text for w in _HANDLER_WRAPPERS):
        return

    from pathlib import PurePosixPath

    stem = PurePosixPath(filename).stem
    parts = stem.split(".")
    if len(parts) >= 2:
        name = parts[0] + "".join(p.capitalize() for p in parts[1:])
    else:
        name = parts[0]

    start = node.start_byte
    end = node.end_byte
    symbols.append(
        Symbol(
            symbol_id=make_symbol_id(filename, name, "function"),
            name=name,
            qualified_name=name,
            kind="function",
            language=language,
            signature="export default defineEventHandler()",
            docstring=extract_docstring(node, spec, source_bytes, language),
            summary=f"Server route handler: {stem}",
            keywords=extract_keywords(name, None, []),
            parent_symbol_id=None,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            byte_offset=start,
            byte_length=end - start,
            content_hash=compute_content_hash(source_bytes[start:end]),
        )
    )


def _walk_tree(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
    parent_symbol: Symbol | None,
    scope_parts: list[str],
) -> None:
    """Recursively walk tree-sitter AST extracting symbols.

    Args:
        node: Current tree-sitter AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        symbols: Accumulator list for extracted symbols.
        parent_symbol: Enclosing symbol, or None at top level.
        scope_parts: Ancestor symbol names forming the qualified name prefix.
    """
    if node.has_error and node.type == "ERROR":
        return

    if node.type in spec.symbol_node_types:
        sym = _extract_symbol(
            node,
            spec,
            source_bytes,
            filename,
            language,
            parent_symbol,
            scope_parts,
        )
        if sym is not None:
            symbols.append(sym)
            if node.type in spec.container_node_types:
                for child in node.children:
                    _walk_tree(
                        child,
                        spec,
                        source_bytes,
                        filename,
                        language,
                        symbols,
                        sym,
                        [*scope_parts, sym.name],
                    )
                return

    if node.type == "decorated_definition":
        _handle_decorated_definition(
            node,
            spec,
            source_bytes,
            filename,
            language,
            symbols,
            parent_symbol,
            scope_parts,
        )
        return

    if node.type in ("lexical_declaration", "variable_declaration") and language in (
        "javascript",
        "typescript",
        "tsx",
    ):
        for child in node.children:
            if child.type == "variable_declarator":
                try_extract_variable_function(
                    child,
                    node,
                    spec,
                    source_bytes,
                    filename,
                    language,
                    symbols,
                    parent_symbol,
                    scope_parts,
                )

    if node.type in ("expression_statement", "assignment") and language == "python" and parent_symbol is None:
        try_extract_python_constant(
            node,
            spec,
            source_bytes,
            filename,
            language,
            symbols,
        )

    if node.type == "export_statement" and language in ("javascript", "typescript", "tsx") and parent_symbol is None:
        _try_extract_export_default(
            node,
            spec,
            source_bytes,
            filename,
            language,
            symbols,
        )

    for child in node.children:
        _walk_tree(
            child,
            spec,
            source_bytes,
            filename,
            language,
            symbols,
            parent_symbol,
            scope_parts,
        )


def _handle_decorated_definition(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
    parent_symbol: Symbol | None,
    scope_parts: list[str],
) -> None:
    """Extract symbols from decorated definitions (Python, TypeScript, Java).

    Fully handles the decorated node so the caller should not recurse into
    its children again, which would re-extract the inner symbol with a
    disambiguation suffix.

    Args:
        node: The decorated_definition AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        symbols: Accumulator list for extracted symbols.
        parent_symbol: Enclosing symbol, or None at top level.
        scope_parts: Ancestor symbol names forming the qualified name prefix.
    """
    for child in node.children:
        if child.type in spec.symbol_node_types:
            sym = _extract_symbol(
                child,
                spec,
                source_bytes,
                filename,
                language,
                parent_symbol,
                scope_parts,
                decorator_node=node,
            )
            if sym is not None:
                symbols.append(sym)
                if child.type in spec.container_node_types:
                    for grandchild in child.children:
                        _walk_tree(
                            grandchild,
                            spec,
                            source_bytes,
                            filename,
                            language,
                            symbols,
                            sym,
                            [*scope_parts, sym.name],
                        )
            return


def _truncate_name(name: str, max_length: int = 1000) -> str:
    """Truncate an oversized symbol name.

    Args:
        name: Raw symbol name.
        max_length: Maximum allowed length.

    Returns:
        Name truncated to max_length if necessary.
    """
    if len(name) > max_length:
        return name[:max_length]
    return name


def _truncate_docstring(docstring: str | None, max_length: int = 10000) -> str | None:
    """Truncate an oversized docstring.

    Args:
        docstring: Raw docstring text, or None.
        max_length: Maximum allowed length.

    Returns:
        Docstring truncated to max_length if necessary, or None.
    """
    if docstring and len(docstring) > max_length:
        return docstring[:max_length]
    return docstring


def _extract_symbol(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    parent_symbol: Symbol | None,
    scope_parts: list[str],
    decorator_node: object = None,
) -> Symbol | None:
    """Extract a Symbol from an AST node.

    Args:
        node: Tree-sitter AST node representing a symbol.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        parent_symbol: Enclosing symbol, or None at top level.
        scope_parts: Ancestor symbol names forming the qualified name prefix.
        decorator_node: Parent decorated_definition node, if applicable.

    Returns:
        Extracted Symbol object, or None if extraction fails.
    """
    kind = spec.symbol_node_types[node.type]

    name = extract_name(node, spec, source_bytes)
    if not name:
        return None

    name = _truncate_name(name)

    qualified_name = ".".join([*scope_parts, name]) if scope_parts else name

    signature = build_signature(node, spec, source_bytes)
    docstring = _truncate_docstring(extract_docstring(node, spec, source_bytes, language))

    decorators = extract_decorators(node, spec, source_bytes, decorator_node)

    start = node.start_byte
    end = node.end_byte
    if decorator_node is not None:
        start = decorator_node.start_byte
    symbol_bytes = source_bytes[start:end]
    content_hash = compute_content_hash(symbol_bytes)

    summary = heuristic_summary(docstring, signature, name)

    source_text = symbol_bytes.decode("utf-8", errors="replace")
    metrics = compute_complexity(source_text, language)

    sym = Symbol(
        symbol_id=make_symbol_id(filename, qualified_name, kind),
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=language,
        signature=signature,
        docstring=docstring,
        summary=summary,
        decorators=decorators,
        keywords=extract_keywords(name, docstring, decorators),
        parent_symbol_id=parent_symbol.symbol_id if parent_symbol else None,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        byte_offset=start,
        byte_length=end - start,
        content_hash=content_hash,
        cyclomatic=metrics["cyclomatic"],
        max_nesting=metrics["max_nesting"],
        param_count=metrics["param_count"],
    )
    return sym
