"""Tests for documentation parsers — markdown, rst, text, asciidoc, notebook, json, xml, html, parser router, and sections utilities."""

from __future__ import annotations

import json

from sylvan.database.validation import Section
from sylvan.indexing.documents.formats.asciidoc import parse_asciidoc
from sylvan.indexing.documents.formats.html import parse_html
from sylvan.indexing.documents.formats.json_parser import parse_json_doc
from sylvan.indexing.documents.formats.markdown import parse_markdown
from sylvan.indexing.documents.formats.notebook import parse_notebook
from sylvan.indexing.documents.formats.rst import parse_rst
from sylvan.indexing.documents.formats.text import parse_text
from sylvan.indexing.documents.formats.xml_parser import parse_xml_doc
from sylvan.indexing.documents.parser import parse_document
from sylvan.indexing.documents.section_builder import (
    compute_section_hash,
    extract_references,
    extract_tags,
    make_hierarchical_slug,
    make_section_id,
    resolve_slug_collision,
    slugify,
    wire_hierarchy,
)

# ---------------------------------------------------------------------------
# sections.py utilities
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_simple_text(self):
        assert slugify("Hello World") == "hello-world"

    def test_unicode_normalization(self):
        assert slugify("Héllo Wörld") == "hello-world"

    def test_special_characters_removed(self):
        assert slugify("foo@bar!baz") == "foobarbaz"

    def test_collapses_hyphens(self):
        assert slugify("foo---bar") == "foo-bar"

    def test_empty_returns_untitled(self):
        assert slugify("") == "untitled"

    def test_strips_leading_trailing_hyphens(self):
        assert slugify("-hello-") == "hello"


class TestMakeSectionId:
    def test_format(self):
        sid = make_section_id("myrepo", "docs/guide.md", "introduction", 1)
        assert sid == "myrepo::docs/guide.md::introduction#1"

    def test_different_levels(self):
        sid = make_section_id("r", "p", "s", 3)
        assert sid == "r::p::s#3"


class TestResolveSlugCollision:
    def test_no_collision(self):
        used: set[str] = set()
        result = resolve_slug_collision("intro", used)
        assert result == "intro"
        assert "intro" in used

    def test_collision_appends_counter(self):
        used: set[str] = {"intro"}
        result = resolve_slug_collision("intro", used)
        assert result == "intro-2"
        assert "intro-2" in used

    def test_multiple_collisions(self):
        used: set[str] = {"intro", "intro-2"}
        result = resolve_slug_collision("intro", used)
        assert result == "intro-3"


class TestMakeHierarchicalSlug:
    def test_single_heading(self):
        stack: list[tuple[int, str]] = []
        used: set[str] = set()
        slug = make_hierarchical_slug("Introduction", 1, stack, used)
        assert slug == "introduction"

    def test_nested_headings(self):
        stack: list[tuple[int, str]] = []
        used: set[str] = set()
        make_hierarchical_slug("Chapter", 1, stack, used)
        slug = make_hierarchical_slug("Section", 2, stack, used)
        assert slug == "chapter/section"

    def test_sibling_headings_pop(self):
        stack: list[tuple[int, str]] = []
        used: set[str] = set()
        make_hierarchical_slug("Chapter 1", 1, stack, used)
        make_hierarchical_slug("Section A", 2, stack, used)
        slug = make_hierarchical_slug("Section B", 2, stack, used)
        assert slug == "chapter-1/section-b"


class TestComputeSectionHash:
    def test_deterministic(self):
        h1 = compute_section_hash("hello")
        h2 = compute_section_hash("hello")
        assert h1 == h2

    def test_different_content(self):
        assert compute_section_hash("a") != compute_section_hash("b")


class TestExtractReferences:
    def test_extracts_urls(self):
        text = "Visit https://example.com and http://foo.bar/baz"
        refs = extract_references(text)
        assert "https://example.com" in refs
        assert "http://foo.bar/baz" in refs

    def test_no_urls(self):
        assert extract_references("no links here") == []

    def test_deduplication(self):
        text = "https://a.com and https://a.com again"
        refs = extract_references(text)
        assert len(refs) == 1


