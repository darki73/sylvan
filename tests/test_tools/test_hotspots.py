"""Tests for the get_hotspots tool and git churn module."""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from sylvan.git.churn import hotspot_score


class TestHotspotScore:
    def test_zero_commits(self):
        assert hotspot_score(5, 0) == 0.0

    def test_basic_score(self):
        score = hotspot_score(10, 10)
        expected = round(10 * math.log(11), 2)
        assert score == expected

    def test_low_complexity(self):
        score = hotspot_score(1, 100)
        assert score == round(math.log(101), 2)

    def test_high_complexity_low_churn(self):
        score = hotspot_score(50, 1)
        expected = round(50 * math.log(2), 2)
        assert score == expected


class TestChurnAssessment:
    def test_stable(self):
        from sylvan.git.churn import get_file_churn

        with patch("sylvan.git.churn.run_git", return_value=None):
            result = get_file_churn("/fake/repo", "src/main.py", days=90)
            assert result["assessment"] == "stable"
            assert result["commit_count"] == 0

    def test_churn_with_mock_data(self):
        from sylvan.git.churn import get_file_churn

        mock_output = (
            "abc123|2025-01-01 12:00:00 +0000|Alice\n"
            "def456|2025-01-02 12:00:00 +0000|Bob\n"
            "ghi789|2025-01-03 12:00:00 +0000|Alice\n"
        )
        with patch("sylvan.git.churn.run_git", return_value=mock_output):
            result = get_file_churn("/fake/repo", "src/main.py", days=90)
            assert result["commit_count"] == 3
            assert result["unique_authors"] == 2
            assert result["first_seen"] is not None
            assert result["last_modified"] is not None
            assert result["churn_per_week"] > 0

    def test_empty_git_output(self):
        from sylvan.git.churn import get_file_churn

        with patch("sylvan.git.churn.run_git", return_value=""):
            result = get_file_churn("/fake/repo", "src/main.py", days=90)
            assert result["commit_count"] == 0
            assert result["assessment"] == "stable"


class TestGetHotspotsTool:
    @pytest.mark.asyncio
    async def test_tool_registration(self):
        from sylvan.tools.analysis.get_hotspots import GetHotspots

        tool = GetHotspots()
        assert tool.name == "get_hotspots"
        assert tool.category == "analysis"

    @pytest.mark.asyncio
    async def test_tool_params(self):
        from sylvan.tools.analysis.get_hotspots import GetHotspots

        tool = GetHotspots()
        schema = tool.Params.to_schema()
        props = schema["properties"]
        assert "repo" in props
        assert "days" in props
        assert "top_n" in props
        assert "min_complexity" in props

    @pytest.mark.asyncio
    async def test_tool_has_mcp_schema(self):
        from sylvan.tools.analysis.get_hotspots import GetHotspots

        tool = GetHotspots()
        mcp = tool.to_mcp_tool()
        assert mcp.name == "get_hotspots"
        assert "hotspot" in mcp.description.lower() or "complex" in mcp.description.lower()
