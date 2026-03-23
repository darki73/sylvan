"""reStructuredText documentation parser."""

import re
import string

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

# Any printable non-alphanumeric character can be an adornment character.
_ADORNMENT_CHARS = set(string.punctuation)
_ADORNMENT_RE = re.compile(r"^([^\w\s])\1{2,}\s*$")


def _is_adornment(line: str) -> str | None:
    """Return the adornment character if *line* is a valid RST adornment, else None.

    Args:
        line: A single line of text.

    Returns:
        The adornment character, or None if not an adornment line.
    """
    m = _ADORNMENT_RE.match(line)
    if m and m.group(1) in _ADORNMENT_CHARS:
        return m.group(1)
    return None


def _is_title_line(line: str) -> bool:
    """Return True if *line* could be a title (non-empty, not adornment, not blank).

    Args:
        line: A single line of text.

    Returns:
        True if the line is a candidate title.
    """
    stripped = line.strip()
    return bool(stripped) and _is_adornment(line) is None


@register_parser("rst", [".rst"])
def parse_rst(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse reStructuredText into a list of Section objects.

    Heading levels are assigned by order of first appearance of each
    ``(adornment_char, has_overline)`` combination, exactly as Docutils does.

    Args:
        content: Raw reStructuredText content.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    content_bytes = content.encode("utf-8")
    lines = content.split("\n")

    line_byte_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_byte_offsets.append(offset)
        offset += len(line.encode("utf-8")) + 1

    headings: list[tuple[int, str, tuple[str, bool]]] = []

    idx = 0
    while idx < len(lines):
        if (
            idx + 2 < len(lines)
            and (over_char := _is_adornment(lines[idx])) is not None
            and _is_title_line(lines[idx + 1])
            and _is_adornment(lines[idx + 2]) == over_char
        ):
            title = lines[idx + 1].strip()
            headings.append((idx + 1, title, (over_char, True)))
            idx += 3
            continue

        if (
            idx + 1 < len(lines)
            and _is_title_line(lines[idx])
            and (under_char := _is_adornment(lines[idx + 1])) is not None
            and len(lines[idx + 1].rstrip()) >= len(lines[idx].rstrip())
        ):
            title = lines[idx].strip()
            headings.append((idx, title, (under_char, False)))
            idx += 2
            continue

        idx += 1

    level_map: dict[tuple[str, bool], int] = {}
    for _, _, key in headings:
        if key not in level_map:
            level_map[key] = len(level_map) + 1

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()

    def _make(title: str, level: int, start_line: int, end_line: int) -> Section:
        """Build a Section for the given heading span.

        Args:
            title: Section heading text.
            level: Heading depth level.
            start_line: First line index (inclusive).
            end_line: Last line index (exclusive).

        Returns:
            A populated Section object.
        """
        byte_start = line_byte_offsets[start_line] if start_line < len(line_byte_offsets) else len(content_bytes)
        byte_end = line_byte_offsets[end_line] if end_line < len(line_byte_offsets) else len(content_bytes)
        body = "\n".join(lines[start_line:end_line])
        slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
        return Section(
            section_id=make_section_id(repo, doc_path, slug, level),
            title=title,
            level=level,
            byte_start=byte_start,
            byte_end=byte_end,
            content_hash=compute_section_hash(body),
            tags=extract_tags(body),
            references=extract_references(body),
        )

    first_line = headings[0][0] if headings else len(lines)
    if headings and headings[0][2][1]:
        first_line = max(first_line - 1, 0)
    preamble = "\n".join(lines[:first_line]).strip()
    if preamble:
        sections.append(_make("(root)", 0, 0, first_line))

    for i, (title_line, title, key) in enumerate(headings):
        level = level_map[key]
        start = title_line - 1 if key[1] else title_line
        if i + 1 < len(headings):
            next_title_line, _, next_key = headings[i + 1]
            end = (next_title_line - 1) if next_key[1] else next_title_line
        else:
            end = len(lines)
        sections.append(_make(title, level, start, end))

    wire_hierarchy(sections)
    return sections
