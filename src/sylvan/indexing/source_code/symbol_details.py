"""AST node detail extraction -- names, signatures, docstrings, decorators.

Each function takes a tree-sitter node and a LanguageSpec, returning the
extracted detail. These are pure functions with no side effects.
"""

from sylvan.indexing.source_code.language_specs import LanguageSpec


def extract_name(node: object, spec: LanguageSpec, source_bytes: bytes) -> str | None:
    """Extract the symbol name from an AST node.

    Args:
        node: Tree-sitter AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.

    Returns:
        Symbol name string, or None if extraction fails.
    """
    field_name = spec.name_fields.get(node.type)
    if not field_name:
        return None

    name_node = node.child_by_field_name(field_name)
    if name_node is None:
        return _scan_children_for_name(node, source_bytes)

    if name_node.type in ("function_declarator", "pointer_declarator", "reference_declarator"):
        return _extract_declarator_name(name_node, source_bytes)

    return source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")


def _scan_children_for_name(node: object, source_bytes: bytes) -> str | None:
    """Scan child nodes for an identifier when the field-based lookup fails.

    Args:
        node: Tree-sitter AST node to scan.
        source_bytes: Raw source file bytes.

    Returns:
        Identifier name string, or None if not found.
    """
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "field_identifier", "property_identifier"):
            return source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
        if child.type == "type_spec":
            inner_name = child.child_by_field_name("name")
            if inner_name:
                return source_bytes[inner_name.start_byte : inner_name.end_byte].decode("utf-8", errors="replace")
    return None


def _extract_declarator_name(node: object, source_bytes: bytes) -> str | None:
    """Recursively extract name from C/C++ declarator chains.

    Args:
        node: Tree-sitter declarator node.
        source_bytes: Raw source file bytes.

    Returns:
        Identifier name string, or None if not found.
    """
    for child in node.children:
        if child.type in ("identifier", "field_identifier", "type_identifier"):
            return source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
        if child.type in ("function_declarator", "pointer_declarator", "reference_declarator"):
            return _extract_declarator_name(child, source_bytes)
    return None


def build_signature(node: object, spec: LanguageSpec, source_bytes: bytes) -> str:
    """Build a signature string from an AST node.

    Takes the text from the node start to the body start (or end if no body).

    Args:
        node: Tree-sitter AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.

    Returns:
        Cleaned signature string.
    """
    body = node.child_by_field_name("body")
    if body is not None:
        sig_bytes = source_bytes[node.start_byte : body.start_byte]
    else:
        end = source_bytes.find(b"\n", node.start_byte)
        if end == -1:
            end = node.end_byte
        sig_bytes = source_bytes[node.start_byte : end]

    sig = sig_bytes.decode("utf-8", errors="replace").strip()
    sig = sig.rstrip(":{ \t\n\r")
    return sig


def extract_docstring(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    language: str,
) -> str | None:
    """Extract docstring/documentation comment for a symbol.

    Args:
        node: Tree-sitter AST node.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        language: Language identifier for comment style detection.

    Returns:
        Cleaned docstring text, or None if not found.
    """
    if spec.docstring_strategy == "next_sibling_string":
        return _extract_python_style_docstring(node, source_bytes)

    elif spec.docstring_strategy == "preceding_comment":
        return _extract_preceding_comment(node, source_bytes, language)

    return None


def _extract_python_style_docstring(node: object, source_bytes: bytes) -> str | None:
    """Extract a Python-style docstring from the first expression in the body.

    Args:
        node: Tree-sitter AST node with a body field.
        source_bytes: Raw source file bytes.

    Returns:
        Cleaned docstring text, or None if not found.
    """
    body = node.child_by_field_name("body")
    if body is not None and body.child_count > 0:
        first_stmt = body.children[0]
        target = first_stmt
        if first_stmt.type == "expression_statement" and first_stmt.child_count > 0:
            target = first_stmt.children[0]
        if target.type == "string":
            raw = source_bytes[target.start_byte : target.end_byte].decode("utf-8", errors="replace")
            return _clean_docstring(raw)
    return None


def _extract_preceding_comment(node: object, source_bytes: bytes, language: str) -> str | None:
    """Extract a C/Go/Rust/Java-style comment block preceding the declaration.

    Args:
        node: Tree-sitter AST node.
        source_bytes: Raw source file bytes.
        language: Language identifier for comment marker detection.

    Returns:
        Cleaned comment text, or None if no preceding comment found.
    """
    prev = node.prev_named_sibling
    if prev is not None and prev.type == "comment":
        parts: list[str] = []
        current = prev
        while current is not None and current.type == "comment":
            parts.append(source_bytes[current.start_byte : current.end_byte].decode("utf-8", errors="replace"))
            current = current.prev_named_sibling
        parts.reverse()
        return _clean_comment_block("\n".join(parts), language)
    return None


def _clean_docstring(raw: str) -> str:
    """Clean a Python-style docstring.

    Args:
        raw: Raw docstring including quote delimiters.

    Returns:
        Cleaned docstring with delimiters removed.
    """
    for q in ('"""', "'''", '"', "'"):
        if raw.startswith(q) and raw.endswith(q):
            raw = raw[len(q) : -len(q)]
            break
    return raw.strip()


def _clean_comment_block(text: str, language: str) -> str:
    """Clean a comment block (remove comment markers).

    Args:
        text: Raw comment text with markers.
        language: Language identifier (unused, reserved for future use).

    Returns:
        Cleaned comment text with markers stripped.
    """
    lines = text.split("\n")
    cleaned: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        for prefix in ("///", "//!", "//", "#", "/*", "*/", "*"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :]
                break
        cleaned.append(stripped.strip())
    return "\n".join(cleaned).strip()


def extract_decorators(
    node: object,
    spec: LanguageSpec,
    source_bytes: bytes,
    decorator_node: object = None,
) -> list[str]:
    """Extract decorator/annotation strings.

    Args:
        node: Tree-sitter AST node for the symbol.
        spec: Language extraction specification.
        source_bytes: Raw source file bytes.
        decorator_node: Parent decorated_definition node, if applicable.

    Returns:
        List of decorator/annotation text strings.
    """
    decorators: list[str] = []

    if decorator_node is not None:
        for child in decorator_node.children:
            if child.type in ("decorator", "annotation", "marker_annotation", "attribute_list"):
                text = source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace").strip()
                decorators.append(text)
    elif spec.decorator_node_type:
        prev = node.prev_named_sibling
        while prev is not None and prev.type == spec.decorator_node_type:
            text = source_bytes[prev.start_byte : prev.end_byte].decode("utf-8", errors="replace").strip()
            decorators.insert(0, text)
            prev = prev.prev_named_sibling

    return decorators
