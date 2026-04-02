"""JSON deep extraction - schema-aware symbol extraction from JSON files.

Handles package.json, tsconfig.json, and generic JSON with structural
extraction of keys, scripts, dependencies, compiler options, etc.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from sylvan.database.validation import Symbol, make_symbol_id

_KEY_PATTERN = re.compile(r'"([^"\\]+)"\s*:')


def _build_line_map(content: str) -> dict[str, list[int]]:
    """Build a mapping of JSON key names to their line numbers.

    Returns a dict where each key maps to a list of line numbers (1-based)
    where that key appears as a JSON object key.
    """
    line_map: dict[str, list[int]] = {}
    for lineno, line in enumerate(content.splitlines(), start=1):
        m = _KEY_PATTERN.search(line)
        if m:
            key = m.group(1)
            line_map.setdefault(key, []).append(lineno)
    return line_map


def _find_line(line_map: dict[str, list[int]], key: str) -> int:
    """Find the first line number for a key, defaulting to 1."""
    lines = line_map.get(key)
    return lines[0] if lines else 1


def _find_nested_line(
    content: str,
    line_map: dict[str, list[int]],
    parent_key: str,
    child_key: str,
) -> int:
    """Find the line of child_key within the section owned by parent_key.

    Searches for occurrences of child_key that appear after the parent_key line.
    Falls back to global lookup, then to 1.
    """
    parent_lines = line_map.get(parent_key)
    child_lines = line_map.get(child_key)
    if not child_lines:
        return 1
    if not parent_lines:
        return child_lines[0]
    parent_line = parent_lines[0]
    for cl in child_lines:
        if cl > parent_line:
            return cl
    return child_lines[0]


def _find_deep_line(
    content: str,
    line_map: dict[str, list[int]],
    *keys: str,
) -> int:
    """Find the line of the deepest key, scoped by ancestor keys."""
    if len(keys) < 2:
        return _find_line(line_map, keys[0]) if keys else 1
    parent = keys[-2]
    child = keys[-1]
    return _find_nested_line(content, line_map, parent, child)


def extract_json_symbols(content: str, filename: str) -> list[Symbol]:
    """Extract symbols from a JSON file."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, dict):
        return []

    basename = PurePosixPath(filename).name.lower()

    if basename == "package.json":
        return _extract_package_json(data, content, filename)
    if basename in ("tsconfig.json", "jsconfig.json"):
        return _extract_tsconfig(data, content, filename)
    return _extract_generic_json(data, content, filename)


