"""Workspace management -- group repos that belong together.

Provides async helpers for workspace CRUD operations used by server dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.database.backends.base import BaseBackend


async def async_create_workspace(
    backend: BaseBackend,
    name: str,
    description: str = "",
) -> int:
    """Create a workspace and return its ID via the async backend.

    Args:
        backend: The async storage backend.
        name: Unique workspace name.
        description: Optional human-readable description.

    Returns:
        The integer ID of the created (or existing) workspace.
    """
    await backend.execute(
        "INSERT OR IGNORE INTO workspaces (name, description) VALUES (?, ?)",
        [name, description],
    )
    await backend.commit()
    row = await backend.fetch_one(
        "SELECT id FROM workspaces WHERE name = ?", [name]
    )
    return row["id"]


async def async_add_repo_to_workspace(
    backend: BaseBackend,
    workspace_id: int,
    repo_id: int,
) -> None:
    """Add a repo to a workspace via the async backend.

    Args:
        backend: The async storage backend.
        workspace_id: ID of the target workspace.
        repo_id: ID of the repo to add.
    """
    await backend.execute(
        "INSERT OR IGNORE INTO workspace_repos (workspace_id, repo_id) VALUES (?, ?)",
        [workspace_id, repo_id],
    )
    await backend.commit()


async def async_get_workspace_repo_ids(backend: BaseBackend, workspace_name: str) -> list[int]:
    """Get all repo IDs in a workspace via the async backend.

    Args:
        backend: The async storage backend.
        workspace_name: Name of the workspace to query.

    Returns:
        List of integer repo IDs belonging to the workspace.
    """
    rows = await backend.fetch_all(
        """SELECT wr.repo_id FROM workspace_repos wr
           JOIN workspaces w ON w.id = wr.workspace_id
           WHERE w.name = ?""",
        [workspace_name],
    )
    return [r["repo_id"] for r in rows]


async def async_get_workspace(backend: BaseBackend, name: str) -> dict | None:
    """Get workspace details with its list of repos via the async backend.

    Args:
        backend: The async storage backend.
        name: Name of the workspace to retrieve.

    Returns:
        A dict with workspace info and repo list, or None if not found.
    """
    ws = await backend.fetch_one(
        "SELECT * FROM workspaces WHERE name = ?", [name]
    )
    if ws is None:
        return None

    repos = await backend.fetch_all(
        """SELECT r.* FROM repos r
           JOIN workspace_repos wr ON wr.repo_id = r.id
           WHERE wr.workspace_id = ?
           ORDER BY r.name""",
        [ws["id"]],
    )

    return {
        "id": ws["id"],
        "name": ws["name"],
        "description": ws["description"],
        "repos": [dict(r) for r in repos],
    }


async def async_list_workspaces(backend: BaseBackend) -> list[dict]:
    """List all workspaces with repo counts via the async backend.

    Args:
        backend: The async storage backend.

    Returns:
        List of dicts, each containing workspace info, repo_count, and total_symbols.
    """
    rows = await backend.fetch_all(
        """SELECT w.*,
                  (SELECT COUNT(*) FROM workspace_repos WHERE workspace_id = w.id) as repo_count,
                  (SELECT SUM(sub.sc) FROM (
                      SELECT (SELECT COUNT(*) FROM symbols s
                              JOIN files f ON f.id = s.file_id
                              WHERE f.repo_id = wr2.repo_id) as sc
                      FROM workspace_repos wr2
                      WHERE wr2.workspace_id = w.id
                  ) sub) as total_symbols
           FROM workspaces w
           ORDER BY w.name""",
    )
    return [dict(r) for r in rows]


async def async_delete_workspace(backend: BaseBackend, name: str) -> bool:
    """Delete a workspace by name via the async backend.

    Args:
        backend: The async storage backend.
        name: Name of the workspace to delete.

    Returns:
        True if a workspace was deleted, False if it did not exist.
    """
    rows_affected = await backend.execute(
        "DELETE FROM workspaces WHERE name = ?", [name]
    )
    await backend.commit()
    return rows_affected > 0
