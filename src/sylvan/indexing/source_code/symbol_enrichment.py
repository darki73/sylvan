"""Post-extraction symbol enrichment -- summaries, keywords, special cases.

Handles heuristic summary generation, keyword extraction, variable-assigned
function detection (JS/TS), Python constant detection, overload disambiguation,
and method classification.
"""

import hashlib
import re

from sylvan.database.validation import Symbol, make_symbol_id
from sylvan.indexing.source_code.language_specs import LanguageSpec
from sylvan.indexing.source_code.symbol_details import (
    build_signature,
    extract_docstring,
)


def _content_hash(source_bytes: bytes) -> str:
    """SHA-256 of raw source bytes -- local helper to avoid circular import with extractor.

    Args:
        source_bytes: Raw source code bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(source_bytes).hexdigest()


def heuristic_summary(
    docstring: str | None, signature: str, name: str,
) -> str:
    """Generate a one-line summary from available metadata.

    Args:
        docstring: Extracted docstring text, or None.
        signature: Symbol signature string.
        name: Symbol name.

    Returns:
        A short summary string (at most 120 characters).
    """
    if docstring:
        first_line = docstring.split("\n")[0].strip()
        if first_line:
            dot = first_line.find(".")
            if 0 < dot < 120:
                return first_line[: dot + 1]
            return first_line[:120]

    if signature:
        return signature[:120]

    return name


_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
"""Regex that inserts split points at camelCase boundaries."""

_SPLIT_RE = re.compile(r"[_\-./]")
"""Regex that splits on common identifier separators."""


def split_identifier(name: str) -> list[str]:
    """Split a camelCase or snake_case identifier into tokens.

    Args:
        name: Identifier string to split.

    Returns:
        List of lowercased tokens (minimum 2 characters each).
    """
    parts = _CAMEL_RE.sub("_", name)
    tokens = _SPLIT_RE.split(parts)
    return [t.lower() for t in tokens if len(t) >= 2]


def extract_keywords(
    name: str, docstring: str | None, decorators: list[str],
) -> list[str]:
    """Extract searchable keywords from symbol metadata.

    Args:
        name: Symbol name.
        docstring: Extracted docstring text, or None.
        decorators: List of decorator/annotation strings.

    Returns:
        Sorted list of unique keyword strings.
    """
    keywords = set(split_identifier(name))

    if docstring:
        first_line = docstring.split("\n")[0].lower()
        for word in re.findall(r"\b[a-z]{3,}\b", first_line):
            keywords.add(word)

    for dec in decorators:
        match = re.match(r"@?(\w+)", dec)
        if match:
            keywords.add(match.group(1).lower())

    return sorted(keywords)


def try_extract_variable_function(
    declarator_node: object,
    parent_node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
    parent_symbol: Symbol | None,
    scope_parts: list[str],
) -> None:
    """Try to extract a function from a variable assignment (arrow functions, etc.).

    Args:
        declarator_node: Variable declarator AST node.
        parent_node: Parent declaration AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        symbols: Accumulator list for extracted symbols.
        parent_symbol: Enclosing symbol, or None at top level.
        scope_parts: Ancestor symbol names forming the qualified name prefix.
    """
    name_node = declarator_node.child_by_field_name("name")
    value_node = declarator_node.child_by_field_name("value")

    if name_node is None or value_node is None:
        return

    if value_node.type not in ("arrow_function", "function_expression", "function"):
        return

    name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    qualified_name = ".".join([*scope_parts, name]) if scope_parts else name

    signature = build_signature(parent_node, spec, source_bytes)
    docstring = extract_docstring(parent_node, spec, source_bytes, language)
    start = parent_node.start_byte
    end = parent_node.end_byte
    content_hash = _content_hash(source_bytes[start:end])

    sym = Symbol(
        symbol_id=make_symbol_id(filename, qualified_name, "function"),
        name=name,
        qualified_name=qualified_name,
        kind="function",
        language=language,
        signature=signature,
        docstring=docstring,
        summary=heuristic_summary(docstring, signature, name),
        keywords=extract_keywords(name, docstring, []),
        parent_symbol_id=parent_symbol.symbol_id if parent_symbol else None,
        line_start=parent_node.start_point[0] + 1,
        line_end=parent_node.end_point[0] + 1,
        byte_offset=start,
        byte_length=end - start,
        content_hash=content_hash,
    )
    symbols.append(sym)


def _is_upper_case_constant(name: str) -> bool:
    """Return True if name is an UPPER_CASE constant identifier.

    Args:
        name: Identifier string to check.

    Returns:
        True if the name follows UPPER_CASE convention.
    """
    return name.isupper() or (name.upper() == name and "_" in name)


def try_extract_python_constant(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    filename: str,
    language: str,
    symbols: list[Symbol],
) -> None:
    """Try to extract an UPPER_CASE module-level constant (Python).

    Args:
        node: Expression statement or assignment AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        filename: Relative file path.
        language: Language identifier.
        symbols: Accumulator list for extracted symbols.
    """
    assignments: list = []
    if node.type == "assignment":
        assignments.append(node)
    else:
        for child in node.children:
            if child.type == "assignment":
                assignments.append(child)

    for assign in assignments:
        left = assign.child_by_field_name("left")
        if left is None:
            for child in assign.children:
                if child.type == "identifier":
                    left = child
                    break
        if left and left.type == "identifier":
            name = source_bytes[left.start_byte:left.end_byte].decode("utf-8", errors="replace")
            if _is_upper_case_constant(name):
                start = assign.start_byte
                end = assign.end_byte

                sig = source_bytes[start:end].decode("utf-8", errors="replace").strip()

                sym = Symbol(
                    symbol_id=make_symbol_id(filename, name, "constant"),
                    name=name,
                    qualified_name=name,
                    kind="constant",
                    language=language,
                    signature=sig,
                    summary=f"Constant: {name}",
                    keywords=extract_keywords(name, None, []),
                    line_start=assign.start_point[0] + 1,
                    line_end=assign.end_point[0] + 1,
                    byte_offset=start,
                    byte_length=end - start,
                    content_hash=_content_hash(source_bytes[start:end]),
                )
                symbols.append(sym)


def disambiguate_overloads(symbols: list[Symbol]) -> None:
    """Append ordinal suffix to duplicate symbol IDs.

    Args:
        symbols: Mutable list of symbols to disambiguate in place.
    """
    seen: dict[str, int] = {}
    for sym in symbols:
        if sym.symbol_id in seen:
            count = seen[sym.symbol_id]
            seen[sym.symbol_id] = count + 1
            sym.symbol_id = f"{sym.symbol_id}~{count}"
        else:
            seen[sym.symbol_id] = 1


def classify_methods(symbols: list[Symbol]) -> None:
    """Reclassify functions inside classes as methods.

    Args:
        symbols: Mutable list of symbols to reclassify in place.
    """
    parent_ids = {s.symbol_id for s in symbols if s.kind in ("class", "type")}
    for sym in symbols:
        if sym.kind == "function" and sym.parent_symbol_id in parent_ids:
            sym.kind = "method"
            base = sym.symbol_id.rsplit("#", 1)[0]
            sym.symbol_id = f"{base}#method"
