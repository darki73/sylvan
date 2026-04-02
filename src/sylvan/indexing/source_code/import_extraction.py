"""Per-language import extraction from source files."""

import re


def extract_imports(content: str, file_path: str, language: str) -> list[dict]:
    """Extract import statements from source code.

    Args:
        content: Source file content.
        file_path: Relative file path (unused, reserved for future use).
        language: Language identifier for selecting the correct extractor.

    Returns:
        List of dicts with "specifier" (str) and "names" (list[str]) keys.
    """
    extractors = {
        "python": _extract_python_imports,
        "javascript": _extract_js_imports,
        "typescript": _extract_js_imports,
        "tsx": _extract_js_imports,
        "go": _extract_go_imports,
        "rust": _extract_rust_imports,
        "java": _extract_java_imports,
        "kotlin": _extract_java_imports,
        "c": _extract_c_imports,
        "cpp": _extract_c_imports,
        "c_sharp": _extract_csharp_imports,
        "ruby": _extract_ruby_imports,
        "php": _extract_php_imports,
        "swift": _extract_swift_imports,
        "scss": _extract_scss_imports,
        "less": _extract_less_imports,
        "stylus": _extract_stylus_imports,
    }

    extractor = extractors.get(language)
    if extractor is None:
        return []

    try:
        return extractor(content)
    except Exception:
        return []


_PY_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)", re.MULTILINE)
"""Matches Python ``from X import Y`` statements."""

_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)
"""Matches Python ``import X`` statements."""


def _extract_python_imports(content: str) -> list[dict]:
    """Extract Python import statements.

    Args:
        content: Python source code.

    Returns:
        List of import dicts with specifier and names.
    """
    imports = []
    for m in _PY_FROM_RE.finditer(content):
        specifier = m.group(1)
        names_str = m.group(2).split("#")[0].strip()
        if names_str.startswith("("):
            start = m.end()
            end = content.find(")", start)
            if end != -1:
                names_str = names_str[1:] + content[start:end]
        names = [n.strip().split(" as ")[0].strip() for n in names_str.split(",") if n.strip() and n.strip() != ")"]
        imports.append({"specifier": specifier, "names": names})

    for m in _PY_IMPORT_RE.finditer(content):
        for mod_part in m.group(1).split(","):
            mod_name = mod_part.strip().split(" as ")[0].strip()
            if mod_name:
                imports.append({"specifier": mod_name, "names": []})

    return imports


_JS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:"""
    r"""(?:type\s+)?(?:\{([^}]+)\}|(\w+)(?:\s*,\s*\{([^}]+)\})?)\s+from\s+"""
    r"""|)['"]([^'"]+)['"]""",
    re.MULTILINE,
)
"""Matches JavaScript/TypeScript import and export-from statements."""

_JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
"""Matches CommonJS require() calls."""

_JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""")
"""Matches dynamic import() expressions."""


def _extract_js_imports(content: str) -> list[dict]:
    """Extract JavaScript/TypeScript import statements.

    Args:
        content: JavaScript or TypeScript source code.

    Returns:
        List of import dicts with specifier and names.
    """
    imports = []
    seen_specifiers: set[str] = set()

    for m in _JS_IMPORT_RE.finditer(content):
        named = m.group(1) or ""
        default = m.group(2) or ""
        extra = m.group(3) or ""
        specifier = m.group(4)
        if not specifier:
            continue

        names = []
        if default:
            names.append(default)
        for group in (named, extra):
            for n_part in group.split(","):
                n_clean = n_part.strip().split(" as ")[0].strip()
                if n_clean and n_clean != "type":
                    names.append(n_clean)
        imports.append({"specifier": specifier, "names": names})
        seen_specifiers.add(specifier)

    for m in _JS_REQUIRE_RE.finditer(content):
        specifier = m.group(1)
        if specifier not in seen_specifiers:
            imports.append({"specifier": specifier, "names": []})
            seen_specifiers.add(specifier)

    for m in _JS_DYNAMIC_IMPORT_RE.finditer(content):
        specifier = m.group(1)
        if specifier not in seen_specifiers:
            imports.append({"specifier": specifier, "names": []})
            seen_specifiers.add(specifier)

    return imports


_GO_IMPORT_SINGLE_RE = re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE)
"""Matches single-line Go import statements."""

_GO_IMPORT_BLOCK_RE = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
"""Matches Go import blocks."""

_GO_IMPORT_LINE_RE = re.compile(r'(?:\w+\s+)?"([^"]+)"')
"""Matches individual import lines within a Go import block."""


def _extract_go_imports(content: str) -> list[dict]:
    """Extract Go import statements.

    Args:
        content: Go source code.

    Returns:
        List of import dicts with specifier and names.
    """
    imports = [{"specifier": m.group(1), "names": []} for m in _GO_IMPORT_SINGLE_RE.finditer(content)]

    for m in _GO_IMPORT_BLOCK_RE.finditer(content):
        block = m.group(1)
        for line_m in _GO_IMPORT_LINE_RE.finditer(block):
            imports.append({"specifier": line_m.group(1), "names": []})

    return imports


