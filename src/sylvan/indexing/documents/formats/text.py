"""Plain-text parser -- splits on blank lines into paragraph sections."""

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


@register_parser("text", [".txt"])
def parse_text(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse plain text by splitting on blank lines.

    Each non-empty paragraph becomes a level-1 section.

    Args:
        content: Raw plain text content.
        doc_path: Path to the text file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    content_bytes = content.encode("utf-8")

    paragraphs = re.split(r"\n\s*\n", content)

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()
    byte_cursor = 0

    para_num = 0
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            para_bytes = para.encode("utf-8")
            byte_cursor += len(para_bytes) + 1  # +1 for the split newline
            continue

        para_num += 1
        first_line = stripped.split("\n", 1)[0]
        title = first_line[:80].strip()
        if not title:
            title = f"Paragraph {para_num}"

        body = stripped
        body_bytes_len = len(para.encode("utf-8"))

        para_encoded = stripped.encode("utf-8")
        pos = content_bytes.find(para_encoded, byte_cursor)
        if pos >= 0:
            byte_start = pos
            byte_end = pos + len(para_encoded)
            byte_cursor = byte_end
        else:
            byte_start = byte_cursor
            byte_end = byte_cursor + body_bytes_len
            byte_cursor = byte_end

        level = 1
        slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
        sec = Section(
            section_id=make_section_id(repo, doc_path, slug, level),
            title=title,
            level=level,
            byte_start=byte_start,
            byte_end=byte_end,
            content_hash=compute_section_hash(body),
            tags=extract_tags(body),
            references=extract_references(body),
        )
        sections.append(sec)

    wire_hierarchy(sections)
    return sections