def extract_json_imports(content: str, filename: str) -> list[dict]:
    """Extract import-like references from JSON files."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, dict):
        return []

    basename = PurePosixPath(filename).name.lower()
    imports: list[dict] = []

    if basename == "package.json":
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            deps = data.get(section, {})
            if isinstance(deps, dict):
                for pkg in deps:
                    imports.append({"specifier": pkg, "names": [pkg]})

    if basename in ("tsconfig.json", "jsconfig.json"):
        extends = data.get("extends")
        if isinstance(extends, str):
            imports.append({"specifier": extends, "names": ["extends"]})

        paths = _nested_get(data, "compilerOptions", "paths")
        if isinstance(paths, dict):
            for alias, targets in paths.items():
                if isinstance(targets, list):
                    for target in targets:
                        if isinstance(target, str):
                            imports.append({"specifier": target, "names": [alias]})

    return imports


def _extract_package_json(data: dict, content: str, filename: str) -> list[Symbol]:
    """Extract symbols from package.json."""
    symbols: list[Symbol] = []
    source_bytes = content.encode("utf-8")
    lm = _build_line_map(content)

    for field in ("name", "version", "description", "main", "module", "types"):
        value = data.get(field)
        if isinstance(value, str):
            symbols.append(
                _make(
                    filename=filename,
                    name=field,
                    kind="constant",
                    signature=f'"{value}"',
                    source_bytes=source_bytes,
                    line=_find_line(lm, field),
                )
            )

    scripts = data.get("scripts", {})
    if isinstance(scripts, dict):
        for script_name, command in scripts.items():
            symbols.append(
                _make(
                    filename=filename,
                    name=script_name,
                    qualified_name=f"scripts.{script_name}",
                    kind="function",
                    signature=f"{script_name}: {command}" if isinstance(command, str) else script_name,
                    source_bytes=source_bytes,
                    line=_find_nested_line(content, lm, "scripts", script_name),
                )
            )

    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            for pkg, ver in deps.items():
                symbols.append(
                    _make(
                        filename=filename,
                        name=pkg,
                        qualified_name=f"{section}.{pkg}",
                        kind="constant",
                        signature=f"{pkg}@{ver}" if isinstance(ver, str) else pkg,
                        source_bytes=source_bytes,
                        line=_find_nested_line(content, lm, section, pkg),
                    )
                )

    exports = data.get("exports", {})
    if isinstance(exports, dict):
        for entry, target in exports.items():
            sig = f"{entry}: {_value_signature(target)}"
            symbols.append(
                _make(
                    filename=filename,
                    name=entry,
                    qualified_name=f"exports.{entry}",
                    kind="constant",
                    signature=sig,
                    source_bytes=source_bytes,
                    line=_find_nested_line(content, lm, "exports", entry),
                )
            )

    engines = data.get("engines", {})
    if isinstance(engines, dict):
        for engine, constraint in engines.items():
            symbols.append(
                _make(
                    filename=filename,
                    name=engine,
                    qualified_name=f"engines.{engine}",
                    kind="type",
                    signature=f"{engine}: {constraint}" if isinstance(constraint, str) else engine,
                    source_bytes=source_bytes,
                    line=_find_nested_line(content, lm, "engines", engine),
                )
            )

    return symbols


def _extract_tsconfig(data: dict, content: str, filename: str) -> list[Symbol]:
    """Extract symbols from tsconfig.json / jsconfig.json."""
    symbols: list[Symbol] = []
    source_bytes = content.encode("utf-8")
    lm = _build_line_map(content)

    extends = data.get("extends")
    if isinstance(extends, str):
        symbols.append(
            _make(
                filename=filename,
                name="extends",
                kind="constant",
                signature=f'extends: "{extends}"',
                source_bytes=source_bytes,
                line=_find_line(lm, "extends"),
            )
        )

    compiler_opts = data.get("compilerOptions", {})
    if isinstance(compiler_opts, dict):
        for key, value in compiler_opts.items():
            if key == "paths" and isinstance(value, dict):
                for alias, targets in value.items():
                    sig = f"{alias} -> {targets}" if isinstance(targets, list) else alias
                    symbols.append(
                        _make(
                            filename=filename,
                            name=alias,
                            qualified_name=f"compilerOptions.paths.{alias}",
                            kind="constant",
                            signature=str(sig),
                            source_bytes=source_bytes,
                            line=_find_deep_line(content, lm, "paths", alias),
                        )
                    )
            else:
                sig = f"{key}: {json.dumps(value)}" if not isinstance(value, str) else f"{key}: {value}"
                symbols.append(
                    _make(
                        filename=filename,
                        name=key,
                        qualified_name=f"compilerOptions.{key}",
                        kind="constant",
                        signature=sig,
                        source_bytes=source_bytes,
                        line=_find_nested_line(content, lm, "compilerOptions", key),
                    )
                )

    for section in ("include", "exclude", "files"):
        value = data.get(section)
        if isinstance(value, list):
            symbols.append(
                _make(
                    filename=filename,
                    name=section,
                    kind="constant",
                    signature=f"{section}: {json.dumps(value)}",
                    source_bytes=source_bytes,
                    line=_find_line(lm, section),
                )
            )

    return symbols


def _extract_generic_json(data: dict, content: str, filename: str) -> list[Symbol]:
    """Extract symbols from generic JSON files."""
    symbols: list[Symbol] = []
    source_bytes = content.encode("utf-8")
    lm = _build_line_map(content)

    for key, value in data.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                sig = _value_signature(sub_value)
                symbols.append(
                    _make(
                        filename=filename,
                        name=sub_key,
                        qualified_name=f"{key}.{sub_key}",
                        kind="constant",
                        signature=f"{key}.{sub_key}: {sig}",
                        source_bytes=source_bytes,
                        line=_find_nested_line(content, lm, key, sub_key),
                    )
                )
        else:
            sig = _value_signature(value)
            symbols.append(
                _make(
                    filename=filename,
                    name=key,
                    kind="constant",
                    signature=f"{key}: {sig}",
                    source_bytes=source_bytes,
                    line=_find_line(lm, key),
                )
            )

    return symbols


def _value_signature(value: object) -> str:
    """Create a short signature string for a JSON value."""
    if isinstance(value, str):
        if len(value) > 60:
            return f'"{value[:57]}..."'
        return f'"{value}"'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)


def _make(
    *,
    filename: str,
    name: str,
    kind: str,
    signature: str,
    source_bytes: bytes,
    line: int = 1,
    qualified_name: str | None = None,
) -> Symbol:
    """Create a Symbol from JSON extraction."""
    qname = qualified_name or name
    return Symbol(
        symbol_id=make_symbol_id(filename, qname, kind),
        name=name,
        qualified_name=qname,
        kind=kind,
        language="json",
        signature=signature,
        docstring=None,
        summary=signature,
        decorators=[],
        keywords=[name],
        parent_symbol_id=None,
        line_start=line,
        line_end=line,
        byte_offset=0,
        byte_length=len(source_bytes),
        content_hash=None,
        cyclomatic=0,
        max_nesting=0,
        param_count=0,
    )


def _nested_get(data: dict, *keys: str) -> object:
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
