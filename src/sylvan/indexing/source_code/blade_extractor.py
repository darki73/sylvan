"""Blade template extractor - regex-based symbol and import extraction.

Blade is Laravel's template engine. Files use the ``.blade.php`` extension
and contain HTML mixed with Blade directives (``@extends``, ``@section``,
``{{ }}`` expressions, etc.). Tree-sitter cannot parse Blade syntax directly,
so this module uses regex for Blade directives and delegates ``@php`` blocks
to the PHP tree-sitter parser for full symbol extraction.
"""

from __future__ import annotations

import re

from sylvan.database.validation import Symbol

# ── Symbol patterns ─────────────────────────────────────────────────

_SECTION_RE = re.compile(r"@section\s*\(\s*['\"]([^'\"]+)['\"]")
_YIELD_RE = re.compile(r"@yield\s*\(\s*['\"]([^'\"]+)['\"]")
_PROPS_RE = re.compile(r"@props\s*\(\s*\[(.*?)\]\s*\)", re.DOTALL)
_AWARE_RE = re.compile(r"@aware\s*\(\s*\[(.*?)\]\s*\)", re.DOTALL)
_SLOT_RE = re.compile(r"@slot\s*\(\s*['\"]([^'\"]+)['\"]")
_PUSH_RE = re.compile(r"@(?:push|pushOnce)\s*\(\s*['\"]([^'\"]+)['\"]")
# @pushIf($cond, 'stack') - stack name is the 2nd arg
_PUSH_IF_RE = re.compile(r"@pushIf\s*\([^,]+,\s*['\"]([^'\"]+)['\"]")

# ── Import patterns ─────────────────────────────────────────────────

_EXTENDS_RE = re.compile(r"@extends\s*\(\s*['\"]([^'\"]+)['\"]")
_INCLUDE_RE = re.compile(r"@include\s*\(\s*['\"]([^'\"]+)['\"]")
_INCLUDE_IF_RE = re.compile(r"@includeIf\s*\(\s*['\"]([^'\"]+)['\"]")
_INCLUDE_COND_RE = re.compile(r"@include(?:When|Unless)\s*\([^,]+,\s*['\"]([^'\"]+)['\"]")
_INCLUDE_FIRST_RE = re.compile(r"@includeFirst\s*\(\s*\[(.*?)\]", re.DOTALL)
_COMPONENT_RE = re.compile(r"@component\s*\(\s*['\"]([^'\"]+)['\"]")
_LIVEWIRE_DIRECTIVE_RE = re.compile(r"@livewire\s*\(\s*['\"]([^'\"]+)['\"]")
_X_COMPONENT_RE = re.compile(r"<x-([\w.:/-]+)")
_LIVEWIRE_TAG_RE = re.compile(r"<livewire:([\w.:/-]+)")
_EACH_RE = re.compile(r"@each\s*\(\s*['\"]([^'\"]+)['\"]")
# Laravel 11+ @use directive: @use('App\Models\User')
_BLADE_USE_RE = re.compile(r"@use\s*\(\s*['\"]([^'\"]+)['\"]")

# ── PHP extraction ──────────────────────────────────────────────────

_PHP_BLOCK_RE = re.compile(r"@php\b(.*?)@endphp", re.DOTALL)
_PHP_USE_RE = re.compile(
    r"^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;",
    re.MULTILINE,
)
_QUOTED_STRING_RE = re.compile(r"['\"]([^'\"]+)['\"]")
_QUOTED_RE = re.compile(r"['\"](\w+)['\"]")


def _extract_prop_names(array_body: str) -> list[str]:
    """Extract prop names from a PHP array body.

    Handles both standalone keys (``'name'``) and keyed entries
    (``'name' => default``). Ignores string values after ``=>``.

    Args:
        array_body: Content between the ``[`` and ``]`` of ``@props([...])``.

    Returns:
        List of prop name strings.
    """
    names: list[str] = []
    depth = 0
    current = ""
    for ch in array_body:
        if ch in "([{":
            depth += 1
            current += ch
        elif ch in ")]}":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            name = _prop_name_from_entry(current)
            if name:
                names.append(name)
            current = ""
        else:
            current += ch
    name = _prop_name_from_entry(current)
    if name:
        names.append(name)
    return names


