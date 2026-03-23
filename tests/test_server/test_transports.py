"""Tests for sylvan.server.transports — stdio, SSE, and streamable HTTP runners."""

from __future__ import annotations

import inspect


class TestRunStdio:
    """Tests for run_stdio()."""

    def test_is_async_function(self):
        """run_stdio is an async function."""
        from sylvan.server.transports import run_stdio

        assert inspect.iscoroutinefunction(run_stdio)

    def test_accepts_server_argument(self):
        """run_stdio accepts a single 'server' parameter."""
        from sylvan.server.transports import run_stdio

        sig = inspect.signature(run_stdio)
        params = list(sig.parameters.keys())
        assert "server" in params


class TestRunSse:
    """Tests for run_sse()."""

    def test_is_async_function(self):
        """run_sse is an async function."""
        from sylvan.server.transports import run_sse

        assert inspect.iscoroutinefunction(run_sse)

    def test_default_host_and_port(self):
        """run_sse defaults to 127.0.0.1:8420."""
        from sylvan.server.transports import run_sse

        sig = inspect.signature(run_sse)
        assert sig.parameters["host"].default == "127.0.0.1"
        assert sig.parameters["port"].default == 8420

    def test_accepts_server_host_port(self):
        """run_sse accepts server, host, and port parameters."""
        from sylvan.server.transports import run_sse

        sig = inspect.signature(run_sse)
        params = list(sig.parameters.keys())
        assert "server" in params
        assert "host" in params
        assert "port" in params


class TestRunStreamableHttp:
    """Tests for run_streamable_http()."""

    def test_is_async_function(self):
        """run_streamable_http is an async function."""
        from sylvan.server.transports import run_streamable_http

        assert inspect.iscoroutinefunction(run_streamable_http)

    def test_default_host_and_port(self):
        """run_streamable_http defaults to 127.0.0.1:8420."""
        from sylvan.server.transports import run_streamable_http

        sig = inspect.signature(run_streamable_http)
        assert sig.parameters["host"].default == "127.0.0.1"
        assert sig.parameters["port"].default == 8420

    def test_accepts_server_host_port(self):
        """run_streamable_http accepts server, host, and port parameters."""
        from sylvan.server.transports import run_streamable_http

        sig = inspect.signature(run_streamable_http)
        params = list(sig.parameters.keys())
        assert "server" in params
        assert "host" in params
        assert "port" in params


class TestModuleImport:
    """Tests for module-level behavior."""

    def test_module_importable(self):
        """The transports module can be imported."""
        import sylvan.server.transports  # noqa: F401

    def test_all_transports_defined(self):
        """All three transport runners are accessible from the module."""
        from sylvan.server import transports

        assert hasattr(transports, "run_stdio")
        assert hasattr(transports, "run_sse")
        assert hasattr(transports, "run_streamable_http")
