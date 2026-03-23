"""HTML documentation parser -- strips tags and delegates to Markdown logic."""

import re
from html.parser import HTMLParser

from sylvan.database.validation import Section
from sylvan.indexing.documents.formats.markdown import parse_markdown
from sylvan.indexing.documents.registry import register_parser

# Tags whose entire subtree should be discarded.
_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})

# Heading tags we translate to ATX headings.
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


class _HTMLToMarkdown(HTMLParser):
    """Minimal HTML-to-Markdown converter for structured text extraction."""

    def __init__(self) -> None:
        """Initialize the converter state.
        """
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth: int = 0
        self._current_heading: int | None = None
        self._heading_text: list[str] = []
        self._in_pre: bool = False
        self._list_stack: list[str] = []  # "ul" or "ol"
        self._ol_counter: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Process an opening HTML tag.

        Args:
            tag: Lowercase tag name.
            attrs: List of (attribute_name, value) pairs.
        """
        tag = tag.lower()

        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return

        if self._skip_depth:
            return

        if tag in _HEADING_TAGS:
            self._current_heading = _HEADING_TAGS[tag]
            self._heading_text = []
            return

        if tag == "pre":
            self._in_pre = True
            self._parts.append("\n```\n")
            return

        if tag == "br":
            self._parts.append("\n")
            return

        if tag == "p":
            self._parts.append("\n\n")
            return

        if tag in ("ul", "ol"):
            self._list_stack.append(tag)
            if tag == "ol":
                self._ol_counter.append(0)
            return

        if tag == "li":
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ol_counter[-1] += 1
                self._parts.append(f"\n{self._ol_counter[-1]}. ")
            else:
                self._parts.append("\n- ")
            return

        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and href.startswith(("http://", "https://")):
                self._parts.append("[")
            return

        if tag in ("code",) and not self._in_pre:
            self._parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        """Process a closing HTML tag.

        Args:
            tag: Lowercase tag name.
        """
        tag = tag.lower()

        if tag in _SKIP_TAGS:
            self._skip_depth = max(self._skip_depth - 1, 0)
            return

        if self._skip_depth:
            return

        if tag in _HEADING_TAGS and self._current_heading is not None:
            prefix = "#" * self._current_heading
            text = "".join(self._heading_text).strip()
            self._parts.append(f"\n\n{prefix} {text}\n\n")
            self._current_heading = None
            self._heading_text = []
            return

        if tag == "pre":
            self._in_pre = False
            self._parts.append("\n```\n")
            return

        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if tag == "ol" and self._ol_counter:
                self._ol_counter.pop()
            self._parts.append("\n")
            return

        if tag in ("code",) and not self._in_pre:
            self._parts.append("`")

        if tag == "a":
            pass

    def handle_data(self, data: str) -> None:
        """Process text content.

        Args:
            data: Raw text data from the HTML parser.
        """
        if self._skip_depth:
            return
        if self._current_heading is not None:
            self._heading_text.append(data)
            return
        self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        """Convert an HTML entity reference to text.

        Args:
            name: Entity name without the ampersand and semicolon.
        """
        from html import unescape
        self.handle_data(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        """Convert an HTML character reference to text.

        Args:
            name: Character reference value (decimal or hex).
        """
        from html import unescape
        self.handle_data(unescape(f"&#{name};"))

    def get_text(self) -> str:
        """Return the accumulated Markdown text.

        Returns:
            Converted Markdown string.
        """
        return "".join(self._parts)


def _html_to_markdown(html: str) -> str:
    """Convert HTML to a rough Markdown representation.

    Args:
        html: Raw HTML content.

    Returns:
        Approximate Markdown equivalent.
    """
    parser = _HTMLToMarkdown()
    parser.feed(html)
    text = parser.get_text()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


@register_parser("html", [".html", ".htm"])
def parse_html(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse HTML content into sections by converting to Markdown first.

    Args:
        content: Raw HTML content.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects.
    """
    md = _html_to_markdown(content)
    return parse_markdown(md, doc_path, repo)
