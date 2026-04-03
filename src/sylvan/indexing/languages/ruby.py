"""Ruby language plugin."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_RUBY_REQUIRE_RE = re.compile(
    r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)

_RUBY_DECISION = re.compile(
    r"\b(if|elif|for|while|except|and|or|assert)\b"
    r"|\bif\s+.*\s+else\s+"
)


@register(
    name="ruby",
    extensions=[".rb", ".rake", ".gemspec"],
    spec=LanguageSpec(
        ts_language="ruby",
        symbol_node_types={
            "method": "method",
            "singleton_method": "method",
            "class": "class",
            "module": "class",
        },
        name_fields={
            "method": "name",
            "singleton_method": "name",
            "class": "name",
            "module": "name",
        },
        param_fields={"method": "parameters", "singleton_method": "parameters"},
        return_type_fields={},
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=["class", "module"],
        constant_patterns=["assignment"],
    ),
)
class RubyLanguage:
    """Ruby import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract Ruby require and require_relative statements.

        Args:
            content: Ruby source code.

        Returns:
            List of import dicts with specifier and names.
        """
        return [{"specifier": m.group(1), "names": []} for m in _RUBY_REQUIRE_RE.finditer(content)]

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a Ruby require specifier.

        Args:
            specifier: Ruby require path.
            source_path: Relative path of the importing file.
            context: Resolver context (unused for Ruby).

        Returns:
            Candidate file paths.
        """
        if specifier.startswith("."):
            source_dir = posixpath.dirname(source_path)
            resolved = posixpath.normpath(posixpath.join(source_dir, specifier))
            candidates = [resolved]
            if not resolved.endswith(".rb"):
                candidates.append(f"{resolved}.rb")
            return candidates

        candidates = [specifier]
        if not specifier.endswith(".rb"):
            candidates.append(f"{specifier}.rb")
        for prefix in ("lib/", "app/"):
            candidates.append(f"{prefix}{specifier}")
            if not specifier.endswith(".rb"):
                candidates.append(f"{prefix}{specifier}.rb")

        return candidates

    decision_pattern = _RUBY_DECISION
    uses_braces = False

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for Ruby.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str
