"""Tests for sylvan.tools.definitions — tool schema validation."""

from __future__ import annotations

from sylvan.tools.definitions.analysis import TOOLS as ANALYSIS_TOOLS
from sylvan.tools.definitions.core import TOOLS as CORE_TOOLS
from sylvan.tools.definitions.support import TOOLS as SUPPORT_TOOLS


class TestCoreTools:
    def test_core_tools_defined(self):
        assert len(CORE_TOOLS) > 0

    def test_core_tools_contain_expected_names(self):
        names = {t.name for t in CORE_TOOLS}
        assert "search_symbols" in names
        assert "index_folder" in names
        assert "get_symbol" in names
        assert "get_file_outline" in names
        assert "list_repos" in names
        assert "search_text" in names


class TestAnalysisTools:
    def test_analysis_tools_defined(self):
        assert len(ANALYSIS_TOOLS) > 0

    def test_analysis_tools_contain_expected_names(self):
        names = {t.name for t in ANALYSIS_TOOLS}
        assert "get_blast_radius" in names
        assert "get_class_hierarchy" in names
        assert "get_references" in names
        assert "get_quality" in names
        assert "get_quality_report" in names


class TestSupportTools:
    def test_support_tools_defined(self):
        assert len(SUPPORT_TOOLS) > 0

    def test_support_tools_contain_expected_names(self):
        names = {t.name for t in SUPPORT_TOOLS}
        assert "search_sections" in names
        assert "get_section" in names
        assert "get_toc" in names
        assert "scaffold" in names
        assert "add_library" in names


class TestAllTools:
    def test_all_tools_have_descriptions(self):
        for tool in [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]:
            assert tool.description, f"{tool.name} missing description"

    def test_no_duplicate_tool_names(self):
        all_tools = [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]
        names = [t.name for t in all_tools]
        assert len(names) == len(set(names)), (
            f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"
        )

    def test_all_tools_have_input_schemas(self):
        for tool in [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]:
            assert tool.inputSchema is not None, f"{tool.name} missing inputSchema"
            assert isinstance(tool.inputSchema, dict), f"{tool.name} inputSchema not a dict"

    def test_all_tools_have_name_strings(self):
        for tool in [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]:
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0

    def test_tools_with_required_params_have_them_in_schema(self):
        for tool in [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]:
            schema = tool.inputSchema
            if "required" in schema:
                properties = schema.get("properties", {})
                for req in schema["required"]:
                    assert req in properties, (
                        f"{tool.name}: required param '{req}' not in properties"
                    )

    def test_total_tool_count(self):
        """Sanity check: we should have a reasonable number of tools total."""
        total = len(CORE_TOOLS) + len(ANALYSIS_TOOLS) + len(SUPPORT_TOOLS)
        assert total >= 20, f"Expected at least 20 tools, got {total}"
