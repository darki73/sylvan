"""Java/Kotlin language plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register, register_alias
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_JAVA_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;?",
    re.MULTILINE,
)

_JAVA_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")


@register(
    name="java",
    extensions=[".java"],
    spec=LanguageSpec(
        ts_language="java",
        symbol_node_types={
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "type",
            "enum_declaration": "type",
            "constructor_declaration": "method",
        },
        name_fields={
            "method_declaration": "name",
            "class_declaration": "name",
            "interface_declaration": "name",
            "enum_declaration": "name",
            "constructor_declaration": "name",
        },
        param_fields={
            "method_declaration": "parameters",
            "constructor_declaration": "parameters",
        },
        return_type_fields={"method_declaration": "type"},
        docstring_strategy="preceding_comment",
        decorator_node_type="marker_annotation",
        container_node_types=["class_declaration", "interface_declaration", "enum_declaration"],
        constant_patterns=["field_declaration"],
    ),
)
class JavaLanguage:
    """Java/Kotlin import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
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

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a Java/Kotlin import specifier.

        Args:
            specifier: Java import path (e.g. ``com.example.util``).
            source_path: Relative path of the importing file.
            context: Resolver context (unused for Java).

        Returns:
            Candidate file paths.
        """
        path_base = specifier.replace(".", "/")
        # Determine extension from source file.
        ext = ".kt" if source_path.endswith((".kt", ".kts")) else ".java"

        candidates: list[str] = []
        for prefix in ("", "src/main/java/", "src/main/kotlin/", "src/"):
            candidates.append(f"{prefix}{path_base}{ext}")

        return candidates

    decision_pattern = _JAVA_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for Java.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str


register_alias(
    name="kotlin",
    extensions=[".kt", ".kts"],
    spec=LanguageSpec(
        ts_language="kotlin",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "object_declaration": "class",
            "interface_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "object_declaration": "name",
            "interface_declaration": "name",
        },
        param_fields={"function_declaration": "value_parameters"},
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "object_declaration", "interface_declaration"],
    ),
    plugin_cls=JavaLanguage,
)
