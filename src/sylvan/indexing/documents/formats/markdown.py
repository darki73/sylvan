"""Markdown documentation parser.

Backed by ``sylvan-indexing`` (Rust) since v2.x. The Rust side uses
``pulldown-cmark`` (a real CommonMark parser) which fixes the
long-standing ``_strip_mdx`` regression that dropped ~50% of headings
from large `.md` docs sets.
"""

from __future__ import annotations

from sylvan._rust import parse_markdown as _rust_parse_markdown
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
    raw_sections = _rust_parse_markdown(content)

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()

    for entry in raw_sections:
        title = entry["title"]
        level = int(entry["level"])
        body = entry["body"]
        slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
        sections.append(
            Section(
                section_id=make_section_id(repo, doc_path, slug, level),
                title=title,
                level=level,
                byte_start=int(entry["byte_start"]),
                byte_end=int(entry["byte_end"]),
                content_hash=compute_section_hash(body),
                tags=extract_tags(body),
                references=extract_references(body),
            )
        )

    wire_hierarchy(sections)
    return sections
