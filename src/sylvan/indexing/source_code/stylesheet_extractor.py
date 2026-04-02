"""Extra symbol extraction for SCSS, LESS, and Stylus.

Tree-sitter grammars for CSS-family languages miss variables, nested &
selectors, and preprocessor imports. These functions supplement the
tree-sitter pass with regex-based variable/import extraction and AST
walking for nested selector expansion.
"""

from __future__ import annotations

import hashlib
import re

from sylvan.database.validation import Symbol, make_symbol_id
from sylvan.indexing.source_code.symbol_enrichment import extract_keywords, heuristic_summary


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_number(content: str, pos: int) -> int:
    return content[:pos].count("\n") + 1


def _existing_names(symbols: list[Symbol]) -> set[str]:
    return {s.name for s in symbols}


_SCSS_VAR_RE = re.compile(
    r"^\s*(\$[\w-]+)\s*:\s*(.+?)\s*(?:!default\s*)?;",
    re.MULTILINE,
)

_SCSS_USE_RE = re.compile(
    r'^\s*@use\s+["\']([^"\']+)["\']\s*(?:as\s+([\w*]+))?\s*;',
    re.MULTILINE,
)

_SCSS_FORWARD_RE = re.compile(
    r'^\s*@forward\s+["\']([^"\']+)["\']\s*(?:(?:hide|show)\s+[^;]+)?\s*;',
    re.MULTILINE,
)

_SCSS_IMPORT_RE = re.compile(
    r'^\s*@import\s+["\']([^"\']+)["\']\s*;',
    re.MULTILINE,
)

_LESS_VAR_RE = re.compile(
    r"^\s*(@[\w-]+)\s*:\s*(.+?)\s*;",
    re.MULTILINE,
)

_LESS_IMPORT_RE = re.compile(
    r'^\s*@import\s+(?:\([^)]*\)\s*)?["\']([^"\']+)["\']\s*;',
    re.MULTILINE,
)

_STYLUS_VAR_RE = re.compile(
    r"^([\w-]+)\s*=\s*(.+)$",
    re.MULTILINE,
)

_STYLUS_FUNC_RE = re.compile(
    r"^([\w-]+)\(([^)]*)\)\s*$",
    re.MULTILINE,
)

_STYLUS_IMPORT_RE = re.compile(
    r'^\s*@(?:import|require)\s+["\']([^"\']+)["\']\s*$',
    re.MULTILINE,
)

_STYLUS_KEYWORDS = frozenset(
    {
        "if",
        "else",
        "for",
        "in",
        "return",
        "unless",
        "true",
        "false",
        "null",
        "not",
        "and",
        "or",
        "is",
        "isnt",
        "inherit",
        "initial",
        "unset",
        "none",
        "auto",
        "normal",
        "block",
        "inline",
        "flex",
        "grid",
        "absolute",
        "relative",
        "fixed",
        "sticky",
        "hidden",
        "visible",
        "solid",
        "dashed",
        "dotted",
        "transparent",
    }
)


def _make_constant_symbol(
    name: str,
    signature: str,
    filename: str,
    language: str,
    content: str,
    match_start: int,
    match_end: int,
) -> Symbol:
    line_start = _line_number(content, match_start)
    line_end = _line_number(content, match_end)
    source_text = content[match_start:match_end]
    summary = heuristic_summary(None, signature, name)
    return Symbol(
        symbol_id=make_symbol_id(filename, name, "constant"),
        name=name,
        qualified_name=name,
        kind="constant",
        language=language,
        signature=signature,
        summary=summary,
        keywords=extract_keywords(name, None, []),
        line_start=line_start,
        line_end=line_end,
        byte_offset=match_start,
        byte_length=len(source_text.encode("utf-8")),
        content_hash=_content_hash(source_text),
    )


def _expand_nested_selectors(
    node: object,
    source_bytes: bytes,
    parent_selector: str,
) -> list[tuple[str, object]]:
    """Walk AST collecting expanded selectors from & references."""
    results: list[tuple[str, object]] = []
    for child in node.children:
        if child.type == "rule_set":
            sel_node = child.child_by_field_name("selectors")
            if sel_node is None:
                for c in child.children:
                    if c.type in ("selectors", "class_selector", "id_selector", "nesting_selector"):
                        sel_node = c
                        break
            if sel_node is not None:
                raw = source_bytes[sel_node.start_byte : sel_node.end_byte].decode("utf-8", errors="replace").strip()
                if "&" in raw:
                    expanded = raw.replace("&", parent_selector)
                    results.append((expanded, child))
                    block = child.child_by_field_name("block")
                    if block is None:
                        for c in child.children:
                            if c.type == "block":
                                block = c
                                break
                    if block is not None:
                        results.extend(_expand_nested_selectors(block, source_bytes, expanded))
                else:
                    block = child.child_by_field_name("block")
                    if block is None:
                        for c in child.children:
                            if c.type == "block":
                                block = c
                                break
                    if block is not None:
                        results.extend(_expand_nested_selectors(block, source_bytes, parent_selector))
        elif child.type == "block":
            results.extend(_expand_nested_selectors(child, source_bytes, parent_selector))
    return results


