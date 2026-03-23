"""Helper utilities for documentation section parsing."""

import hashlib
import re
import unicodedata

from sylvan.database.validation import Section


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug.

    Normalises unicode, lowercases, strips non-alphanumeric characters (except
    hyphens), collapses runs of hyphens, and trims leading/trailing hyphens.

    Args:
        text: Raw heading or title text.

    Returns:
        A URL-safe slug string.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text or "untitled"


def make_section_id(repo: str, doc_path: str, slug: str, level: int) -> str:
    """Build a stable section ID: ``{repo}::{doc_path}::{slug}#{level}``.

    Args:
        repo: Repository name.
        doc_path: Path to the document file.
        slug: URL-safe section slug.
        level: Heading level (0 for root, 1+ for headings).

    Returns:
        A unique section identifier string.
    """
    return f"{repo}::{doc_path}::{slug}#{level}"


def resolve_slug_collision(slug: str, used_slugs: set[str]) -> str:
    """Append ``-2``, ``-3``, ... until the slug is unique within *used_slugs*.

    The winning slug is added to *used_slugs* before returning.

    Args:
        slug: Candidate slug to deduplicate.
        used_slugs: Mutable set of already-used slugs.

    Returns:
        A unique slug (possibly with a numeric suffix).
    """
    if slug not in used_slugs:
        used_slugs.add(slug)
        return slug

    counter = 2
    while f"{slug}-{counter}" in used_slugs:
        counter += 1
    unique = f"{slug}-{counter}"
    used_slugs.add(unique)
    return unique


def make_hierarchical_slug(
    heading_text: str,
    heading_level: int,
    slug_stack: list[tuple[int, str]],
    used_slugs: set[str],
) -> str:
    """Create a stable hierarchical slug prefixed with the ancestor chain.

    *slug_stack* is a mutable list of ``(level, slug_fragment)`` pairs
    representing the current heading ancestry.  This function pops entries
    whose level is >= the incoming heading level, pushes the new entry, then
    builds a ``/``-joined slug from the remaining stack.

    Args:
        heading_text: Raw heading text to slugify.
        heading_level: Numeric heading level.
        slug_stack: Mutable ancestry stack of (level, fragment) pairs.
        used_slugs: Mutable set of already-used slugs for collision resolution.

    Returns:
        The final collision-resolved hierarchical slug.
    """
    fragment = slugify(heading_text)

    # Pop siblings and deeper headings.
    while slug_stack and slug_stack[-1][0] >= heading_level:
        slug_stack.pop()

    slug_stack.append((heading_level, fragment))

    hierarchical = "/".join(part for _, part in slug_stack)
    return resolve_slug_collision(hierarchical, used_slugs)


def compute_section_hash(content: str) -> str:
    """Return the SHA-256 hex digest of *content* (UTF-8 encoded).

    Args:
        content: Section body text.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_URL_RE = re.compile(
    r"https?://[^\s\)\]\}>\"'`,;]+",
    re.ASCII,
)


def extract_references(content: str) -> list[str]:
    """Extract URLs from *content*.

    Args:
        content: Text to scan for URLs.

    Returns:
        Deduplicated list of URLs found.
    """
    return list(dict.fromkeys(_URL_RE.findall(content)))


_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z][A-Za-z0-9_-]{1,})", re.MULTILINE)


def extract_tags(content: str) -> list[str]:
    """Extract ``#hashtag`` style tags from *content*.

    Tags must start with a letter and be at least 2 characters after ``#``.

    Args:
        content: Text to scan for hashtags.

    Returns:
        Deduplicated list of tag strings (without the ``#`` prefix).
    """
    return list(dict.fromkeys(_TAG_RE.findall(content)))


def wire_hierarchy(sections: list[Section]) -> list[Section]:
    """Set *parent_section_id* on each section using a stack-based O(n) walk.

    The algorithm maintains a stack of ``(level, section_id)`` entries.  For
    each section we pop until we find a parent with a strictly smaller level,
    then link to it.

    Args:
        sections: Mutable list of sections to wire together.

    Returns:
        The same list with parent_section_id populated.
    """
    stack: list[tuple[int, str]] = []

    for sec in sections:
        # Pop entries at the same level or deeper.
        while stack and stack[-1][0] >= sec.level:
            stack.pop()

        if stack:
            sec.parent_section_id = stack[-1][1]
        else:
            sec.parent_section_id = None

        stack.append((sec.level, sec.section_id))

    return sections
