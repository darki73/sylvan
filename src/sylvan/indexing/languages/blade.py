"""Blade template language plugin - import extraction and resolution.

Blade is Laravel's template engine. Files use ``.blade.php`` extensions.
Symbol extraction bypasses tree-sitter entirely (handled by blade_extractor).
This plugin provides import extraction and resolution for Blade's
dot-notation view references.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext


@register(
    name="blade",
    extensions=[".blade.php"],
    spec=LanguageSpec(
        ts_language="php",
        symbol_node_types={},
        name_fields={},
    ),
)
class BladeLanguage:
    """Blade template import extraction and resolution."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract template references from Blade content.

        Args:
            content: Blade file content.

        Returns:
            List of import dicts with specifier and names keys.
        """
        from sylvan.indexing.source_code.blade_extractor import extract_blade_imports

        return extract_blade_imports(content)

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate file paths for a Blade view reference.

        Converts dot notation to Laravel's conventional view paths.

        Args:
            specifier: View reference in dot notation (e.g. ``layouts.app``).
            source_path: Path of the importing file.
            context: Resolver context with repo-level state.

        Returns:
            List of candidate relative paths to try.
        """
        # PHP namespace (from @php use blocks or @use) - delegate to PHP resolver
        if "\\" in specifier:
            if context is None:
                return []
            from sylvan.indexing.languages import get_import_resolver

            php_resolver = get_import_resolver("php")
            if php_resolver:
                return php_resolver.generate_candidates(specifier, source_path, context)
            return []

        # Namespaced views: "mail::message" -> vendor hint resolution
        if "::" in specifier:
            namespace, view = specifier.split("::", 1)
            view_path = view.replace(".", "/")
            return [
                f"resources/views/vendor/{namespace}/{view_path}.blade.php",
                f"vendor/{namespace}/resources/views/{view_path}.blade.php",
            ]

        path_base = specifier.replace(".", "/")
        candidates = [
            f"resources/views/{path_base}.blade.php",
            f"resources/views/{path_base}/index.blade.php",
        ]

        # Livewire references: also try the PHP component class
        if path_base.startswith("livewire/"):
            component_name = path_base[len("livewire/") :]
            # kebab-case to PascalCase: search-users -> SearchUsers
            parts = component_name.split("-")
            pascal = "".join(p.capitalize() for p in parts)
            candidates.append(f"app/Livewire/{pascal}.php")

        return candidates