def _prop_name_from_entry(entry: str) -> str | None:
    """Extract the prop name from a single array entry.

    For ``'name' => default``, returns ``name``.
    For standalone ``'name'``, returns ``name``.
    """
    entry = entry.strip()
    if not entry:
        return None
    if "=>" in entry:
        key_part = entry.split("=>", 1)[0]
    else:
        key_part = entry
    m = _QUOTED_RE.search(key_part)
    return m.group(1) if m else None


def _line_number(content: str, pos: int) -> int:
    """Return the 1-based line number for a character position."""
    return content.count("\n", 0, pos) + 1


def _make_symbol(
    filename: str,
    content: str,
    m: re.Match,
    name: str,
    kind: str,
    qualified_name: str,
    signature: str,
) -> Symbol:
    """Build a Symbol from a regex match."""
    line = _line_number(content, m.start())
    return Symbol(
        symbol_id=f"{filename}::{qualified_name}#{kind}",
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language="blade",
        signature=signature,
        line_start=line,
        line_end=line,
        byte_offset=m.start(),
        byte_length=m.end() - m.start(),
    )


def _extract_php_symbols(content: str, filename: str) -> list[Symbol]:
    """Extract PHP symbols from @php blocks using the PHP tree-sitter parser.

    Parses each ``@php...@endphp`` block as PHP and adjusts byte offsets
    back to the original Blade file.

    Args:
        content: Full Blade file content.
        filename: Relative file path.

    Returns:
        List of Symbol instances from PHP code blocks.
    """
    symbols: list[Symbol] = []
    for block_m in _PHP_BLOCK_RE.finditer(content):
        php_code = block_m.group(1)
        if not php_code.strip():
            continue

        # Skip blocks that are just use statements (already handled as imports)
        stripped = "\n".join(
            line for line in php_code.splitlines() if line.strip() and not re.match(r"^\s*use\s+", line)
        )
        if not stripped.strip():
            continue

        # Wrap in <?php tags for the PHP tree-sitter parser
        wrapped = f"<?php\n{php_code}\n?>"
        prefix_len = len("<?php\n")
        block_byte_offset = len(content[: block_m.start(1)].encode("utf-8"))

        try:
            from sylvan.indexing.source_code.extractor import parse_file

            php_symbols = parse_file(wrapped, filename, "php")
            for sym in php_symbols:
                sym.language = "blade"
                # Adjust byte offset: subtract the <?php\n prefix, add block offset
                sym.byte_offset = sym.byte_offset - prefix_len + block_byte_offset
                # Adjust line numbers
                block_start_line = _line_number(content, block_m.start(1))
                if sym.line_start is not None:
                    sym.line_start = sym.line_start - 2 + block_start_line
                if sym.line_end is not None:
                    sym.line_end = sym.line_end - 2 + block_start_line
                symbols.append(sym)
        except Exception as exc:
            from sylvan.logging import get_logger

            get_logger(__name__).debug("blade_php_block_parse_failed", error=str(exc))

    return symbols