def _extract_nested_selectors_from_tree(
    tree: object,
    source_bytes: bytes,
    filename: str,
    language: str,
    existing: set[str],
) -> list[Symbol]:
    """Walk the full AST looking for rule_sets with nested & selectors."""
    symbols: list[Symbol] = []

    def _walk(node: object) -> None:
        if node.type == "rule_set":
            sel_node = node.child_by_field_name("selectors")
            if sel_node is None:
                for c in node.children:
                    if c.type in ("selectors", "class_selector", "id_selector"):
                        sel_node = c
                        break
            if sel_node is not None:
                parent_sel = (
                    source_bytes[sel_node.start_byte : sel_node.end_byte].decode("utf-8", errors="replace").strip()
                )
                if "&" not in parent_sel:
                    block = node.child_by_field_name("block")
                    if block is None:
                        for c in node.children:
                            if c.type == "block":
                                block = c
                                break
                    if block is not None:
                        nested = _expand_nested_selectors(block, source_bytes, parent_sel)
                        for expanded_name, child_node in nested:
                            if expanded_name in existing:
                                continue
                            existing.add(expanded_name)
                            line_start = child_node.start_point[0] + 1
                            line_end = child_node.end_point[0] + 1
                            source_text = source_bytes[child_node.start_byte : child_node.end_byte]
                            summary = heuristic_summary(None, expanded_name, expanded_name)
                            sym = Symbol(
                                symbol_id=make_symbol_id(filename, expanded_name, "class"),
                                name=expanded_name,
                                qualified_name=expanded_name,
                                kind="class",
                                language=language,
                                signature=expanded_name,
                                summary=summary,
                                keywords=extract_keywords(expanded_name, None, []),
                                line_start=line_start,
                                line_end=line_end,
                                byte_offset=child_node.start_byte,
                                byte_length=len(source_text),
                                content_hash=_content_hash(source_text.decode("utf-8", errors="replace")),
                            )
                            symbols.append(sym)
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return symbols


def extract_scss_extras(
    content: str,
    filename: str,
    existing_symbols: list[Symbol],
    tree: object | None = None,
) -> tuple[list[Symbol], list[dict]]:
    """Extract SCSS variables, nested selectors, and imports.

    Args:
        content: File content.
        filename: Relative file path.
        existing_symbols: Symbols already found by tree-sitter.
        tree: Parsed tree-sitter tree (for nested selector expansion).

    Returns:
        Tuple of (additional symbols, imports).
    """
    symbols: list[Symbol] = []
    imports: list[dict] = []
    existing = _existing_names(existing_symbols)

    for m in _SCSS_VAR_RE.finditer(content):
        raw_name = m.group(1)
        value = m.group(2)
        name = raw_name.lstrip("$")
        if name in existing:
            continue
        existing.add(name)
        sig = f"{raw_name}: {value}"
        symbols.append(_make_constant_symbol(name, sig, filename, "scss", content, m.start(), m.end()))

    for m in _SCSS_USE_RE.finditer(content):
        specifier = m.group(1)
        alias = m.group(2)
        names = [alias] if alias and alias != "*" else []
        imports.append({"specifier": specifier, "names": names})

    for m in _SCSS_FORWARD_RE.finditer(content):
        imports.append({"specifier": m.group(1), "names": []})

    for m in _SCSS_IMPORT_RE.finditer(content):
        imports.append({"specifier": m.group(1), "names": []})

    if tree is not None:
        source_bytes = content.encode("utf-8")
        nested = _extract_nested_selectors_from_tree(
            tree,
            source_bytes,
            filename,
            "scss",
            existing,
        )
        symbols.extend(nested)

    return symbols, imports


def extract_less_extras(
    content: str,
    filename: str,
    existing_symbols: list[Symbol],
    tree: object | None = None,
) -> tuple[list[Symbol], list[dict]]:
    """Extract LESS variables, mixin-as-rule-set patterns, and imports.

    Args:
        content: File content.
        filename: Relative file path.
        existing_symbols: Symbols already found by tree-sitter.
        tree: Parsed tree-sitter tree (for mixin detection).

    Returns:
        Tuple of (additional symbols, imports).
    """
    symbols: list[Symbol] = []
    imports: list[dict] = []
    existing = _existing_names(existing_symbols)

    for m in _LESS_VAR_RE.finditer(content):
        raw_name = m.group(1)
        value = m.group(2)
        name = raw_name.lstrip("@")
        if name in existing:
            continue
        existing.add(name)
        sig = f"{raw_name}: {value}"
        symbols.append(_make_constant_symbol(name, sig, filename, "less", content, m.start(), m.end()))

    if tree is not None:
        source_bytes = content.encode("utf-8")
        _extract_less_mixins(tree.root_node, source_bytes, filename, existing, symbols)

    for m in _LESS_IMPORT_RE.finditer(content):
        imports.append({"specifier": m.group(1), "names": []})

    return symbols, imports


