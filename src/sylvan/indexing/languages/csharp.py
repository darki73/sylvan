"""C# language plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_CSHARP_USING_RE = re.compile(
    r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;",
    re.MULTILINE,
)

_CSHARP_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")


@register(
    name="c_sharp",
    extensions=[".cs"],
    spec=LanguageSpec(
        ts_language="c_sharp",
        symbol_node_types={
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "type",
            "struct_declaration": "class",
            "enum_declaration": "type",
        },
        name_fields={
            "method_declaration": "name",
            "class_declaration": "name",
            "interface_declaration": "name",
            "struct_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={"method_declaration": "parameters"},
        return_type_fields={"method_declaration": "type"},
        docstring_strategy="preceding_comment",
        decorator_node_type="attribute_list",
        container_node_types=[
            "class_body",
            "interface_body",
            "struct_body",
            "enum_body",
        ],
        constant_patterns=["field_declaration", "property_declaration"],
    ),
)
class CSharpLanguage:
    """C# import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract C# using directives.

        Args:
            content: C# source code.

        Returns:
            List of import dicts with specifier and names.
        """
        return [{"specifier": m.group(1), "names": []} for m in _CSHARP_USING_RE.finditer(content)]

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a C# using specifier.

        Args:
            specifier: C# namespace (e.g. ``MyApp.Models``).
            source_path: Relative path of the importing file.
            context: Resolver context (unused for C#).

        Returns:
            Candidate file paths.
        """
        path_base = specifier.replace(".", "/")
        return [
            f"{path_base}.cs",
            f"src/{path_base}.cs",
        ]

    decision_pattern = _CSHARP_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for C#.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str
