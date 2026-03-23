"""Hook event handling for Claude Code worktree integration.

Records worktree lifecycle events to a JSONL manifest and optionally
triggers auto-indexing when a worktree is created.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sylvan.logging import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path.home() / ".sylvan" / "worktrees.jsonl"


def record_event(event_type: str, worktree_path: str) -> None:
    """Append a worktree event to the JSONL manifest.

    Creates the manifest file and parent directory if they do not exist.

    Args:
        event_type: Event type string (e.g. ``worktree-create``, ``worktree-remove``).
        worktree_path: Absolute path to the worktree.
    """
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": event_type,
        "path": worktree_path,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with MANIFEST_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    logger.info("hook_event_recorded", event_type=event_type, path=worktree_path)


def get_active_worktrees() -> list[str]:
    """Read the manifest and return currently active worktree paths.

    Replays the event log: ``worktree-create`` adds a path,
    ``worktree-remove`` removes it.

    Returns:
        List of worktree paths that have been created but not removed.
    """
    if not MANIFEST_PATH.exists():
        return []

    active: dict[str, bool] = {}
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                path = entry.get("path", "")
                event = entry.get("event", "")
                if event == "worktree-create":
                    active[path] = True
                elif event == "worktree-remove":
                    active.pop(path, None)
            except json.JSONDecodeError:
                continue

    return [p for p, is_active in active.items() if is_active]


async def handle_worktree_create(worktree_path: str) -> dict:
    """Handle a worktree-create event by auto-indexing the worktree.

    Args:
        worktree_path: Absolute path to the new worktree.

    Returns:
        Indexing result dict.
    """
    record_event("worktree-create", worktree_path)

    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations
    from sylvan.indexing.pipeline.orchestrator import index_folder

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    name = Path(worktree_path).name
    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await index_folder(worktree_path, name=name)

    await backend.disconnect()
    return result.to_dict()


def handle_worktree_remove(worktree_path: str) -> None:
    """Handle a worktree-remove event by recording it.

    Args:
        worktree_path: Absolute path to the removed worktree.
    """
    record_event("worktree-remove", worktree_path)
