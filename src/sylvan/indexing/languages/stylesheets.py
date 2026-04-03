"""Stylesheet language plugins (SCSS, LESS, Stylus)."""

from __future__ import annotations

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec


@register(
    name="scss",
    extensions=[".scss", ".sass"],
    spec=LanguageSpec(
        ts_language="scss",
        symbol_node_types={
            "rule_set": "type",
            "mixin_statement": "function",
            "function_statement": "function",
            "media_statement": "type",
            "keyframes_statement": "function",
            "include_statement": "constant",
            "placeholder": "type",
        },
        name_fields={
            "rule_set": "selectors",
            "mixin_statement": "name",
            "function_statement": "name",
            "keyframes_statement": "name",
        },
        param_fields={
            "mixin_statement": "parameters",
            "function_statement": "parameters",
        },
        docstring_strategy="preceding_comment",
    ),
)
class ScssLanguage:
    """SCSS import extraction (no resolver)."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract SCSS @use, @forward, and @import statements.

        Args:
            content: SCSS source code.

        Returns:
            List of import dicts with specifier and names.
        """
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


@register(
    name="less",
    extensions=[".less"],
    spec=LanguageSpec(
        ts_language="css",
        symbol_node_types={
            "rule_set": "type",
            "media_statement": "type",
            "keyframes_statement": "function",
            "import_statement": "constant",
        },
        name_fields={
            "rule_set": "selectors",
            "keyframes_statement": "name",
        },
        docstring_strategy="preceding_comment",
    ),
)
class LessLanguage:
    """LESS import extraction (no resolver)."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract LESS @import statements.

        Args:
            content: LESS source code.

        Returns:
            List of import dicts with specifier and names.
        """
        from sylvan.indexing.source_code.stylesheet_extractor import _LESS_IMPORT_RE

        return [{"specifier": m.group(1), "names": []} for m in _LESS_IMPORT_RE.finditer(content)]


@register(
    name="stylus",
    extensions=[".styl"],
    spec=LanguageSpec(
        ts_language="css",
        symbol_node_types={
            "rule_set": "type",
            "media_statement": "type",
            "keyframes_statement": "function",
        },
        name_fields={
            "rule_set": "selectors",
            "keyframes_statement": "name",
        },
        docstring_strategy="preceding_comment",
    ),
)
class StylusLanguage:
    """Stylus import extraction (no resolver)."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract Stylus @import/@require statements.

        Args:
            content: Stylus source code.

        Returns:
            List of import dicts with specifier and names.
        """
        from sylvan.indexing.source_code.stylesheet_extractor import _STYLUS_IMPORT_RE

        return [{"specifier": m.group(1), "names": []} for m in _STYLUS_IMPORT_RE.finditer(content)]
