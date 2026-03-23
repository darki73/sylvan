"""Markdown documentation parser -- ATX and setext headings, MDX support."""

import re

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

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_IMPORT_RE = re.compile(r"^import\s+.*$", re.MULTILINE)
_JSX_BLOCK_RE = re.compile(r"<[A-Z][A-Za-z0-9.]*(?:\s[^>]*)?>.*?</[A-Z][A-Za-z0-9.]*>", re.DOTALL)
_JSX_SELF_RE = re.compile(r"<[A-Z][A-Za-z0-9.]*(?:\s[^>]*)?/>")
_EXPORT_DEFAULT_RE = re.compile(r"^export\s+default\s+.*$", re.MULTILINE)
_EXPORT_RE = re.compile(r"^export\s+.*$", re.MULTILINE)


def _strip_mdx(content: str) -> str:
    """Remove MDX-specific syntax so the remainder is valid Markdown.

    Args:
        content: Raw MDX/Markdown content.

    Returns:
        Cleaned Markdown with MDX constructs removed.
    """
    content = _FRONTMATTER_RE.sub("", content)
    content = _IMPORT_RE.sub("", content)
    content = _EXPORT_DEFAULT_RE.sub("", content)
    content = _EXPORT_RE.sub("", content)
    content = _JSX_BLOCK_RE.sub("", content)
    content = _JSX_SELF_RE.sub("", content)
    return content


_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^(={3,}|-{3,})\s*$")


def _is_in_fenced_block(line_idx: int, lines: list[str]) -> bool:
    """Return True if *line_idx* is inside a fenced code block.

    Args:
        line_idx: Zero-based line index to check.
        lines: All lines of the document.

    Returns:
        True if the line falls inside a fenced code block.
    """
    fence_open = False
    for i in range(line_idx):
        stripped = lines[i].lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_open = not fence_open
    return fence_open


@register_parser("markdown", [".md", ".markdown", ".mdx"])
def parse_markdown(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse Markdown (and MDX) content into a list of Section objects.

    Args:
        content: Raw Markdown/MDX content.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    cleaned = _strip_mdx(content)
    content.encode("utf-8")
    cleaned_bytes = cleaned.encode("utf-8")
    lines = cleaned.split("\n")

    line_byte_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_byte_offsets.append(offset)
        offset += len(line.encode("utf-8")) + 1  # +1 for '\n'

    headings: list[tuple[int, int, str]] = []

    for idx, line in enumerate(lines):
        if _is_in_fenced_block(idx, lines):
            continue

        m = _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            headings.append((idx, level, title))
            continue

        if idx + 1 < len(lines):
            m_under = _SETEXT_UNDERLINE_RE.match(lines[idx + 1])
            if m_under and line.strip() and not line.startswith((" ", "\t", "#", ">", "-", "*", "+")):
                level = 1 if lines[idx + 1][0] == "=" else 2
                headings.append((idx, level, line.strip()))

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()

    def _make_section(
        title: str,
        level: int,
        start_line: int,
        end_line: int,
    ) -> Section:
        """Build a Section for the given heading span.

        Args:
            title: Section heading text.
            level: Heading depth level.
            start_line: First line index (inclusive).
            end_line: Last line index (exclusive).

        Returns:
            A populated Section object.
        """
        byte_start = line_byte_offsets[start_line] if start_line < len(line_byte_offsets) else len(cleaned_bytes)
        byte_end = line_byte_offsets[end_line] if end_line < len(line_byte_offsets) else len(cleaned_bytes)
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

    first_heading_line = headings[0][0] if headings else len(lines)
    preamble = "\n".join(lines[:first_heading_line]).strip()
    if preamble:
        sections.append(_make_section("(root)", 0, 0, first_heading_line))

    for i, (line_idx, level, title) in enumerate(headings):
        next_line = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        sections.append(_make_section(title, level, line_idx, next_line))

    wire_hierarchy(sections)
    return sections
