"""Swift language plugin."""

from __future__ import annotations

import re

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

_SWIFT_IMPORT_RE = re.compile(r"^\s*import\s+(\w+)", re.MULTILINE)

_SWIFT_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")


@register(
    name="swift",
    extensions=[".swift"],
    spec=LanguageSpec(
        ts_language="swift",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "struct_declaration": "class",
            "enum_declaration": "type",
            "protocol_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "struct_declaration": "name",
            "enum_declaration": "name",
            "protocol_declaration": "name",
        },
        param_fields={"function_declaration": "parameters"},
        return_type_fields={"function_declaration": "return_type"},
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=[
            "class_body",
            "struct_body",
            "enum_body",
            "protocol_body",
        ],
        constant_patterns=["property_declaration"],
    ),
)
class SwiftLanguage:
    """Swift import extraction and complexity (no resolver - framework imports only)."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract Swift import statements.

        Args:
            content: Swift source code.

        Returns:
            List of import dicts with specifier and names.
        """
        return [{"specifier": m.group(1), "names": []} for m in _SWIFT_IMPORT_RE.finditer(content)]

    decision_pattern = _SWIFT_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for Swift.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str
