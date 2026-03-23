"""Tests for sylvan.tools.meta.get_logs."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def log_env(tmp_path):
    """Set SYLVAN_HOME to a temp dir and create a log file."""
    home = tmp_path / ".sylvan"
    log_dir = home / "logs"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "sylvan.log"

    lines = [f"line {i}" for i in range(1, 101)]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    old = os.environ.get("SYLVAN_HOME")
    os.environ["SYLVAN_HOME"] = str(home)
    yield log_file
    if old is None:
        os.environ.pop("SYLVAN_HOME", None)
    else:
        os.environ["SYLVAN_HOME"] = old


@pytest.fixture
def empty_log_env(tmp_path):
    """Set SYLVAN_HOME to a temp dir with no log file."""
    home = tmp_path / ".sylvan"
    home.mkdir(parents=True)

    old = os.environ.get("SYLVAN_HOME")
    os.environ["SYLVAN_HOME"] = str(home)
    yield home
    if old is None:
        os.environ.pop("SYLVAN_HOME", None)
    else:
        os.environ["SYLVAN_HOME"] = old


class TestGetLogsTailMode:
    async def test_returns_last_n_lines(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=10)
        assert "_meta" in resp
        entries = resp["entries"]
        assert len(entries) == 10
        assert entries[-1] == "line 100"
        assert entries[0] == "line 91"

    async def test_tail_with_offset(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=5, offset=10)
        entries = resp["entries"]
        assert len(entries) == 5
        # offset=10 means skip last 10 lines, so end at line 90
        assert entries[-1] == "line 90"
        assert entries[0] == "line 86"

    async def test_default_returns_50_lines(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs()
        assert resp["_meta"]["returned_lines"] == 50


class TestGetLogsHeadMode:
    async def test_returns_first_n_lines(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=5, from_start=True)
        entries = resp["entries"]
        assert len(entries) == 5
        assert entries[0] == "line 1"
        assert entries[4] == "line 5"

    async def test_head_with_offset(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=3, from_start=True, offset=5)
        entries = resp["entries"]
        assert len(entries) == 3
        assert entries[0] == "line 6"


class TestGetLogsMeta:
    async def test_meta_fields_present(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=5)
        meta = resp["_meta"]
        assert "total_lines" in meta
        assert meta["total_lines"] == 100
        assert "returned_lines" in meta
        assert meta["returned_lines"] == 5
        assert "offset" in meta
        assert "from_start" in meta
        assert "log_file" in meta


class TestGetLogsEdgeCases:
    async def test_no_log_file(self, empty_log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs()
        assert resp["entries"] == []
        assert "message" in resp

    async def test_lines_clamped_to_max_500(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=9999)
        # 100 lines in the file, but lines param clamped to 500
        assert resp["_meta"]["returned_lines"] == 100

    async def test_lines_clamped_to_min_1(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=0)
        assert resp["_meta"]["returned_lines"] == 1

    async def test_offset_beyond_end_returns_empty(self, log_env):
        from sylvan.tools.meta.get_logs import get_logs

        resp = await get_logs(lines=5, offset=200)
        assert resp["entries"] == []