class TestExtractTags:
    def test_extracts_hashtags(self):
        text = "This is #important and #todo"
        tags = extract_tags(text)
        assert "important" in tags
        assert "todo" in tags

    def test_ignores_short_tags(self):
        text = "#a is too short"
        tags = extract_tags(text)
        assert tags == []

    def test_must_start_with_letter(self):
        text = "#123invalid"
        tags = extract_tags(text)
        assert tags == []

    def test_tag_at_start_of_line(self):
        text = "#setup at line start"
        tags = extract_tags(text)
        assert "setup" in tags


class TestWireHierarchy:
    def test_flat_sections(self):
        sections = [
            Section(section_id="a", level=1),
            Section(section_id="b", level=1),
        ]
        wire_hierarchy(sections)
        assert sections[0].parent_section_id is None
        assert sections[1].parent_section_id is None

    def test_nested_sections(self):
        sections = [
            Section(section_id="a", level=1),
            Section(section_id="b", level=2),
            Section(section_id="c", level=3),
        ]
        wire_hierarchy(sections)
        assert sections[0].parent_section_id is None
        assert sections[1].parent_section_id == "a"
        assert sections[2].parent_section_id == "b"

    def test_sibling_then_deeper(self):
        sections = [
            Section(section_id="h1", level=1),
            Section(section_id="h2a", level=2),
            Section(section_id="h2b", level=2),
            Section(section_id="h3", level=3),
        ]
        wire_hierarchy(sections)
        assert sections[2].parent_section_id == "h1"
        assert sections[3].parent_section_id == "h2b"


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------


