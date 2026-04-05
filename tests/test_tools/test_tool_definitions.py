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
        assert "find_code" in names
        assert "index_project" in names
        assert "read_symbol" in names
        assert "whats_in_file" in names
        assert "indexed_repos" in names
        assert "find_text" in names
        assert "what_breaks_if_i_change" in names
        assert "inheritance_chain" in names
        assert "who_calls_this" in names
        assert "find_tech_debt" in names
        assert "find_docs" in names
        assert "read_doc_section" in names
        assert "doc_table_of_contents" in names
        assert "generate_project_docs" in names
        assert "index_library_source" in names

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
