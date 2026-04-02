"""Per-symbol complexity metrics computed at index time.

Cyclomatic complexity, max nesting depth, and parameter count.
Language-aware with proper comment/string exclusion.
"""

from __future__ import annotations

import re

# McCabe decision points per language (else is NOT a decision point).
# Each keyword represents a path fork.
_PYTHON_DECISION = re.compile(
    r"\b(if|elif|for|while|except|and|or|assert)\b"
    r"|\bif\s+.*\s+else\s+"  # inline ternary
)
_JS_DECISION = re.compile(
    r"\b(if|for|while|case|catch)\b"
    r"|&&|\|\||\?\?|\?(?=[^:])"  # logical ops + ternary
)
_GO_DECISION = re.compile(r"\b(if|for|case|select)\b|&&|\|\|")
_RUST_DECISION = re.compile(r"\b(if|for|while|loop|match)\b|=>")
_JAVA_DECISION = re.compile(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
_GENERIC_DECISION = re.compile(r"\b(if|elif|for|while|case|catch|except)\b|&&|\|\||(?<!\w)and\b|(?<!\w)or\b")

_DECISION_PATTERNS: dict[str, re.Pattern[str]] = {
    "python": _PYTHON_DECISION,
    "javascript": _JS_DECISION,
    "typescript": _JS_DECISION,
    "tsx": _JS_DECISION,
    "go": _GO_DECISION,
    "rust": _RUST_DECISION,
    "java": _JAVA_DECISION,
    "kotlin": _JAVA_DECISION,
    "c_sharp": _JAVA_DECISION,
    "c": _GENERIC_DECISION,
    "cpp": _GENERIC_DECISION,
    "php": _JAVA_DECISION,
    "swift": _JAVA_DECISION,
    "ruby": _PYTHON_DECISION,
    "dart": _JAVA_DECISION,
}

# Comment/string stripping per language family
_LINE_COMMENT = re.compile(r"//.*$|#.*$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_TRIPLE_STRING = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'', re.DOTALL)
_DOUBLE_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_SINGLE_STRING = re.compile(r"'(?:[^'\\]|\\.)*'")
_TEMPLATE_STRING = re.compile(r"`(?:[^`\\]|\\.)*`")

_BRACE_LANGUAGES = frozenset(
    {
        "javascript",
        "typescript",
        "tsx",
        "go",
        "rust",
        "java",
        "kotlin",
        "c_sharp",
        "c",
        "cpp",
        "php",
        "swift",
        "dart",
        "scala",
    }
)

_PARAM_SPLIT = re.compile(r",(?![^<\[({]*[>\])}])")


def compute_complexity(source: str, language: str) -> dict[str, int]:
    """Compute complexity metrics for a symbol's source body.

    Args:
        source: The raw source text of the symbol.
        language: Language identifier.

    Returns:
        Dict with cyclomatic, max_nesting, and param_count keys.
    """
    return {
        "cyclomatic": _cyclomatic(source, language),
        "max_nesting": _max_nesting(source, language),
        "param_count": _param_count(source, language),
    }


def _strip_noise(source: str, language: str) -> str:
    """Remove comments and string literals so they don't inflate counts."""
    if language == "python":
        text = _TRIPLE_STRING.sub("", source)
        text = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    else:
        text = _BLOCK_COMMENT.sub("", source)
        text = _LINE_COMMENT.sub("", text)

    text = _DOUBLE_STRING.sub('""', text)
    text = _SINGLE_STRING.sub("''", text)
    text = _TEMPLATE_STRING.sub("``", text)
    return text


def _cyclomatic(source: str, language: str) -> int:
    """Cyclomatic complexity: 1 + decision point count.

    Comments and strings are stripped first so keywords inside
    them don't inflate the score.
    """
    clean = _strip_noise(source, language)
    pattern = _DECISION_PATTERNS.get(language, _GENERIC_DECISION)
    return 1 + len(pattern.findall(clean))


def _max_nesting(source: str, language: str) -> int:
    """Max nesting depth from indentation or brace counting."""
    if language in _BRACE_LANGUAGES:
        return _brace_nesting(source)
    return _indent_nesting(source)


def _indent_nesting(source: str) -> int:
    """Max nesting from indentation (Python, Ruby, etc.).

    Auto-detects indent width from the first indented line
    instead of assuming 4 spaces.
    """
    lines = source.split("\n")
    if not lines:
        return 0

    base_indent = None
    indent_step = None
    max_depth = 0

    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        if "\t" in line and not line.lstrip().startswith("\t"):
            indent = line[: len(line) - len(stripped)].count("\t")
        else:
            indent = len(line) - len(stripped)

        if base_indent is None:
            base_indent = indent
            continue

        relative = indent - base_indent
        if relative <= 0:
            continue

        if indent_step is None and relative > 0:
            indent_step = relative

        if indent_step and indent_step > 0:
            depth = relative // indent_step
            max_depth = max(max_depth, depth)

    return max_depth


def _brace_nesting(source: str) -> int:
    """Max nesting from brace depth, skipping strings."""
    depth = 0
    max_depth = 0
    in_string = None
    prev = ""

    for ch in source:
        if in_string:
            if ch == in_string and prev != "\\":
                in_string = None
        elif ch in ('"', "'", "`"):
            in_string = ch
        elif ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)
        prev = ch

    return max(0, max_depth - 1)


def _param_count(source: str, language: str) -> int:
    """Count parameters from the first parenthesised group."""
    first_paren = source.find("(")
    if first_paren == -1:
        return 0

    depth = 0
    end = -1
    for i in range(first_paren, len(source)):
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return 0

    params_str = source[first_paren + 1 : end].strip()
    if not params_str:
        return 0

    # Strip Python self/cls receiver
    if language == "python":
        if params_str in ("self", "cls"):
            return 0
        for prefix in ("self,", "cls,"):
            if params_str.startswith(prefix):
                params_str = params_str[len(prefix) :].strip()
                break

    # Strip Rust &self/&mut self receiver
    if language == "rust":
        for prefix in ("&mut self,", "&self,", "mut self,", "self,"):
            if params_str.startswith(prefix):
                params_str = params_str[len(prefix) :].strip()
                break
        if params_str in ("&self", "&mut self", "self", "mut self"):
            return 0

    parts = _PARAM_SPLIT.split(params_str)
    return len([p for p in parts if p.strip()])