def extract_blade_symbols(content: str, filename: str) -> list[Symbol]:
    """Extract symbols from a Blade template.

    Extracts:
    - ``@section`` definitions (layout slots filled by child views)
    - ``@yield`` placeholders (layout slots defined by parent layouts)
    - ``@slot`` definitions (component slot overrides)
    - ``@props`` declarations (component public API)
    - ``@aware`` declarations (inherited props from parent components)
    - ``@push``/``@pushOnce``/``@pushIf`` stack contributions
    - PHP symbols from ``@php`` blocks (functions, classes, constants)

    Args:
        content: Blade file content.
        filename: Relative file path.

    Returns:
        List of Symbol dataclass instances.
    """
    symbols: list[Symbol] = []

    for m in _SECTION_RE.finditer(content):
        name = m.group(1)
        symbols.append(
            _make_symbol(
                filename,
                content,
                m,
                name,
                "function",
                f"@section('{name}')",
                f"@section('{name}')",
            )
        )

    for m in _YIELD_RE.finditer(content):
        name = m.group(1)
        symbols.append(
            _make_symbol(
                filename,
                content,
                m,
                name,
                "function",
                f"@yield('{name}')",
                f"@yield('{name}')",
            )
        )

    for m in _SLOT_RE.finditer(content):
        name = m.group(1)
        symbols.append(
            _make_symbol(
                filename,
                content,
                m,
                name,
                "function",
                f"@slot('{name}')",
                f"@slot('{name}')",
            )
        )

    for m in _PUSH_RE.finditer(content):
        name = m.group(1)
        symbols.append(
            _make_symbol(
                filename,
                content,
                m,
                name,
                "function",
                f"@push('{name}')",
                f"@push('{name}')",
            )
        )

    for m in _PUSH_IF_RE.finditer(content):
        name = m.group(1)
        symbols.append(
            _make_symbol(
                filename,
                content,
                m,
                name,
                "function",
                f"@push('{name}')",
                f"@push('{name}')",
            )
        )

    for m in _PROPS_RE.finditer(content):
        props_line = _line_number(content, m.start())
        for prop_name in _extract_prop_names(m.group(1)):
            symbols.append(
                Symbol(
                    symbol_id=f"{filename}::@props.{prop_name}#constant",
                    name=prop_name,
                    qualified_name=f"@props.{prop_name}",
                    kind="constant",
                    language="blade",
                    signature=f"@props('{prop_name}')",
                    line_start=props_line,
                    line_end=props_line,
                    byte_offset=m.start(),
                    byte_length=m.end() - m.start(),
                )
            )

    for m in _AWARE_RE.finditer(content):
        aware_line = _line_number(content, m.start())
        for prop_name in _extract_prop_names(m.group(1)):
            symbols.append(
                Symbol(
                    symbol_id=f"{filename}::@aware.{prop_name}#constant",
                    name=prop_name,
                    qualified_name=f"@aware.{prop_name}",
                    kind="constant",
                    language="blade",
                    signature=f"@aware('{prop_name}')",
                    line_start=aware_line,
                    line_end=aware_line,
                    byte_offset=m.start(),
                    byte_length=m.end() - m.start(),
                )
            )

    # Extract real PHP symbols from @php blocks
    symbols.extend(_extract_php_symbols(content, filename))

    return symbols


def extract_blade_imports(content: str) -> list[dict]:
    """Extract template references from a Blade file.

    Recognizes:
    - ``@extends``, ``@include`` variants, ``@component``, ``@each``
    - ``@livewire`` directive and ``<livewire:...>`` tags
    - ``<x-...>`` anonymous component tags
    - ``@use`` directive (Laravel 11+)
    - PHP ``use`` statements inside ``@php`` blocks
    - Namespaced views (``mail::message``, ``vendor::view``)

    Args:
        content: Blade file content.

    Returns:
        List of import dicts with ``specifier`` and ``names`` keys.
    """
    seen: set[str] = set()
    imports: list[dict] = []

    def _add(specifier: str) -> None:
        if specifier and specifier not in seen:
            seen.add(specifier)
            imports.append({"specifier": specifier, "names": []})

    for m in _EXTENDS_RE.finditer(content):
        _add(m.group(1))

    for m in _INCLUDE_RE.finditer(content):
        _add(m.group(1))

    for m in _INCLUDE_IF_RE.finditer(content):
        _add(m.group(1))

    for m in _INCLUDE_COND_RE.finditer(content):
        _add(m.group(1))

    for m in _INCLUDE_FIRST_RE.finditer(content):
        for sm in _QUOTED_STRING_RE.finditer(m.group(1)):
            _add(sm.group(1))

    for m in _COMPONENT_RE.finditer(content):
        _add(m.group(1))

    for m in _LIVEWIRE_DIRECTIVE_RE.finditer(content):
        _add(f"livewire.{m.group(1)}")

    for m in _X_COMPONENT_RE.finditer(content):
        tag = m.group(1).replace("/", ".")
        _add(f"components.{tag}")

    for m in _LIVEWIRE_TAG_RE.finditer(content):
        tag = m.group(1).replace("/", ".")
        _add(f"livewire.{tag}")

    for m in _EACH_RE.finditer(content):
        _add(m.group(1))

    # Laravel 11+ @use directive
    for m in _BLADE_USE_RE.finditer(content):
        _add(m.group(1))

    # PHP use statements from @php blocks
    for block in _PHP_BLOCK_RE.finditer(content):
        for use_m in _PHP_USE_RE.finditer(block.group(1)):
            _add(use_m.group(1))

    return imports
