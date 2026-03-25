"""XML / SVG documentation parser -- element hierarchy as sections."""

import xml.etree.ElementTree as ET

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

_MAX_DEPTH = 4


def _strip_ns(tag: str) -> str:
    """Remove XML namespace prefix from a tag name.

    Args:
        tag: Full tag name, possibly including a namespace URI.

    Returns:
        Tag name without the namespace prefix.
    """
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _element_text(elem: ET.Element) -> str:
    """Return the concatenated text of an element (direct text + tail of children).

    Args:
        elem: XML element to extract text from.

    Returns:
        Space-joined text content.
    """
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text.strip())
    for child in elem:
        child_text = _element_text(child)
        if child_text:
            parts.append(child_text)
        if child.tail:
            parts.append(child.tail.strip())
    return " ".join(parts)


def _walk_element(
    elem: ET.Element,
    depth: int,
    doc_path: str,
    repo: str,
    sections: list[Section],
    slug_stack: list[tuple[int, str]],
    used_slugs: set[str],
    byte_cursor: list[int],
) -> None:
    """Recursively create sections from XML elements up to *_MAX_DEPTH*.

    Args:
        elem: Current XML element.
        depth: Current nesting depth.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.
        sections: Accumulator list for generated sections.
        slug_stack: Mutable ancestry stack for hierarchical slugs.
        used_slugs: Mutable set of already-used slugs.
        byte_cursor: Mutable single-element list tracking byte position.
    """
    tag_name = _strip_ns(elem.tag)
    level = min(depth, _MAX_DEPTH)

    body_parts = [f"<{tag_name}>"]
    for attr_name, attr_val in elem.attrib.items():
        body_parts.append(f"  {_strip_ns(attr_name)}={attr_val}")
    text = _element_text(elem)
    if text:
        body_parts.append(text)
    body = "\n".join(body_parts) + "\n"
    body_bytes = body.encode("utf-8")

    start = byte_cursor[0]
    byte_cursor[0] += len(body_bytes)

    slug = make_hierarchical_slug(tag_name, level, slug_stack, used_slugs)
    sec = Section(
        section_id=make_section_id(repo, doc_path, slug, level),
        title=tag_name,
        level=level,
        byte_start=start,
        byte_end=byte_cursor[0],
        content_hash=compute_section_hash(body),
        tags=extract_tags(body),
        references=extract_references(body),
    )
    sections.append(sec)

    if depth < _MAX_DEPTH:
        for child in elem:
            _walk_element(
                child,
                depth + 1,
                doc_path,
                repo,
                sections,
                slug_stack,
                used_slugs,
                byte_cursor,
            )


@register_parser("xml", [".xml", ".svg"])
def parse_xml_doc(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse an XML or SVG file into sections based on element hierarchy.

    Args:
        content: Raw XML content.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    try:
        root = ET.fromstring(content)  # noqa: S314 -- parsing indexed source files, not untrusted input
    except ET.ParseError:
        return []

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()
    byte_cursor = [0]

    _walk_element(root, 1, doc_path, repo, sections, slug_stack, used_slugs, byte_cursor)

    wire_hierarchy(sections)
    return sections