_RUST_USE_RE = re.compile(r"^\s*use\s+([\w:]+(?:::\{[^}]+\})?)\s*;", re.MULTILINE)
"""Matches Rust use statements."""


def _extract_rust_imports(content: str) -> list[dict]:
    """Extract Rust use statements.

    Args:
        content: Rust source code.

    Returns:
        List of import dicts with specifier and names.
    """
    imports = []
    for m in _RUST_USE_RE.finditer(content):
        use_path = m.group(1)
        if "::{" in use_path:
            base, brace_part = use_path.split("::{", 1)
            names = [n.strip() for n in brace_part.rstrip("}").split(",") if n.strip()]
            imports.append({"specifier": base, "names": names})
        else:
            parts = use_path.split("::")
            name = parts[-1] if parts else ""
            imports.append({"specifier": use_path, "names": [name] if name else []})
    return imports


_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;?", re.MULTILINE)
"""Matches Java and Kotlin import statements."""


def _extract_java_imports(content: str) -> list[dict]:
    """Extract Java/Kotlin import statements.

    Args:
        content: Java or Kotlin source code.

    Returns:
        List of import dicts with specifier and names.
    """
    imports = []
    for m in _JAVA_IMPORT_RE.finditer(content):
        full = m.group(1)
        parts = full.rsplit(".", 1)
        if len(parts) == 2:
            imports.append({"specifier": parts[0], "names": [parts[1]]})
        else:
            imports.append({"specifier": full, "names": []})
    return imports


_C_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)
"""Matches C/C++ #include directives."""


def _extract_c_imports(content: str) -> list[dict]:
    """Extract C/C++ #include directives.

    Args:
        content: C or C++ source code.

    Returns:
        List of import dicts with specifier and names.
    """
    return [{"specifier": m.group(1), "names": []} for m in _C_INCLUDE_RE.finditer(content)]


_CSHARP_USING_RE = re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)
"""Matches C# using directives."""


def _extract_csharp_imports(content: str) -> list[dict]:
    """Extract C# using directives.

    Args:
        content: C# source code.

    Returns:
        List of import dicts with specifier and names.
    """
    return [{"specifier": m.group(1), "names": []} for m in _CSHARP_USING_RE.finditer(content)]


_RUBY_REQUIRE_RE = re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.MULTILINE)
"""Matches Ruby require and require_relative statements."""


def _extract_ruby_imports(content: str) -> list[dict]:
    """Extract Ruby require statements.

    Args:
        content: Ruby source code.

    Returns:
        List of import dicts with specifier and names.
    """
    return [{"specifier": m.group(1), "names": []} for m in _RUBY_REQUIRE_RE.finditer(content)]


_PHP_USE_RE = re.compile(r"^\s*use\s+([\w\\]+)(?:\s+as\s+\w+)?\s*;", re.MULTILINE)
"""Matches PHP use statements."""


def _extract_php_imports(content: str) -> list[dict]:
    """Extract PHP use statements.

    Args:
        content: PHP source code.

    Returns:
        List of import dicts with specifier and names.
    """
    return [{"specifier": m.group(1), "names": []} for m in _PHP_USE_RE.finditer(content)]


_SWIFT_IMPORT_RE = re.compile(r"^\s*import\s+(\w+)", re.MULTILINE)
"""Matches Swift import statements."""


def _extract_swift_imports(content: str) -> list[dict]:
    """Extract Swift import statements.

    Args:
        content: Swift source code.

    Returns:
        List of import dicts with specifier and names.
    """
    return [{"specifier": m.group(1), "names": []} for m in _SWIFT_IMPORT_RE.finditer(content)]


def _extract_scss_imports(content: str) -> list[dict]:
    """Extract SCSS @use, @forward, and @import statements."""
    from sylvan.indexing.source_code.stylesheet_extractor import (
        _SCSS_FORWARD_RE,
        _SCSS_IMPORT_RE,
        _SCSS_USE_RE,
    )

    results: list[dict] = []
    for m in _SCSS_USE_RE.finditer(content):
        alias = m.group(2)
        names = [alias] if alias and alias != "*" else []
        results.append({"specifier": m.group(1), "names": names})
    for m in _SCSS_FORWARD_RE.finditer(content):
        results.append({"specifier": m.group(1), "names": []})
    for m in _SCSS_IMPORT_RE.finditer(content):
        results.append({"specifier": m.group(1), "names": []})
    return results


def _extract_less_imports(content: str) -> list[dict]:
    """Extract LESS @import statements."""
    from sylvan.indexing.source_code.stylesheet_extractor import _LESS_IMPORT_RE

    return [{"specifier": m.group(1), "names": []} for m in _LESS_IMPORT_RE.finditer(content)]


def _extract_stylus_imports(content: str) -> list[dict]:
    """Extract Stylus @import/@require statements."""
    from sylvan.indexing.source_code.stylesheet_extractor import _STYLUS_IMPORT_RE

    return [{"specifier": m.group(1), "names": []} for m in _STYLUS_IMPORT_RE.finditer(content)]
