"""Extract call sites from parsed source code using tree-sitter ASTs.

Walks each symbol's AST subtree to find function/method calls, producing
CallSite records that link caller symbol IDs to callee names. These are
later resolved to target symbol IDs by build_reference_graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter_language_pack import get_parser

from sylvan.indexing.source_code.language_specs import get_spec


@dataclass(slots=True)
class CallSite:
    """A function/method call found inside a symbol body.

    Attributes:
        caller_symbol_id: Symbol ID of the enclosing function/method.
        callee_name: Name being called (e.g., "foo", "self.bar", "Module.baz").
        line: 1-based line number of the call.
    """

    caller_symbol_id: str
    callee_name: str
    line: int


def extract_call_sites(
    symbols: list,
    content_str: str,
    language: str,
    repo_name: str,
) -> list[CallSite]:
    """Extract call sites from source code using tree-sitter.

    For each symbol in the list, finds its corresponding AST node by byte
    range and walks the subtree looking for call expressions. Also captures
    module-level calls (outside any symbol).

    Args:
        symbols: List of Symbol dataclass objects (from parse_file).
        content_str: Source code text.
        language: Language identifier (e.g., "python").
        repo_name: Repository name for symbol ID prefixing.

    Returns:
        List of CallSite records found in the source.
    """
    if language != "python":
        return []

    spec = get_spec(language)
    if spec is None:
        return []

    source_bytes = content_str.encode("utf-8")

    try:
        parser = get_parser(spec.ts_language)
    except Exception:
        return []

    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return []

    sym_ranges: list[tuple[int, int, str]] = []
    for sym in symbols:
        if sym.kind in ("function", "method"):
            sym_ranges.append((sym.byte_offset, sym.byte_offset + sym.byte_length, sym.symbol_id))

    sym_ranges.sort(key=lambda r: r[0])

    calls: list[CallSite] = []

    for start, end, symbol_id in sym_ranges:
        node = _find_node_at_range(tree.root_node, start, end)
        if node is None:
            continue
        _extract_calls_from_subtree(node, source_bytes, calls, symbol_id)

    prefix = f"{repo_name}::"
    _extract_module_level_calls(
        tree.root_node,
        source_bytes,
        calls,
        sym_ranges,
        prefix,
    )

    return calls


def _find_node_at_range(root, start: int, end: int):
    """Find the AST node that matches a given byte range.

    Walks children to find the node whose start/end bytes match the
    target range. Returns None if no exact match is found.

    Args:
        root: Root tree-sitter node to search from.
        start: Start byte offset.
        end: End byte offset.

    Returns:
        The matching tree-sitter node, or None.
    """
    if root.start_byte == start and root.end_byte == end:
        return root
    for child in root.children:
        if child.start_byte <= start and child.end_byte >= end:
            found = _find_node_at_range(child, start, end)
            if found is not None:
                return found
    return None


def _extract_calls_from_subtree(
    node,
    source_bytes: bytes,
    calls: list[CallSite],
    symbol_id: str,
) -> None:
    """Walk an AST subtree and extract call expressions.

    Skips nested function/class definitions since they belong to
    different symbols.

    Args:
        node: Tree-sitter AST node to walk.
        source_bytes: Encoded source bytes.
        calls: Accumulator list for discovered call sites.
        symbol_id: Symbol ID of the enclosing function/method.
    """
    if node.type == "call":
        callee = _resolve_callee(node)
        if callee:
            calls.append(
                CallSite(
                    caller_symbol_id=symbol_id,
                    callee_name=callee,
                    line=node.start_point[0] + 1,
                )
            )

    if node.type in ("function_definition", "class_definition"):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    _extract_calls_from_subtree(child, source_bytes, calls, symbol_id)
            return
        if node.type == "class_definition":
            return

    for child in node.children:
        _extract_calls_from_subtree(child, source_bytes, calls, symbol_id)


def _extract_module_level_calls(
    root,
    source_bytes: bytes,
    calls: list[CallSite],
    sym_ranges: list[tuple[int, int, str]],
    prefix: str,
) -> None:
    """Extract calls at module level (outside any symbol body).

    Args:
        root: Root AST node.
        source_bytes: Encoded source bytes.
        calls: Accumulator list for discovered call sites.
        sym_ranges: Sorted list of (start, end, symbol_id) for known symbols.
        prefix: Repo prefix for the module-level symbol ID.
    """
    module_id = "__module__"

    for child in root.children:
        if child.type in ("function_definition", "class_definition", "decorated_definition"):
            continue

        _walk_for_calls(child, source_bytes, calls, module_id)


def _walk_for_calls(
    node,
    source_bytes: bytes,
    calls: list[CallSite],
    symbol_id: str,
) -> None:
    """Recursively walk nodes looking for call expressions.

    Args:
        node: Tree-sitter node.
        source_bytes: Encoded source bytes.
        calls: Accumulator list.
        symbol_id: Caller symbol ID to assign.
    """
    if node.type == "call":
        callee = _resolve_callee(node)
        if callee:
            calls.append(
                CallSite(
                    caller_symbol_id=symbol_id,
                    callee_name=callee,
                    line=node.start_point[0] + 1,
                )
            )

    if node.type in ("function_definition", "class_definition", "decorated_definition"):
        return

    for child in node.children:
        _walk_for_calls(child, source_bytes, calls, symbol_id)


def _resolve_callee(call_node) -> str | None:
    """Extract the callee name from a call expression node.

    Handles simple identifiers (foo), attribute access (self.bar,
    Module.baz), and chained calls (Repo.where(x).first() -> "first"
    with the chain root being "Repo.where").

    For chains like Repo.where(x).first(), the outermost call resolves
    to the leaf method ("first") while inner calls resolve to their
    own identifiers ("Repo.where"). This avoids producing duplicate
    references for the same chain.

    Args:
        call_node: A tree-sitter "call" node.

    Returns:
        The callee name string, or None for complex expressions.
    """
    func_node = call_node.child_by_field_name("function")
    if func_node is None:
        for child in call_node.children:
            if child.type != "argument_list":
                func_node = child
                break

    if func_node is None:
        return None

    if func_node.type == "identifier":
        return func_node.text.decode("utf-8")

    if func_node.type == "attribute":
        return _resolve_attribute_chain(func_node)

    return None


def _resolve_attribute_chain(attr_node) -> str | None:
    """Walk an attribute node to build a clean dotted name.

    For simple attributes (self.bar, Module.baz), returns the dotted name.
    For chained calls (Repo.where(x).first), the object is a call node -
    we skip through it to find the root identifier, producing just the
    leaf attribute name with its immediate object.

    Args:
        attr_node: A tree-sitter "attribute" node.

    Returns:
        A dotted name string like "self.bar" or "Repo.where", or None.
    """
    attr_name = attr_node.child_by_field_name("attribute")
    obj = attr_node.child_by_field_name("object")

    if attr_name is None or obj is None:
        return None

    name = attr_name.text.decode("utf-8")

    if obj.type == "identifier":
        return f"{obj.text.decode('utf-8')}.{name}"

    if obj.type == "attribute":
        parent = _resolve_attribute_chain(obj)
        if parent:
            return f"{parent}.{name}"
        return None

    if obj.type == "call":
        root = _find_chain_root(obj)
        if root:
            return f"{root}.{name}"
        return name

    return None


def _find_chain_root(node) -> str | None:
    """Walk down through chained calls to find the root identifier.

    For Repo.where(x).first().count(), walks down to find "Repo".

    Args:
        node: Any tree-sitter node in a call chain.

    Returns:
        The root identifier string, or None.
    """
    if node.type == "identifier":
        return node.text.decode("utf-8")

    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        if obj:
            return _find_chain_root(obj)

    if node.type == "call":
        func = node.child_by_field_name("function")
        if func:
            return _find_chain_root(func)

    return None
