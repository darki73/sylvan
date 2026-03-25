"""JSON / JSONC documentation parser -- top-level keys become sections."""

import json
import re
from typing import Any

from sylvan.database.validation import Section
from sylvan.indexing.documents.registry import register_parser
from sylvan.indexing.documents.section_builder import (
    compute_section_hash,
    extract_references,
    extract_tags,
    make_hierarchical_slug,
    make_section_id,
    wire_hierarchy,
)

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Trailing commas before } or ]
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_jsonc(text: str) -> str:
    """Remove JSONC-style comments and trailing commas.

    Args:
        text: Raw JSONC content.

    Returns:
        Cleaned JSON string with comments and trailing commas removed.
    """
    result: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(text):
        ch = text[i]

        if escape:
            result.append(ch)
            escape = False
            i += 1
            continue

        if in_string:
            result.append(ch)
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue

        result.append(ch)
        i += 1

    cleaned = "".join(result)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


def _walk(
    key: str,
    value: Any,
    depth: int,
    max_depth: int,
    doc_path: str,
    repo: str,
    sections: list[Section],
    slug_stack: list[tuple[int, str]],
    used_slugs: set[str],
    byte_cursor: list[int],
) -> None:
    """Recursively create sections from a JSON object.

    Args:
        key: Current JSON key name.
        value: Value associated with the key.
        depth: Current nesting depth.
        max_depth: Maximum depth to recurse into.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.
        sections: Accumulator list for generated sections.
        slug_stack: Mutable ancestry stack for hierarchical slugs.
        used_slugs: Mutable set of already-used slugs.
        byte_cursor: Mutable single-element list tracking byte position.
    """
    level = min(depth, max_depth)
    body = _render_value(key, value)
    body_bytes = body.encode("utf-8")
    start = byte_cursor[0]
    byte_cursor[0] += len(body_bytes)

    slug = make_hierarchical_slug(key, level, slug_stack, used_slugs)
    sec = Section(
        section_id=make_section_id(repo, doc_path, slug, level),
        title=key,
        level=level,
        byte_start=start,
        byte_end=byte_cursor[0],
        content_hash=compute_section_hash(body),
        tags=extract_tags(body),
        references=extract_references(body),
    )
    sections.append(sec)

    if isinstance(value, dict) and depth < max_depth:
        for child_key, child_val in value.items():
            _walk(
                child_key,
                child_val,
                depth + 1,
                max_depth,
                doc_path,
                repo,
                sections,
                slug_stack,
                used_slugs,
                byte_cursor,
            )


def _render_value(key: str, value: Any) -> str:
    """Render a JSON key/value pair as readable text.

    Args:
        key: JSON key name.
        value: Associated value (dict, list, or scalar).

    Returns:
        Human-readable text representation.
    """
    if isinstance(value, dict):
        inner = json.dumps(value, indent=2, ensure_ascii=False)
        return f"{key}:\n{inner}\n"
    if isinstance(value, list):
        inner = json.dumps(value, indent=2, ensure_ascii=False)
        return f"{key}: {inner}\n"
    return f"{key}: {json.dumps(value, ensure_ascii=False)}\n"


@register_parser("json", [".json", ".jsonc"])
def parse_json_doc(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse a JSON or JSONC file into sections.

    Top-level keys become level-1 sections.  Nested objects produce deeper
    headings up to depth 4.

    Args:
        content: Raw JSON/JSONC content string.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    cleaned = _strip_jsonc(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, dict):
        return []

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()
    byte_cursor = [0]

    for key, value in data.items():
        _walk(key, value, 1, 4, doc_path, repo, sections, slug_stack, used_slugs, byte_cursor)

    wire_hierarchy(sections)
    return sections
