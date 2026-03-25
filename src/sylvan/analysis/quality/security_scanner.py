"""Security pattern scanner -- detect common vulnerabilities without LLMs."""

import re
from dataclasses import dataclass

from sylvan.database.orm import FileRecord
from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class SecurityFinding:
    """A detected security issue.

    Attributes:
        file: File path where the issue was found.
        line: Approximate line number.
        rule: Rule identifier.
        severity: critical, high, medium, or low.
        message: Human-readable description.
        snippet: The matched source code snippet.
    """

    file: str
    line: int
    rule: str
    severity: str
    message: str
    snippet: str


# Each rule: (name, severity, pattern, message)
_NOQA_MARKER = "# sylvan-sql-safe"

SECURITY_RULES: list[tuple[str, str, re.Pattern, str]] = [
    (
        "eval_usage",
        "critical",
        re.compile(r"\beval\s*\("),
        "Use of eval() \u2014 arbitrary code execution risk",
    ),
    (
        "exec_usage",
        "critical",
        re.compile(r"\bexec\s*\("),
        "Use of exec() \u2014 arbitrary code execution risk",
    ),
    (
        "shell_injection",
        "high",
        re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
        "subprocess with shell=True — command injection risk",
    ),
    (
        "pickle_load",
        "high",
        re.compile(r"pickle\.loads?\s*\("),
        "Deserialization of untrusted data via pickle",
    ),
    (
        "yaml_unsafe_load",
        "high",
        re.compile(r"yaml\.load\s*\([^)]*(?!Loader)"),
        "yaml.load without SafeLoader — code execution risk",
    ),
    (
        "sql_concatenation",
        "high",
        re.compile(r'(?:execute|cursor\.execute)\s*\(\s*[f"\'].*\{'),
        "SQL string concatenation — SQL injection risk",
    ),
    (
        "hardcoded_password",
        "medium",
        re.compile(
            r'(?:password|passwd|pwd|secret|token|api_key)\s*=\s*["\'][^"\']{4,}["\']',
            re.IGNORECASE,
        ),
        "Hardcoded secret in source code",
    ),
    (
        "md5_usage",
        "medium",
        re.compile(r"(?:md5|MD5)\s*\("),
        "MD5 is cryptographically broken — use SHA-256+",
    ),
    (
        "assert_in_production",
        "low",
        re.compile(r"^\s*assert\s+(?!.*#\s*noqa)", re.MULTILINE),
        "assert statements are stripped in optimized mode (-O)",
    ),
    (
        "broad_except",
        "low",
        re.compile(r"except\s*:\s*$", re.MULTILINE),
        "Bare except catches KeyboardInterrupt and SystemExit",
    ),
]


async def scan_security(repo_id: int) -> list[SecurityFinding]:
    """Scan all source files in a repo for security anti-patterns.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        List of SecurityFinding instances, sorted by severity.
    """
    from sylvan.database.orm.models.blob import Blob

    findings: list[SecurityFinding] = []

    files = await FileRecord.where(repo_id=repo_id).get()

    _self_path = "analysis/quality/security_scanner.py"

    for file_rec in files:
        if not file_rec.language:
            continue
        if "test" in file_rec.path.lower() or "spec" in file_rec.path.lower():
            continue
        if file_rec.path.endswith(_self_path):
            continue

        content = await Blob.get(file_rec.content_hash)
        if not content:
            continue

        text = content.decode("utf-8", errors="replace")
        lines = text.split("\n")

        for rule_name, severity, pattern, message in SECURITY_RULES:
            for match in pattern.finditer(text):
                line_num = text[: match.start()].count("\n") + 1
                snippet_line = lines[line_num - 1].strip() if line_num <= len(lines) else ""

                if _NOQA_MARKER in (lines[line_num - 1] if line_num <= len(lines) else ""):
                    continue

                findings.append(
                    SecurityFinding(
                        file=file_rec.path,
                        line=line_num,
                        rule=rule_name,
                        severity=severity,
                        message=message,
                        snippet=snippet_line[:120],
                    )
                )

    return findings
