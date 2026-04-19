"""End-to-end test for the rust-backed file watcher.

Creates a real tempdir, starts the watcher, writes a file, and asserts
the change surfaces through the Python proxy. This is the canary for
"does watching actually work" — the feature used to be silently broken
when ``watchfiles`` wasn't installed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from sylvan._rust import Watcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_rust_watcher_observes_file_creation(tmp_path: Path) -> None:
    watcher = Watcher(str(tmp_path), 50)
    try:
        # Give the OS a moment to register the watch before writing.
        await asyncio.sleep(0.1)

        target = tmp_path / "hello.txt"
        target.write_text("hi", encoding="utf-8")

        # Poll for up to ~5s in 200ms steps.
        seen: list[tuple[str, str]] = []
        for _ in range(25):
            batch = await asyncio.to_thread(watcher.next_batch, 200)
            seen.extend(batch)
            if any("hello.txt" in path for _kind, path in seen):
                break

        assert any("hello.txt" in path for _kind, path in seen), f"expected a change event for hello.txt, got {seen}"
    finally:
        watcher.close()


@pytest.mark.asyncio
async def test_rust_watcher_times_out_with_no_events(tmp_path: Path) -> None:
    watcher = Watcher(str(tmp_path), 50)
    try:
        batch = await asyncio.to_thread(watcher.next_batch, 150)
        assert batch == []
    finally:
        watcher.close()


def test_rust_watcher_raises_for_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(RuntimeError, match="failed to start watching"):
        Watcher(str(missing))


@pytest.mark.asyncio
async def test_rust_watcher_close_is_idempotent(tmp_path: Path) -> None:
    watcher = Watcher(str(tmp_path), 50)
    watcher.close()
    watcher.close()  # no error on repeat close
    with pytest.raises(RuntimeError, match="watcher has been closed"):
        await asyncio.to_thread(watcher.next_batch, 50)
