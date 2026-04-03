"""JavaScript/TypeScript/TSX/JSX language plugin."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register, register_alias
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_JS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:"""
    r"""(?:type\s+)?(?:\{([^}]+)\}|(\w+)(?:\s*,\s*\{([^}]+)\})?)\s+from\s+"""
    r"""|)['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_DYNAMIC_IMPORT_RE = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""")

_JS_DECISION = re.compile(
    r"\b(if|for|while|case|catch)\b"
    r"|&&|\|\||\?\?|\?(?=[^:])"
)

_JS_EXTENSIONS = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue", ".svelte")


@register(
    name="javascript",
    extensions=[".js", ".mjs", ".cjs"],
    spec=LanguageSpec(
        ts_language="javascript",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "class"],
    ),
)
class JavaScriptLanguage:
    """JavaScript/TypeScript import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract JS/TS import, export-from, require, and dynamic import statements.

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

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a JS/TS import specifier.

        Args:
            specifier: Import specifier.
            source_path: Relative path of the importing file.
            context: Resolver context with tsconfig aliases.

        Returns:
            Candidate file paths.
        """
        if context.tsconfig_aliases and not specifier.startswith("."):
            expanded = _expand_ts_alias(specifier, context.tsconfig_aliases)
            if expanded is not None:
                return _extension_candidates(expanded)

        if not specifier.startswith(".") and not specifier.startswith("/"):
            return []

        source_dir = posixpath.dirname(source_path)
        resolved = posixpath.normpath(posixpath.join(source_dir, specifier))

        return _extension_candidates(resolved)

    decision_pattern = _JS_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for JavaScript.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str


# Register TypeScript and TSX as aliases sharing JS capabilities
# but with their own tree-sitter specs.
register_alias(
    name="typescript",
    extensions=[".ts"],
    spec=LanguageSpec(
        ts_language="typescript",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
            "interface_declaration": "type",
            "type_alias_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
            "interface_declaration": "name",
            "type_alias_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        return_type_fields={
            "function_declaration": "return_type",
            "method_definition": "return_type",
        },
        docstring_strategy="preceding_comment",
        decorator_node_type="decorator",
        container_node_types=["class_declaration", "class"],
    ),
    plugin_cls=JavaScriptLanguage,
)

register_alias(
    name="tsx",
    extensions=[".tsx"],
    spec=LanguageSpec(
        ts_language="tsx",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
            "interface_declaration": "type",
            "type_alias_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
            "interface_declaration": "name",
            "type_alias_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        decorator_node_type="decorator",
        container_node_types=["class_declaration", "class"],
    ),
    plugin_cls=JavaScriptLanguage,
)

register_alias(
    name="jsx",
    extensions=[".jsx"],
    spec=LanguageSpec(
        ts_language="javascript",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "class"],
    ),
    plugin_cls=JavaScriptLanguage,
)


def _expand_ts_alias(
    specifier: str,
    aliases: dict[str, list[str]],
) -> str | None:
    """Expand a tsconfig path alias to a repo-relative path.

    Args:
        specifier: Import specifier (e.g. ``@/lib/utils``).
        aliases: Alias prefix to directory list mapping.

    Returns:
        Expanded repo-relative path without extension, or None.
    """
    for alias in sorted(aliases, key=len, reverse=True):
        if specifier == alias or specifier.startswith(alias + "/"):
            remainder = specifier[len(alias) :].lstrip("/")
            for target_dir in aliases[alias]:
                if remainder:
                    return f"{target_dir}/{remainder}"
                return target_dir
    return None


def _extension_candidates(resolved: str) -> list[str]:
    """Generate extension variants for a resolved JS/TS path.

    Args:
        resolved: Repo-relative path without extension.

    Returns:
        Candidate file paths with various extensions.
    """
    candidates = [resolved]

    if resolved.endswith(_JS_EXTENSIONS):
        return candidates

    for ext in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue"):
        candidates.append(f"{resolved}{ext}")
    for index in ("/index.js", "/index.ts", "/index.tsx"):
        candidates.append(f"{resolved}{index}")

    return candidates