def _extract_less_mixins(
    node: object,
    source_bytes: bytes,
    filename: str,
    existing: set[str],
    symbols: list[Symbol],
) -> None:
    """Detect LESS mixin definitions (rule_sets with parameters in selectors).

    The CSS tree-sitter parser puts LESS mixin params like ``(@radius)``
    into an ERROR node adjacent to the selectors node. We check for that
    pattern: selectors followed by an ERROR node containing parens.
    """
    if node.type == "rule_set":
        sel_node = None
        error_node = None
        for c in node.children:
            if c.type in ("selectors",):
                sel_node = c
            elif c.type == "ERROR" and sel_node is not None:
                error_node = c
                break
            elif c.type == "block":
                break

        has_params = False
        if sel_node is not None:
            sel_text = source_bytes[sel_node.start_byte : sel_node.end_byte].decode("utf-8", errors="replace").strip()
            if "(" in sel_text and ")" in sel_text:
                has_params = True
                raw = sel_text
            elif error_node is not None:
                err_text = (
                    source_bytes[error_node.start_byte : error_node.end_byte].decode("utf-8", errors="replace").strip()
                )
                if err_text.startswith("(") and ")" in err_text:
                    has_params = True
                    raw = sel_text + err_text

            if has_params:
                name = raw.split("(")[0].lstrip(".#").strip()
                if name and name not in existing:
                    existing.add(name)
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1
                    source_text = source_bytes[node.start_byte : node.end_byte]
                    sig = raw.split("{")[0].strip() if "{" in raw else raw
                    summary = heuristic_summary(None, sig, name)
                    sym = Symbol(
                        symbol_id=make_symbol_id(filename, name, "function"),
                        name=name,
                        qualified_name=name,
                        kind="function",
                        language="less",
                        signature=sig,
                        summary=summary,
                        keywords=extract_keywords(name, None, []),
                        line_start=line_start,
                        line_end=line_end,
                        byte_offset=node.start_byte,
                        byte_length=len(source_text),
                        content_hash=_content_hash(source_text.decode("utf-8", errors="replace")),
                    )
                    symbols.append(sym)

    for child in node.children:
        _extract_less_mixins(child, source_bytes, filename, existing, symbols)


def extract_stylus_extras(
    content: str,
    filename: str,
    existing_symbols: list[Symbol],
) -> tuple[list[Symbol], list[dict]]:
    """Extract Stylus variables, functions, and imports.

    Args:
        content: File content.
        filename: Relative file path.
        existing_symbols: Symbols already found by tree-sitter.

    Returns:
        Tuple of (additional symbols, imports).
    """
    symbols: list[Symbol] = []
    imports: list[dict] = []
    existing = _existing_names(existing_symbols)

    for m in _STYLUS_FUNC_RE.finditer(content):
        name = m.group(1)
        params = m.group(2)
        if name in existing or name in _STYLUS_KEYWORDS:
            continue
        if name.startswith(("-", ".", "#", "@")):
            continue
        existing.add(name)
        sig = f"{name}({params})"
        line = _line_number(content, m.start())
        summary = heuristic_summary(None, sig, name)
        sym = Symbol(
            symbol_id=make_symbol_id(filename, name, "function"),
            name=name,
            qualified_name=name,
            kind="function",
            language="stylus",
            signature=sig,
            summary=summary,
            keywords=extract_keywords(name, None, []),
            line_start=line,
            line_end=line,
            byte_offset=m.start(),
            byte_length=len(m.group(0).encode("utf-8")),
            content_hash=_content_hash(m.group(0)),
        )
        symbols.append(sym)

    for m in _STYLUS_VAR_RE.finditer(content):
        name = m.group(1)
        value = m.group(2).strip()
        if name in existing or name in _STYLUS_KEYWORDS:
            continue
        if name.startswith(("-", ".", "#", "@")):
            continue
        if "(" in name or "{" in name:
            continue
        existing.add(name)
        sig = f"{name} = {value}"
        symbols.append(_make_constant_symbol(name, sig, filename, "stylus", content, m.start(), m.end()))

    for m in _STYLUS_IMPORT_RE.finditer(content):
        imports.append({"specifier": m.group(1), "names": []})

    return symbols, imports
