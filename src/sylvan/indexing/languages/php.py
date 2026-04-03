"""PHP language plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_PHP_USE_RE = re.compile(
    r"^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;",
    re.MULTILINE,
)
_PHP_GROUP_USE_RE = re.compile(
    r"^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)\\{([^}]+)}\s*;",
    re.MULTILINE,
)

_PHP_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")


@register(
    name="php",
    extensions=[".php"],
    spec=LanguageSpec(
        ts_language="php",
        symbol_node_types={
            "function_definition": "function",
            "class_declaration": "class",
            "method_declaration": "method",
            "interface_declaration": "type",
            "trait_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_definition": "name",
            "class_declaration": "name",
            "method_declaration": "name",
            "interface_declaration": "name",
            "trait_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_definition": "parameters",
            "method_declaration": "parameters",
        },
        return_type_fields={},
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=[
            "class_body",
            "declaration_list",
            "enum_declaration_list",
        ],
        constant_patterns=["const_declaration", "property_declaration"],
    ),
)
class PhpLanguage:
    """PHP import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract PHP use statements including group imports.

        Handles ``use Foo\\Bar;``, ``use function Foo\\bar;``,
        ``use const Foo\\BAR;``, and ``use Foo\\{Bar, Baz};``.

        Args:
            content: PHP source code.

        Returns:
            List of import dicts with specifier and names.
        """
        results = [{"specifier": m.group(1), "names": []} for m in _PHP_USE_RE.finditer(content)]

        for m in _PHP_GROUP_USE_RE.finditer(content):
            prefix = m.group(1)
            for name in m.group(2).split(","):
                name = name.strip().split(" as ")[0].strip()
                if name:
                    results.append({"specifier": f"{prefix}\\{name}", "names": []})

        return results

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a PHP use/require specifier.

        Uses PSR-4/PSR-0 autoload mappings from composer.json when available,
        falling back to naive backslash-to-slash conversion.

        Args:
            specifier: PHP namespace path (e.g. ``App\\Models\\User``).
            source_path: Relative path of the importing file.
            context: Resolver context with PSR-4 mappings.

        Returns:
            Candidate file paths.
        """
        candidates: list[str] = []

        if context.psr4_mappings:
            for prefix in sorted(context.psr4_mappings, key=len, reverse=True):
                ns_prefix = prefix.rstrip("\\")
                if specifier == ns_prefix or specifier.startswith(ns_prefix + "\\"):
                    relative = specifier[len(ns_prefix) :].lstrip("\\")
                    relative_path = relative.replace("\\", "/")
                    for base_dir in context.psr4_mappings[prefix]:
                        if relative_path:
                            candidates.append(f"{base_dir}{relative_path}.php")
                        else:
                            candidates.append(f"{base_dir}.php")
                    if candidates:
                        break

        path_base = specifier.replace("\\", "/")
        candidates.append(f"{path_base}.php")
        candidates.append(f"src/{path_base}.php")
        candidates.append(f"app/{path_base}.php")

        return candidates

    decision_pattern = _PHP_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for PHP.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str
