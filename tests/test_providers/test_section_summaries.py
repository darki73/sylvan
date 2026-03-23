"""Tests for section summarization in providers and the indexing pipeline."""

from __future__ import annotations

import hashlib

import pytest

from sylvan.providers.builtin.heuristic import HeuristicSummaryProvider


class TestSummarizeSectionHeuristic:
    """Test HeuristicSummaryProvider.summarize_section."""

    def setup_method(self):
        self.provider = HeuristicSummaryProvider()

    def test_basic_content(self):
        result = self.provider.summarize_section(
            title="Installation",
            content="Run pip install sylvan to get started. Then configure your project.",
        )
        assert result == "Run pip install sylvan to get started."

    def test_strips_markdown_formatting(self):
        content = (
            "Use the sylvan `CLI` command to index your project. "
            "See [the docs](https://example.com) for details."
        )
        result = self.provider.summarize_section(title="Usage", content=content)
        assert "`" not in result
        assert "](https" not in result
        assert "sylvan" in result

    def test_strips_code_blocks(self):
        content = (
            "```python\nimport sylvan\n```\n\n"
            "After importing, call the main function. More details below."
        )
        result = self.provider.summarize_section(title="Quick Start", content=content)
        assert "```" not in result
        assert "import sylvan" not in result
        assert "After importing" in result

    def test_strips_heading_markers(self):
        content = "## Overview\n\nThis section covers the API. It has many endpoints."
        result = self.provider.summarize_section(title="API", content=content)
        assert result.startswith("Overview") or "This section covers the API." in result

    def test_empty_content_falls_back_to_title(self):
        result = self.provider.summarize_section(title="Empty Section", content="")
        assert result == "Empty Section"

    def test_whitespace_content_falls_back_to_title(self):
        result = self.provider.summarize_section(title="Blank", content="   \n  \n  ")
        assert result == "Blank"

    def test_none_content_falls_back_to_title(self):
        result = self.provider.summarize_section(title="No Content", content="")
        assert result == "No Content"

    def test_truncates_to_150_chars(self):
        long_content = "A" * 200 + ". End."
        result = self.provider.summarize_section(title="Long", content=long_content)
        assert len(result) <= 150

    def test_markdown_links_keep_text(self):
        content = "[Click here](https://example.com) to learn more about the project."
        result = self.provider.summarize_section(title="Links", content=content)
        assert "Click here" in result
        assert "https://" not in result


class TestSummarizeSectionBase:
    """Test the base SummaryProvider.summarize_section fallback behavior."""

    def test_base_fallback_uses_first_sentence(self):
        """Base class falls back to _first_sentence when _generate_summary fails."""
        from sylvan.providers.base import SummaryProvider

        class FailingProvider(SummaryProvider):
            name = "failing"

            def available(self) -> bool:
                return True

            def _generate_summary(self, prompt: str) -> str:
                raise RuntimeError("always fails")

        provider = FailingProvider()
        result = provider.summarize_section(
            title="Fallback",
            content="This is the first sentence. And more text.",
        )
        assert result == "This is the first sentence."

    def test_base_fallback_empty_content_uses_title(self):
        from sylvan.providers.base import SummaryProvider

        class FailingProvider(SummaryProvider):
            name = "failing"

            def available(self) -> bool:
                return True

            def _generate_summary(self, prompt: str) -> str:
                raise RuntimeError("always fails")

        provider = FailingProvider()
        result = provider.summarize_section(title="My Title", content="")
        assert result == "My Title"


class TestGenerateSectionSummaries:
    """Integration test: generate_section_summaries populates section summaries."""

    @pytest.fixture
    async def seeded_repo(self, backend, ctx):
        """Create a repo with a file and sections that have no summaries."""
        from sylvan.database.orm import FileRecord, Repo, Section
        from sylvan.database.orm.models.blob import Blob

        repo = await Repo.create(
            name="test-repo",
            source_path="/test/test-repo",
            indexed_at="2025-01-01T00:00:00",
        )

        content = (
            "# Introduction\n\n"
            "Sylvan is a code intelligence engine. It indexes your codebase.\n\n"
            "## Getting Started\n\n"
            "Install with pip install sylvan. Then run sylvan index.\n\n"
            "## API Reference\n\n"
            "```python\nfrom sylvan import index\n```\n\n"
            "The main entry point is the index function. It accepts a path.\n"
        )
        content_bytes = content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        await Blob.store(content_hash, content_bytes)

        file_rec = await FileRecord.create(
            repo_id=repo.id,
            path="README.md",
            language="markdown",
            content_hash=content_hash,
            byte_size=len(content_bytes),
        )

        # Section 1: Introduction (bytes 0 to end of intro paragraph)
        intro_end = content.index("## Getting Started")
        await Section.create(
            file_id=file_rec.id,
            section_id="test-repo::README.md::introduction#1",
            title="Introduction",
            level=1,
            byte_start=0,
            byte_end=intro_end,
            summary=None,
            tags="[]",
            refs="[]",
        )

        # Section 2: Getting Started
        gs_start = intro_end
        gs_end = content.index("## API Reference")
        await Section.create(
            file_id=file_rec.id,
            section_id="test-repo::README.md::getting-started#2",
            title="Getting Started",
            level=2,
            byte_start=gs_start,
            byte_end=gs_end,
            summary=None,
            tags="[]",
            refs="[]",
        )

        # Section 3: API Reference
        api_start = gs_end
        await Section.create(
            file_id=file_rec.id,
            section_id="test-repo::README.md::api-reference#2",
            title="API Reference",
            level=2,
            byte_start=api_start,
            byte_end=len(content_bytes),
            summary=None,
            tags="[]",
            refs="[]",
        )

        await backend.commit()
        return repo

    @pytest.mark.asyncio
    async def test_generates_summaries_for_sections(self, seeded_repo, backend, ctx):
        from sylvan.database.orm import Section
        from sylvan.indexing.post_processing.summarizer import (
            generate_section_summaries,
        )

        await generate_section_summaries(seeded_repo.id)

        sections = await Section.query().where_raw("file_id > 0").get()
        assert len(sections) == 3

        for sec in sections:
            assert sec.summary is not None, f"Section {sec.section_id} has no summary"
            assert len(sec.summary) > 5, f"Section {sec.section_id} summary too short"

    @pytest.mark.asyncio
    async def test_skips_sections_with_existing_summary(
        self, seeded_repo, backend, ctx
    ):
        from sylvan.database.orm import Section
        from sylvan.indexing.post_processing.summarizer import (
            generate_section_summaries,
        )

        # Set a summary on one section
        sec = await Section.where(
            section_id="test-repo::README.md::introduction#1"
        ).first()
        await sec.update(summary="Already summarized content here.")
        await backend.commit()

        await generate_section_summaries(seeded_repo.id)

        # The pre-existing summary should not be overwritten
        sec = await Section.where(
            section_id="test-repo::README.md::introduction#1"
        ).first()
        assert sec.summary == "Already summarized content here."
