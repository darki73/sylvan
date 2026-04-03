"""Python language plugin."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_PY_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)

_PY_DECISION = re.compile(
    r"\b(if|elif|for|while|except|and|or|assert)\b"
    r"|\bif\s+.*\s+else\s+"
)


@register(
    name="python",
    extensions=[".py", ".pyi", ".pyx"],
    spec=LanguageSpec(
        ts_language="python",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
        },
        param_fields={"function_definition": "parameters"},
        return_type_fields={"function_definition": "return_type"},
        docstring_strategy="next_sibling_string",
        decorator_node_type="decorator",
        container_node_types=["class_definition"],
        constant_patterns=["assignment"],
    ),
)
class PythonLanguage:
    """Python import extraction, resolution, and complexity."""

    def extract_imports(self, content: str) -> list[dict]:
        """Extract Python import and from-import statements.

        Args:
            content: Python source code.

        Returns:
            List of import dicts with specifier and names.
        """
        imports = []
        for m in _PY_FROM_RE.finditer(content):
            specifier = m.group(1)
            names_str = m.group(2).split("#")[0].strip()
            if names_str.startswith("("):
                start = m.end()
                end = content.find(")", start)
                if end != -1:
                    names_str = names_str[1:] + content[start:end]
            names = [n.strip().split(" as ")[0].strip() for n in names_str.split(",") if n.strip() and n.strip() != ")"]
            imports.append({"specifier": specifier, "names": names})

        for m in _PY_IMPORT_RE.finditer(content):
            for mod_part in m.group(1).split(","):
                mod_name = mod_part.strip().split(" as ")[0].strip()
                if mod_name:
                    imports.append({"specifier": mod_name, "names": []})

        return imports

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Generate candidate paths for a Python import specifier.

        Args:
            specifier: Python import specifier.
            source_path: Relative path of the importing file.
            context: Resolver context (unused for Python).

        Returns:
            Candidate file paths.
        """
        if specifier.startswith("."):
            return _python_relative_candidates(specifier, source_path)

        if "." not in specifier:
            candidates = []
            for prefix in ("", "src/", "lib/"):
                candidates.append(f"{prefix}{specifier}/__init__.py")
                candidates.append(f"{prefix}{specifier}.py")
            return _dedupe(candidates)

        path_base = specifier.replace(".", "/")
        candidates: list[str] = []
        for prefix in ("", "src/", "lib/"):
            candidates.append(f"{prefix}{path_base}.py")
            candidates.append(f"{prefix}{path_base}/__init__.py")

        return _dedupe(candidates)

    decision_pattern = _PY_DECISION
    uses_braces = False

    def strip_receiver(self, params_str: str) -> str:
        """Strip Python self/cls receiver from parameter string.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string with receiver stripped.
        """
        if params_str in ("self", "cls"):
            return ""
        for prefix in ("self,", "cls,"):
            if params_str.startswith(prefix):
                return params_str[len(prefix) :].strip()
        return params_str


def _python_relative_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidates for Python relative imports.

    Args:
        specifier: A relative specifier like ``.utils`` or ``..config``.
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    dots = 0
    for ch in specifier:
        if ch == ".":
            dots += 1
        else:
            break

    remainder = specifier[dots:]
    source_dir = posixpath.dirname(source_path)

    base = source_dir
    for _ in range(dots - 1):
        base = posixpath.dirname(base)

    if remainder:
        path_base = posixpath.join(base, remainder.replace(".", "/"))
    else:
        path_base = base

    path_base = posixpath.normpath(path_base)

    return [
        f"{path_base}.py",
        f"{path_base}/__init__.py",
    ]


def _dedupe(items: list[str]) -> list[str]:
    """Remove duplicates while preserving order.

    Args:
        items: List of strings.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