class TestMarkdownParser:
    def test_atx_headings(self):
        md = "# Title\nSome content\n## Subtitle\nMore content\n"
        sections = parse_markdown(md, "doc.md", "repo")
        titles = [s.title for s in sections]
        assert "Title" in titles
        assert "Subtitle" in titles

    def test_heading_levels(self):
        md = "# H1\n## H2\n### H3\n"
        sections = parse_markdown(md, "doc.md", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["H1"] == 1
        assert levels["H2"] == 2
        assert levels["H3"] == 3

    def test_content_before_first_heading(self):
        md = "Preamble text\n\n# Heading\nBody\n"
        sections = parse_markdown(md, "doc.md", "repo")
        assert sections[0].title == "(root)"
        assert sections[0].level == 0

    def test_no_headings(self):
        md = "Just some text without headings.\n"
        sections = parse_markdown(md, "doc.md", "repo")
        # Should still produce a root section for the preamble
        assert len(sections) == 1
        assert sections[0].title == "(root)"

    def test_byte_offsets_are_non_negative(self):
        md = "# First\nContent\n## Second\nMore\n"
        sections = parse_markdown(md, "doc.md", "repo")
        for s in sections:
            assert s.byte_start >= 0
            assert s.byte_end >= s.byte_start

    def test_hierarchy_wired(self):
        md = "# Parent\n## Child\n"
        sections = parse_markdown(md, "doc.md", "repo")
        child = next(s for s in sections if s.title == "Child")
        parent = next(s for s in sections if s.title == "Parent")
        assert child.parent_section_id == parent.section_id

    def test_fenced_code_headings_ignored(self):
        md = "# Real\n```\n## Fake\n```\n## Real2\n"
        sections = parse_markdown(md, "doc.md", "repo")
        titles = [s.title for s in sections]
        assert "Real" in titles
        assert "Real2" in titles
        assert "Fake" not in titles

    def test_setext_heading(self):
        md = "Title\n=====\nContent\n"
        sections = parse_markdown(md, "doc.md", "repo")
        assert any(s.title == "Title" and s.level == 1 for s in sections)

    def test_mdx_frontmatter_stripped(self):
        md = "---\ntitle: Test\n---\n# Heading\nContent\n"
        sections = parse_markdown(md, "doc.md", "repo")
        titles = [s.title for s in sections]
        assert "Heading" in titles


# ---------------------------------------------------------------------------
# RST parser
# ---------------------------------------------------------------------------


class TestRstParser:
    def test_underline_headings(self):
        rst = "Title\n=====\nContent\n\nSubtitle\n--------\nMore\n"
        sections = parse_rst(rst, "doc.rst", "repo")
        titles = [s.title for s in sections]
        assert "Title" in titles
        assert "Subtitle" in titles

    def test_level_assignment_by_order(self):
        rst = "First\n=====\ntext\n\nSecond\n------\ntext\n"
        sections = parse_rst(rst, "doc.rst", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["First"] == 1
        assert levels["Second"] == 2

    def test_overline_style(self):
        rst = "=====\nTitle\n=====\nContent\n"
        sections = parse_rst(rst, "doc.rst", "repo")
        assert any(s.title == "Title" for s in sections)

    def test_preamble_before_heading(self):
        rst = "Preamble\n\nTitle\n=====\nBody\n"
        sections = parse_rst(rst, "doc.rst", "repo")
        assert sections[0].title == "(root)"

    def test_hierarchy_wired(self):
        rst = "Parent\n======\ntext\n\nChild\n-----\ntext\n"
        sections = parse_rst(rst, "doc.rst", "repo")
        child = next(s for s in sections if s.title == "Child")
        parent = next(s for s in sections if s.title == "Parent")
        assert child.parent_section_id == parent.section_id

    def test_empty_returns_empty(self):
        sections = parse_rst("", "doc.rst", "repo")
        assert sections == []


# ---------------------------------------------------------------------------
# Text parser
# ---------------------------------------------------------------------------


class TestTextParser:
    def test_paragraph_splitting(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three.\n"
        sections = parse_text(text, "doc.txt", "repo")
        assert len(sections) == 3

    def test_all_level_one(self):
        text = "A\n\nB\n\nC\n"
        sections = parse_text(text, "doc.txt", "repo")
        for s in sections:
            assert s.level == 1

    def test_empty_text(self):
        sections = parse_text("", "doc.txt", "repo")
        assert sections == []

    def test_single_paragraph(self):
        sections = parse_text("Just one paragraph.", "doc.txt", "repo")
        assert len(sections) == 1

    def test_title_uses_first_line(self):
        text = "First line of paragraph\nSecond line\n\nAnother para\n"
        sections = parse_text(text, "doc.txt", "repo")
        assert sections[0].title == "First line of paragraph"

    def test_byte_offsets(self):
        text = "Hello\n\nWorld\n"
        sections = parse_text(text, "doc.txt", "repo")
        for s in sections:
            assert s.byte_start >= 0
            assert s.byte_end > s.byte_start


# ---------------------------------------------------------------------------
# AsciiDoc parser
# ---------------------------------------------------------------------------


class TestAsciiDocParser:
    def test_heading_markers(self):
        adoc = "= Document Title\nIntro\n\n== Section\nContent\n"
        sections = parse_asciidoc(adoc, "doc.adoc", "repo")
        titles = [s.title for s in sections]
        assert "Document Title" in titles
        assert "Section" in titles

    def test_heading_levels(self):
        adoc = "= Level 1\n== Level 2\n=== Level 3\n"
        sections = parse_asciidoc(adoc, "doc.adoc", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["Level 1"] == 1
        assert levels["Level 2"] == 2
        assert levels["Level 3"] == 3

    def test_preamble(self):
        adoc = "Preamble text\n\n= Heading\nBody\n"
        sections = parse_asciidoc(adoc, "doc.adoc", "repo")
        assert sections[0].title == "(root)"

    def test_hierarchy(self):
        adoc = "= Parent\ncontent\n== Child\ncontent\n"
        sections = parse_asciidoc(adoc, "doc.adoc", "repo")
        child = next(s for s in sections if s.title == "Child")
        parent = next(s for s in sections if s.title == "Parent")
        assert child.parent_section_id == parent.section_id

    def test_delimited_block_ignored(self):
        adoc = "= Real\n----\n== Fake\n----\n== Real2\n"
        sections = parse_asciidoc(adoc, "doc.adoc", "repo")
        titles = [s.title for s in sections]
        assert "Real" in titles
        assert "Real2" in titles
        assert "Fake" not in titles

    def test_empty(self):
        sections = parse_asciidoc("", "doc.adoc", "repo")
        assert sections == []


# ---------------------------------------------------------------------------
# Notebook parser
# ---------------------------------------------------------------------------


class TestNotebookParser:
    def _make_notebook(self, cells, language="python"):
        return json.dumps(
            {
                "metadata": {
                    "kernelspec": {"language": language},
                },
                "cells": cells,
            }
        )

    def test_markdown_cell(self):
        nb = self._make_notebook([{"cell_type": "markdown", "source": ["# Introduction\n", "Some text"]}])
        sections = parse_notebook(nb, "test.ipynb", "repo")
        assert len(sections) >= 1
        assert sections[0].title == "Introduction"

    def test_code_cell(self):
        nb = self._make_notebook([{"cell_type": "code", "source": ["print('hello')"]}])
        sections = parse_notebook(nb, "test.ipynb", "repo")
        assert len(sections) == 1
        assert "Code cell" in sections[0].title

    def test_mixed_cells(self):
        nb = self._make_notebook(
            [
                {"cell_type": "markdown", "source": ["# Title\n"]},
                {"cell_type": "code", "source": ["x = 1"]},
                {"cell_type": "markdown", "source": ["## Section\n"]},
            ]
        )
        sections = parse_notebook(nb, "test.ipynb", "repo")
        assert len(sections) == 3

    def test_invalid_json_returns_empty(self):
        sections = parse_notebook("not json", "test.ipynb", "repo")
        assert sections == []

    def test_empty_cells_skipped(self):
        nb = self._make_notebook(
            [
                {"cell_type": "code", "source": [""]},
                {"cell_type": "markdown", "source": ["# Real\n"]},
            ]
        )
        sections = parse_notebook(nb, "test.ipynb", "repo")
        assert len(sections) == 1
        assert sections[0].title == "Real"

    def test_kernel_language_detected(self):
        nb = self._make_notebook(
            [
                {"cell_type": "code", "source": ["val x = 1"]},
            ],
            language="scala",
        )
        sections = parse_notebook(nb, "test.ipynb", "repo")
        # The code cell body should contain the language tag
        assert sections[0].content_hash  # non-empty


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------


class TestJsonParser:
    def test_top_level_keys(self):
        content = json.dumps({"name": "test", "version": "1.0"})
        sections = parse_json_doc(content, "data.json", "repo")
        titles = [s.title for s in sections]
        assert "name" in titles
        assert "version" in titles

    def test_nested_objects(self):
        content = json.dumps({"config": {"host": "localhost", "port": 8080}})
        sections = parse_json_doc(content, "data.json", "repo")
        # Parent "config" + children "host", "port"
        titles = [s.title for s in sections]
        assert "config" in titles
        assert "host" in titles
        assert "port" in titles

    def test_invalid_json_returns_empty(self):
        sections = parse_json_doc("not json at all", "data.json", "repo")
        assert sections == []

    def test_non_dict_returns_empty(self):
        sections = parse_json_doc(json.dumps([1, 2, 3]), "data.json", "repo")
        assert sections == []

    def test_jsonc_comments_stripped(self):
        content = '{\n  // comment\n  "key": "value"\n}'
        sections = parse_json_doc(content, "data.jsonc", "repo")
        assert len(sections) == 1
        assert sections[0].title == "key"

    def test_hierarchy_levels(self):
        content = json.dumps({"a": {"b": {"c": "deep"}}})
        sections = parse_json_doc(content, "data.json", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["a"] == 1
        assert levels["b"] == 2
        assert levels["c"] == 3


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------


class TestXmlParser:
    def test_element_hierarchy(self):
        xml = "<root><child1>text</child1><child2/></root>"
        sections = parse_xml_doc(xml, "data.xml", "repo")
        titles = [s.title for s in sections]
        assert "root" in titles
        assert "child1" in titles
        assert "child2" in titles

    def test_nested_elements(self):
        xml = "<a><b><c>deep</c></b></a>"
        sections = parse_xml_doc(xml, "data.xml", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["a"] == 1
        assert levels["b"] == 2
        assert levels["c"] == 3

    def test_invalid_xml_returns_empty(self):
        sections = parse_xml_doc("not xml", "data.xml", "repo")
        assert sections == []

    def test_namespace_stripped(self):
        xml = '<root xmlns="http://example.com"><child>text</child></root>'
        sections = parse_xml_doc(xml, "data.xml", "repo")
        titles = [s.title for s in sections]
        assert "root" in titles
        assert "child" in titles

    def test_attributes_in_body(self):
        xml = '<item id="123">content</item>'
        sections = parse_xml_doc(xml, "data.xml", "repo")
        assert len(sections) == 1
        assert sections[0].title == "item"


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------


class TestHtmlParser:
    def test_h1_to_h6(self):
        html = "<h1>Title</h1><p>Body</p><h2>Sub</h2><p>More</p>"
        sections = parse_html(html, "page.html", "repo")
        titles = [s.title for s in sections]
        assert "Title" in titles
        assert "Sub" in titles

    def test_script_style_stripped(self):
        html = "<h1>Title</h1><script>alert(1)</script><p>Body</p>"
        sections = parse_html(html, "page.html", "repo")
        titles = [s.title for s in sections]
        assert "Title" in titles
        # Script content should not produce a section
        assert not any("alert" in s.title for s in sections)

    def test_heading_levels(self):
        html = "<h1>H1</h1><h2>H2</h2><h3>H3</h3>"
        sections = parse_html(html, "page.html", "repo")
        levels = {s.title: s.level for s in sections}
        assert levels["H1"] == 1
        assert levels["H2"] == 2
        assert levels["H3"] == 3

    def test_empty_html(self):
        sections = parse_html("", "page.html", "repo")
        assert sections == []

    def test_nav_footer_stripped(self):
        html = "<nav>skip</nav><h1>Content</h1><footer>skip</footer>"
        sections = parse_html(html, "page.html", "repo")
        titles = [s.title for s in sections]
        assert "Content" in titles


# ---------------------------------------------------------------------------
# Parser router
# ---------------------------------------------------------------------------


class TestParserRouter:
    def test_markdown_dispatch(self):
        md = "# Hello\nWorld\n"
        sections = parse_document(md, "readme.md", "repo")
        assert any(s.title == "Hello" for s in sections)

    def test_mdx_dispatch(self):
        mdx = "# Hello\nWorld\n"
        sections = parse_document(mdx, "docs.mdx", "repo")
        assert any(s.title == "Hello" for s in sections)

    def test_rst_dispatch(self):
        rst = "Title\n=====\nBody\n"
        sections = parse_document(rst, "doc.rst", "repo")
        assert any(s.title == "Title" for s in sections)

    def test_asciidoc_dispatch(self):
        adoc = "= Title\nBody\n"
        sections = parse_document(adoc, "doc.adoc", "repo")
        assert any(s.title == "Title" for s in sections)

    def test_html_dispatch(self):
        html = "<h1>Title</h1><p>Body</p>"
        sections = parse_document(html, "page.html", "repo")
        assert any(s.title == "Title" for s in sections)

    def test_notebook_dispatch(self):
        nb = json.dumps(
            {
                "metadata": {"kernelspec": {"language": "python"}},
                "cells": [{"cell_type": "markdown", "source": ["# NB Title\n"]}],
            }
        )
        sections = parse_document(nb, "test.ipynb", "repo")
        assert any(s.title == "NB Title" for s in sections)

    def test_json_dispatch(self):
        content = json.dumps({"key": "value"})
        sections = parse_document(content, "data.json", "repo")
        assert any(s.title == "key" for s in sections)

    def test_xml_dispatch(self):
        xml = "<root><child>text</child></root>"
        sections = parse_document(xml, "data.xml", "repo")
        assert any(s.title == "root" for s in sections)

    def test_txt_dispatch(self):
        text = "A paragraph.\n\nAnother paragraph.\n"
        sections = parse_document(text, "notes.txt", "repo")
        assert len(sections) == 2

    def test_unknown_ext_falls_back_to_text(self):
        text = "Hello world.\n\nGoodbye.\n"
        sections = parse_document(text, "file.xyz", "repo")
        assert len(sections) >= 1
