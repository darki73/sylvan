"""Rust language plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_RUST_USE_RE = re.compile(r"^\s*use\s+([\w:]+(?:::\{[^}]+\})?)\s*;", re.MULTILINE)

_RUST_DECISION = re.compile(r"\b(if|for|while|loop|match)\b|=>")


@register(
    name="rust",
    extensions=[".rs"],
    spec=LanguageSpec(
        ts_language="rust",
        symbol_node_types={
            "function_item": "function",
            "impl_item": "class",
            "struct_item": "class",
            "enum_item": "type",
            "trait_item": "type",
            "type_item": "type",
        },
        name_fields={
            "function_item": "name",
            "impl_item": "type",
            "struct_item": "name",
            "enum_item": "name",
            "trait_item": "name",
            "type_item": "name",
        },
        param_fields={"function_item": "parameters"},
        return_type_fields={"function_item": "return_type"},
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=["impl_item", "trait_item"],
        constant_patterns=["const_item", "static_item", "let_declaration"],
    ),
)
class RustLanguage:
    """Rust import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
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

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a Rust use specifier.

        Args:
            specifier: Rust use path (e.g. ``crate::module::item``).
            source_path: Relative path of the importing file.
            context: Resolver context (unused for Rust).

        Returns:
            Candidate file paths.
        """
        if specifier.startswith("std::") or specifier.startswith("core::"):
            return []

        if specifier.startswith("crate::"):
            remainder = specifier[len("crate::") :]
            parts = remainder.split("::")
            if len(parts) > 1:
                module_path = "/".join(parts[:-1])
            else:
                module_path = parts[0]

            return [
                f"src/{module_path}.rs",
                f"src/{module_path}/mod.rs",
                f"{module_path}.rs",
                f"{module_path}/mod.rs",
            ]

        parts = specifier.split("::")
        if len(parts) > 1:
            module_path = "/".join(parts[:-1])
            return [
                f"src/{module_path}.rs",
                f"src/{module_path}/mod.rs",
                f"{module_path}.rs",
            ]

        return []

    decision_pattern = _RUST_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """Strip Rust &self/&mut self receiver from parameter string.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string with receiver stripped.
        """
        for prefix in ("&mut self,", "&self,", "mut self,", "self,"):
            if params_str.startswith(prefix):
                return params_str[len(prefix) :].strip()
        if params_str in ("&self", "&mut self", "self", "mut self"):
            return ""
        return params_str
