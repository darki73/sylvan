"""Go language plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_GO_IMPORT_SINGLE_RE = re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE)
_GO_IMPORT_BLOCK_RE = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
_GO_IMPORT_LINE_RE = re.compile(r'(?:\w+\s+)?"([^"]+)"')

_GO_DECISION = re.compile(r"\b(if|for|case|select)\b|&&|\|\|")

_GO_STDLIB = frozenset(
    {
        "archive",
        "bufio",
        "builtin",
        "bytes",
        "cmp",
        "compress",
        "container",
        "context",
        "crypto",
        "database",
        "debug",
        "embed",
        "encoding",
        "errors",
        "expvar",
        "flag",
        "fmt",
        "go",
        "hash",
        "html",
        "image",
        "index",
        "io",
        "iter",
        "log",
        "maps",
        "math",
        "mime",
        "net",
        "os",
        "path",
        "plugin",
        "reflect",
        "regexp",
        "runtime",
        "slices",
        "sort",
        "strconv",
        "strings",
        "structs",
        "sync",
        "syscall",
        "testing",
        "text",
        "time",
        "unicode",
        "unique",
        "unsafe",
        "weak",
    }
)


@register(
    name="go",
    extensions=[".go"],
    spec=LanguageSpec(
        ts_language="go",
        symbol_node_types={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "method_declaration": "name",
            "type_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_declaration": "parameters",
        },
        return_type_fields={
            "function_declaration": "result",
            "method_declaration": "result",
        },
        docstring_strategy="preceding_comment",
        decorator_node_type=None,
        container_node_types=[],
        constant_patterns=["const_declaration", "var_declaration"],
    ),
)
class GoLanguage:
    """Go import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract Go import statements.

        Args:
            content: Go source code.

        Returns:
            List of import dicts with specifier and names.
        """
        imports = [{"specifier": m.group(1), "names": []} for m in _GO_IMPORT_SINGLE_RE.finditer(content)]

        for m in _GO_IMPORT_BLOCK_RE.finditer(content):
            block = m.group(1)
            for line_m in _GO_IMPORT_LINE_RE.finditer(block):
                imports.append({"specifier": line_m.group(1), "names": []})

        return imports

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a Go import specifier.

        Args:
            specifier: Go import path.
            source_path: Relative path of the importing file.
            context: Resolver context (unused for Go).

        Returns:
            Candidate file paths.
        """
        if "/" not in specifier:
            return []

        first_segment = specifier.split("/", maxsplit=1)[0]
        if first_segment in _GO_STDLIB:
            return []

        parts = specifier.split("/")
        candidates: list[str] = []
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            candidates.append(suffix)

        return candidates

    decision_pattern = _GO_DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        """No receiver stripping for Go.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string unchanged.
        """
        return params_str
