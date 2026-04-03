"""C/C++ language plugin."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register, register_alias
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_C_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)

_C_DECISION = re.compile(
    r"\b(if|elif|for|while|case|catch|except)\b"
    r"|&&|\|\||(?<!\w)and\b|(?<!\w)or\b"
)

_C_SYSTEM_HEADERS = frozenset(
    {
        "stdio.h",
        "stdlib.h",
        "string.h",
        "math.h",
        "time.h",
        "ctype.h",
        "errno.h",
        "signal.h",
        "setjmp.h",
        "stdarg.h",
        "stddef.h",
        "assert.h",
        "limits.h",
        "float.h",
        "locale.h",
        "stdbool.h",
        "stdint.h",
        "inttypes.h",
        "complex.h",
        "tgmath.h",
        "fenv.h",
        "iso646.h",
        "wchar.h",
        "wctype.h",
        "iostream",
        "string",
        "vector",
        "map",
        "set",
        "algorithm",
        "memory",
        "functional",
        "cassert",
        "cstdio",
        "cstdlib",
        "cstring",
        "cmath",
        "utility",
        "numeric",
        "array",
        "list",
        "deque",
        "queue",
        "stack",
        "unordered_map",
        "unordered_set",
        "sstream",
    }
)


@register(
    name="c",
    extensions=[".c", ".h"],
    spec=LanguageSpec(
        ts_language="c",
        symbol_node_types={
            "function_definition": "function",
            "struct_specifier": "class",
            "enum_specifier": "type",
            "type_definition": "type",
        },
        name_fields={
            "function_definition": "declarator",
            "struct_specifier": "name",
            "enum_specifier": "name",
            "type_definition": "declarator",
        },
        param_fields={"function_definition": "declarator"},
        return_type_fields={"function_definition": "type"},
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=[],
        constant_patterns=["declaration"],
    ),
)
class CLanguage:
    """C/C++ import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract C/C++ #include directives.

        Args:
            content: C or C++ source code.

        Returns:
            List of import dicts with specifier and names.
        """
        return [{"specifier": m.group(1), "names": []} for m in _C_INCLUDE_RE.finditer(content)]

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a C/C++ include specifier.

        Args:
            specifier: Include path (e.g. ``myheader.h``).
            source_path: Relative path of the importing file.
            context: Resolver context (unused for C).

        Returns:
            Candidate file paths.
        """
        if specifier in _C_SYSTEM_HEADERS:
            return []

        source_dir = posixpath.dirname(source_path)

        candidates: list[str] = []
        if source_dir:
            candidates.append(posixpath.normpath(posixpath.join(source_dir, specifier)))
        candidates.append(specifier)
        for prefix in ("include/", "src/"):
            candidates.append(f"{prefix}{specifier}")

        return _dedupe(candidates)

    decision_pattern = _C_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for C/C++.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str


register_alias(
    name="cpp",
    extensions=[".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"],
    spec=LanguageSpec(
        ts_language="cpp",
        symbol_node_types={
            "function_definition": "function",
            "class_specifier": "class",
            "struct_specifier": "type",
            "enum_specifier": "type",
            "namespace_definition": "type",
            "template_declaration": "template",
        },
        name_fields={
            "function_definition": "declarator",
            "class_specifier": "name",
            "struct_specifier": "name",
            "enum_specifier": "name",
            "namespace_definition": "name",
            "template_declaration": "declarator",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_specifier", "struct_specifier", "namespace_definition"],
    ),
    plugin_cls=CLanguage,
)


def _dedupe(items: list[str]) -> list[str]:
    """Remove duplicates while preserving order.

    Args:
        items: List of strings.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
