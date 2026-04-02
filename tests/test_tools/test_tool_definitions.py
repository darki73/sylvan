"""Tests for tool registry - schema validation and completeness."""

from __future__ import annotations

# Trigger registration of all tool modules
from sylvan.server import _import_all_tool_modules
from sylvan.tools.base.tool import get_all_tools, get_registry

_import_all_tool_modules()


class TestToolRegistry:
    def test_tools_registered(self):
        registry = get_registry()
        assert len(registry) > 0

    def test_expected_tools_present(self):
        registry = get_registry()
        names = set(registry)
        assert "search_symbols" in names
        assert "index_folder" in names
        assert "get_symbol" in names
        assert "get_file_outline" in names
        assert "list_repos" in names
        assert "search_text" in names
        assert "get_blast_radius" in names
        assert "get_class_hierarchy" in names
        assert "get_references" in names
        assert "get_quality" in names
        assert "search_sections" in names
        assert "get_section" in names
        assert "get_toc" in names
        assert "scaffold" in names
        assert "add_library" in names

    def test_total_tool_count(self):
        registry = get_registry()
        assert len(registry) >= 20


class TestToolSchemas:
    def test_all_tools_have_descriptions(self):
        for tool in get_all_tools():
            assert tool.description, f"{tool.name} missing description"

    def test_no_duplicate_tool_names(self):
        tools = get_all_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names)), f"Duplicate: {[n for n in names if names.count(n) > 1]}"

    def test_all_tools_generate_valid_schemas(self):
        for tool in get_all_tools():
            mcp_tool = tool.to_mcp_tool()
            assert mcp_tool.inputSchema is not None, f"{tool.name} missing inputSchema"
            assert isinstance(mcp_tool.inputSchema, dict), f"{tool.name} inputSchema not a dict"

    def test_all_tools_have_name_strings(self):
        for tool in get_all_tools():
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0

    def test_required_params_exist_in_properties(self):
        for tool in get_all_tools():
            schema = tool.Params.to_schema()
            if "required" in schema:
                properties = schema.get("properties", {})
                for req in schema["required"]:
                    assert req in properties, f"{tool.name}: required param '{req}' not in properties"

    def test_all_tools_have_valid_category(self):
        valid = {"search", "retrieval", "analysis", "indexing", "meta"}
        for tool in get_all_tools():
            assert tool.category in valid, f"{tool.name} has invalid category '{tool.category}'"
