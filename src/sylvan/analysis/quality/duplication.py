"""Code duplication detection -- hash-based function body comparison."""

import hashlib
import re
from dataclasses import dataclass

from sylvan.database.orm import Symbol
from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class DuplicateGroup:
    """A group of functions with identical normalized bodies.

    Attributes:
        hash: The normalized body hash.
        symbols: List of symbol info dicts in this group.
        line_count: Approximate number of lines in each duplicate.
    """

    hash: str
    symbols: tuple  # tuple of dicts for frozen=True
    line_count: int


async def detect_duplicates(repo_id: int, min_lines: int = 5) -> list[DuplicateGroup]:
    """Find functions with identical normalized bodies.

    Normalizes function bodies by:
    - Stripping comments and docstrings
    - Removing string literal contents
    - Collapsing whitespace
    Then hashes the result. Functions with the same hash are duplicates.

    Args:
        repo_id: Database ID of the repository.
        min_lines: Minimum function length to consider (skip trivial functions).

    Returns:
        List of DuplicateGroup instances, each containing 2+ identical functions.
    """
    from sylvan.database.orm.models.blob import Blob

    symbols = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .where_in("kind", ["function", "method"])
        .select("symbols.*", "files.path as file_path", "files.content_hash")
        .get()
    )

    hash_to_symbols: dict[str, list[dict]] = {}

    for sym in symbols:
        if not sym.line_start or not sym.line_end:
            continue
        line_count = sym.line_end - sym.line_start
        if line_count < min_lines:
            continue

        content_hash = getattr(sym, "content_hash", None)
        if not content_hash:
            continue

        content = await Blob.get(content_hash)
        if not content:
            continue

        source = content[sym.byte_offset : sym.byte_offset + sym.byte_length]
        body = source.decode("utf-8", errors="replace")

        normalized = _normalize_body(body)
        body_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]

        file_path = getattr(sym, "file_path", "") or ""
        entry = {
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "file": file_path,
            "line_start": sym.line_start,
            "line_end": sym.line_end,
        }

        hash_to_symbols.setdefault(body_hash, []).append(entry)

    # Only keep groups with 2+ duplicates
    groups = []
    for h, syms in hash_to_symbols.items():
        if len(syms) >= 2:
            line_count = syms[0].get("line_end", 0) - syms[0].get("line_start", 0)
            groups.append(
                DuplicateGroup(
                    hash=h,
                    symbols=tuple(syms),
                    line_count=line_count,
                )
            )

    # Sort by line count descending (biggest duplicates first)
    groups.sort(key=lambda g: g.line_count, reverse=True)
    return groups


def _normalize_body(source: str) -> str:
    """Normalize a function body for comparison.

    Strips comments, docstrings, normalizes whitespace,
    and replaces string literal contents so that
    structurally identical code with different string values
    is detected as duplicate.

    Args:
        source: Raw function source code.

    Returns:
        Normalized string for hashing.
    """
    source = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    source = re.sub(r"'''.*?'''", "", source, flags=re.DOTALL)
    source = re.sub(r"#.*$", "", source, flags=re.MULTILINE)
    # avoid false positives on literal content
    source = re.sub(r'"[^"]*"', '""', source)
    source = re.sub(r"'[^']*'", "''", source)
    # Normalize whitespace
    source = re.sub(r"\s+", " ", source).strip()
    return source
