"""Tests for sylvan.server — handler registration, tool listing, shutdown."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetHandlers:
    """Tests for _get_handlers() dispatch table."""

    def test_returns_dict(self):
        """_get_handlers returns a dict."""
        from sylvan.server import _get_handlers

        # Clear the functools.cache so we always get a fresh result
        _get_handlers.cache_clear()
        handlers = _get_handlers()
        assert isinstance(handlers, dict)

    def test_has_minimum_tool_count(self):
        """Handler table has at least 30 entries (34+ tools defined)."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        assert len(handlers) >= 30

    def test_contains_core_tools(self):
        """Core tools are present in the handler table."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        expected_tools = [
            "search_symbols",
            "index_folder",
            "index_file",
            "get_symbol",
            "get_symbols",
            "get_file_outline",
            "get_file_tree",
            "list_repos",
            "search_sections",
            "get_section",
            "get_sections",
            "get_toc",
            "get_toc_tree",
            "get_repo_outline",
        ]
        for tool in expected_tools:
            assert tool in handlers, f"Missing core tool: {tool}"

    def test_contains_analysis_tools(self):
        """Analysis tools are present in the handler table."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        expected_tools = [
            "get_blast_radius",
            "get_class_hierarchy",
            "get_references",
            "find_importers",
            "get_related",
            "get_quality",
            "get_quality_report",
            "get_git_context",
        ]
        for tool in expected_tools:
            assert tool in handlers, f"Missing analysis tool: {tool}"

    def test_contains_workspace_tools(self):
        """Workspace tools are present in the handler table."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        expected_tools = [
            "index_workspace",
            "workspace_search",
            "workspace_blast_radius",
            "add_to_workspace",
            "pin_library",
        ]
        for tool in expected_tools:
            assert tool in handlers, f"Missing workspace tool: {tool}"

    def test_contains_library_tools(self):
        """Library tools are present in the handler table."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        expected_tools = [
            "add_library",
            "list_libraries",
            "remove_library",
            "check_library_versions",
            "compare_library_versions",
        ]
        for tool in expected_tools:
            assert tool in handlers, f"Missing library tool: {tool}"

    def test_contains_meta_tools(self):
        """Meta and support tools are present in the handler table."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        expected_tools = [
            "suggest_queries",
            "get_session_stats",
            "scaffold",
            "get_dashboard_url",
            "get_logs",
        ]
        for tool in expected_tools:
            assert tool in handlers, f"Missing meta tool: {tool}"

    def test_all_handlers_are_callable(self):
        """Every handler in the dispatch table must be callable."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        handlers = _get_handlers()
        for name, handler in handlers.items():
            assert callable(handler), f"Handler for {name!r} is not callable"

    def test_cache_returns_same_object(self):
        """_get_handlers is cached — repeated calls return the same dict."""
        from sylvan.server import _get_handlers

        _get_handlers.cache_clear()
        first = _get_handlers()
        second = _get_handlers()
        assert first is second


class TestShutdownBackendSync:
    """Tests for _shutdown_backend_sync()."""

    def test_noop_when_backend_is_none(self):
        """When _backend is None, shutdown is a silent no-op."""
        import sylvan.server as srv

        original = srv._backend
        try:
            srv._backend = None
            srv._shutdown_backend_sync()  # Should not raise
        finally:
            srv._backend = original

    def test_noop_when_connection_is_none(self):
        """When _backend exists but _connection is None, shutdown handles it."""
        import sylvan.server as srv

        original = srv._backend
        try:
            mock_backend = MagicMock()
            mock_backend._connection = None
            srv._backend = mock_backend
            srv._shutdown_backend_sync()  # Should not raise
            assert srv._backend is None  # Gets cleared
        finally:
            srv._backend = original


class TestListTools:
    """Tests for list_tools()."""

    async def test_returns_list(self):
        """list_tools returns a list of Tool objects."""
        from sylvan.server import list_tools

        tools = await list_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 30

    async def test_tools_have_names(self):
        """Every tool has a non-empty name."""
        from sylvan.server import list_tools

        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "name")
            assert tool.name

    async def test_tools_have_descriptions(self):
        """Every tool has a description."""
        from sylvan.server import list_tools

        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "description")
            assert tool.description

    async def test_tool_names_are_unique(self):
        """No duplicate tool names."""
        from sylvan.server import list_tools

        tools = await list_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names)), f"Duplicate tools: {[n for n in names if names.count(n) > 1]}"

    async def test_tools_have_input_schemas(self):
        """Every tool has an inputSchema."""
        from sylvan.server import list_tools

        tools = await list_tools()
        for tool in tools:
            assert hasattr(tool, "inputSchema")
            assert isinstance(tool.inputSchema, dict)

    async def test_handler_exists_for_every_tool(self):
        """Every registered tool has a matching handler."""
        from sylvan.server import _get_handlers, list_tools

        _get_handlers.cache_clear()
        tools = await list_tools()
        handlers = _get_handlers()
        for tool in tools:
            assert tool.name in handlers, f"Tool {tool.name!r} has no handler"


class TestGetDashboardUrl:
    """Tests for the _get_dashboard_url helper."""

    async def test_returns_not_running_when_no_dashboard(self):
        """When dashboard is not started, returns not_running status."""
        from sylvan.server import _get_dashboard_url

        with patch("sylvan.dashboard.server.get_dashboard_url", return_value=None):
            result = await _get_dashboard_url()
            assert result["status"] == "not_running"
            assert "message" in result

    async def test_returns_url_when_dashboard_running(self):
        """When dashboard is running, returns the URL."""
        from sylvan.server import _get_dashboard_url

        with patch("sylvan.dashboard.server.get_dashboard_url", return_value="http://127.0.0.1:9999"):
            result = await _get_dashboard_url()
            assert result["status"] == "running"
            assert result["url"] == "http://127.0.0.1:9999"


class TestGetUsageStats:
    """Tests for _get_usage_stats()."""

    async def test_returns_session_stats(self, ctx):
        """Usage stats include session-level data."""
        from sylvan.server import _get_usage_stats

        with patch("sylvan.server._get_or_create_backend", return_value=ctx.backend):
            result = await _get_usage_stats({})
            assert "session" in result
            assert "overall" in result
            assert "cache" in result

    async def test_with_nonexistent_repo(self, ctx):
        """Requesting stats for a nonexistent repo still works."""
        from sylvan.server import _get_usage_stats

        with patch("sylvan.server._get_or_create_backend", return_value=ctx.backend):
            result = await _get_usage_stats({"repo": "nonexistent-repo"})
            assert "session" in result
            # No "project" key since the repo doesn't exist
            assert "project" not in result
