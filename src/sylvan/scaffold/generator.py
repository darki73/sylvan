"""Scaffold generator -- creates sylvan/ directory and populates it.

Provides both sync (CLI, wraps async) and async (MCP tool) entry points.
"""

import asyncio
from pathlib import Path

from sylvan.database.orm import FileRecord, Repo
from sylvan.logging import get_logger
from sylvan.scaffold.directory_structure import STRUCTURE

logger = get_logger(__name__)


def scaffold_project(
    repo_name: str,
    agent: str = "claude",
    project_root: Path | None = None,
) -> dict:
    """Generate the sylvan/ directory structure and agent config files (sync).

    Wraps the async implementation with ``asyncio.run()``, creating an
    async backend for the duration of the scaffold operation.

    Args:
        repo_name: Indexed repo name.
        agent: Agent format for instruction file
            (``"claude"``, ``"cursor"``, ``"copilot"``, ``"generic"``).
        project_root: Override project root (defaults to the repo's
            ``source_path``).

    Returns:
        Summary dict of what was generated, including ``files_created``,
        ``sylvan_dir``, and ``config_file``.
    """
    return asyncio.run(_async_scaffold_with_backend(repo_name, agent=agent, project_root=project_root))


async def _async_scaffold_with_backend(
    repo_name: str,
    agent: str = "claude",
    project_root: Path | None = None,
) -> dict:
    """Set up an async backend and delegate to async_scaffold_project.

    Args:
        repo_name: Indexed repo name.
        agent: Agent format for instruction file.
        project_root: Override project root.

    Returns:
        Summary dict of what was generated.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await async_scaffold_project(repo_name, agent=agent, project_root=project_root)

    await backend.disconnect()
    return result


async def async_scaffold_project(
    repo_name: str,
    agent: str = "claude",
    project_root: Path | None = None,
) -> dict:
    """Generate the sylvan/ directory structure and agent config files (async).

    Assumes a SylvanContext with backend is already set.

    Args:
        repo_name: Indexed repo name.
        agent: Agent format for instruction file.
        project_root: Override project root.

    Returns:
        Summary dict of what was generated.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return {"error": f"Repo '{repo_name}' not found. Index it first."}

    root = Path(project_root) if project_root else (Path(repo.source_path) if repo.source_path else None)
    if not root or not root.exists():
        return {"error": f"Project root not found: {root}"}

    sylvan_dir = root / "sylvan"

    files_created = _create_structure(sylvan_dir, STRUCTURE["sylvan"])

    from sylvan.scaffold.auto_docs import (
        async_generate_architecture_overview,
        async_generate_module_doc,
        async_generate_patterns_md,
        async_generate_project_md,
    )
    from sylvan.scaffold.auto_reports import (
        async_generate_dependencies_external,
        async_generate_dependencies_internal,
        async_generate_entry_points,
        async_generate_hot_files,
        async_generate_quality_report,
        async_generate_recent_changes,
    )

    auto_files = {
        "project.md": await async_generate_project_md(repo_name),
        "architecture/overview.md": await async_generate_architecture_overview(repo_name),
        "architecture/patterns.md": await async_generate_patterns_md(repo_name),
        "dependencies/internal.md": await async_generate_dependencies_internal(repo_name),
        "dependencies/external.md": await async_generate_dependencies_external(repo_name),
        "quality/report.md": await async_generate_quality_report(repo_name),
        "context/entry-points.md": await async_generate_entry_points(repo_name),
        "context/recent-changes.md": await async_generate_recent_changes(repo_name),
        "context/hot-files.md": await async_generate_hot_files(repo_name),
    }

    for rel_path, content in auto_files.items():
        if content:
            path = sylvan_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            files_created += 1

    top_dirs = set()
    for f in await FileRecord.where(repo_id=repo.id).get():
        if "/" in f.path:
            top_dirs.add(f.path.split("/")[0])

    modules_dir = sylvan_dir / "architecture" / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    for module in sorted(top_dirs):
        content = await async_generate_module_doc(repo_name, module)
        if content and len(content) > 50:
            (modules_dir / f"{module}.md").write_text(content, encoding="utf-8")
            files_created += 1

    from sylvan.scaffold.agent_config import async_generate_agent_config, get_agent_filename

    config_content = await async_generate_agent_config(repo_name, agent=agent, project_root=root)
    config_filename = get_agent_filename(agent)

    config_path = root / config_filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content, encoding="utf-8")
    files_created += 1

    logger.info(
        "scaffold_generated",
        repo=repo_name,
        agent=agent,
        files_created=files_created,
        sylvan_dir=str(sylvan_dir),
        config_file=config_filename,
    )

    return {
        "status": "generated",
        "repo": repo_name,
        "sylvan_dir": str(sylvan_dir),
        "config_file": config_filename,
        "files_created": files_created,
        "agent": agent,
    }


def _create_structure(base: Path, structure: dict, depth: int = 0) -> int:
    """Recursively create directory structure and write initial content.

    Args:
        base: Base directory to create structure in.
        structure: Nested dict defining subdirectories and file contents.
        depth: Current recursion depth (for internal use).

    Returns:
        Number of files created.
    """
    created = 0
    base.mkdir(parents=True, exist_ok=True)

    for name, value in structure.items():
        path = base / name
        if isinstance(value, dict):
            created += _create_structure(path, value, depth + 1)
        elif isinstance(value, str):
            if not path.exists():
                path.write_text(value, encoding="utf-8")
                created += 1
        elif value is None:
            pass

    return created
