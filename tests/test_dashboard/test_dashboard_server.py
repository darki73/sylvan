"""Tests for sylvan.dashboard.server — URL retrieval, stop, port finding."""

from __future__ import annotations

import sylvan.dashboard.server as srv_mod


class TestGetDashboardUrl:
    """Tests for get_dashboard_url()."""

    def test_returns_none_when_not_started(self):
        """Before starting, get_dashboard_url returns None."""
        original = srv_mod._dashboard_port
        try:
            srv_mod._dashboard_port = None
            result = srv_mod.get_dashboard_url()
            assert result is None
        finally:
            srv_mod._dashboard_port = original

    def test_returns_url_when_port_set(self):
        """When port is set, returns the full URL."""
        original = srv_mod._dashboard_port
        try:
            srv_mod._dashboard_port = 8420
            result = srv_mod.get_dashboard_url()
            assert result == "http://127.0.0.1:8420"
        finally:
            srv_mod._dashboard_port = original


class TestStopDashboard:
    """Tests for stop_dashboard()."""

    async def test_stop_when_not_running(self):
        """stop_dashboard is a no-op when no task exists."""
        original = srv_mod._dashboard_task
        try:
            srv_mod._dashboard_task = None
            await srv_mod.stop_dashboard()  # Should not raise
            assert srv_mod._dashboard_task is None
        finally:
            srv_mod._dashboard_task = original

    async def test_stop_cancels_task(self):
        """stop_dashboard cancels the running task."""
        import asyncio
        import contextlib

        original = srv_mod._dashboard_task
        try:
            # Create a dummy task
            async def _forever():
                await asyncio.sleep(9999)

            task = asyncio.get_running_loop().create_task(_forever())
            srv_mod._dashboard_task = task

            await srv_mod.stop_dashboard()
            assert srv_mod._dashboard_task is None

            # Let the cancellation propagate
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert task.cancelled()
        finally:
            srv_mod._dashboard_task = original


class TestFindFreePort:
    """Tests for _find_free_port()."""

    def test_returns_int(self):
        """_find_free_port returns an integer port number."""
        port = srv_mod._find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_returns_different_ports(self):
        """Successive calls return different ports (probabilistically)."""
        ports = {srv_mod._find_free_port() for _ in range(5)}
        # With 5 calls we expect at least 2 different ports
        assert len(ports) >= 2
