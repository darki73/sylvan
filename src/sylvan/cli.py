"""Sylvan CLI -- unified code + documentation retrieval."""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="sylvan",
    help="Unified code + documentation retrieval MCP server.",
    no_args_is_help=False,
    invoke_without_command=True,
)

migrate_app = typer.Typer(help="Database migration management.")
app.add_typer(migrate_app, name="migrate")

library_app = typer.Typer(help="Third-party library indexing.")
app.add_typer(library_app, name="library")

workspace_app = typer.Typer(help="Multi-repo workspace management.")
app.add_typer(workspace_app, name="workspace")


@app.callback()
def default(ctx: typer.Context) -> None:
    """Start the MCP server if no command is given.

    Args:
        ctx: Typer invocation context.
    """
    if ctx.invoked_subcommand is None:
        serve()


@app.command()
def serve(
    transport: str = typer.Option(
        "stdio",
        "--transport", "-t",
        help="Transport mode: stdio, sse, or http (streamable-http).",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Bind address for SSE/HTTP modes.",
    ),
    port: int = typer.Option(
        8420,
        "--port", "-p",
        help="Port for SSE/HTTP modes.",
    ),
) -> None:
    """Start the MCP server (default when no command given).

    Args:
        transport: Transport protocol to use.
        host: Bind address for network transports.
        port: Bind port for network transports.
    """
    from sylvan.server.startup import main as serve_main
    serve_main(transport=transport, host=host, port=port)


@app.command()
def scaffold(
    repo: str = typer.Argument(..., help="Indexed repo name."),
    agent: str = typer.Option("claude", "--agent", "-a", help="Agent format: claude, cursor, copilot, generic."),
    root: str | None = typer.Option(None, "--root", "-r", help="Override project root path."),
) -> None:
    """Generate sylvan/ directory and agent instructions for a project.

    Args:
        repo: Name of the indexed repository.
        agent: Target agent format for instruction files.
        root: Optional override for the project root path.
    """
    from sylvan.scaffold import scaffold_project

    result = scaffold_project(repo, agent=agent, project_root=Path(root) if root else None)

    if result.get("error"):
        typer.echo(f"Error: {result['error']}")
        raise typer.Exit(1)

    typer.echo(f"Generated {result['files_created']} files:")
    typer.echo(f"  sylvan/ directory: {result['sylvan_dir']}")
    typer.echo(f"  Agent config:     {result['config_file']}")
    typer.echo(f"  Agent format:     {result['agent']}")


@app.command()
def init() -> None:
    """Interactive configuration setup for providers and embeddings.
    """

    typer.echo("Sylvan -- first time setup\n")

    has_claude = shutil.which("claude") is not None
    has_codex = shutil.which("codex") is not None

    typer.echo("Summary provider (generates richer search metadata):")
    typer.echo("  [1] Heuristic only (no AI, always works) [default]")
    typer.echo("  [2] Ollama / local LLM")
    typer.echo(f"  [3] Claude Code ({'detected' if has_claude else 'not detected'})")
    typer.echo(f"  [4] Codex CLI ({'detected' if has_codex else 'not detected'})")
    typer.echo()

    choice = typer.prompt("Select", default="1")
    from sylvan.config import Config, SummaryConfig

    config = Config()

    match choice:
        case "2":
            from sylvan.providers.external.ollama.setup import configure_ollama
            configure_ollama(config)
        case "3":
            config.summary = SummaryConfig(provider="claude-code")
        case "4":
            config.summary = SummaryConfig(provider="codex")
        case _:
            typer.echo("\nUsing heuristic defaults (zero cost, works offline).")
            typer.echo("Semantic search is already enabled via local sentence-transformers.")
            typer.echo("Run `sylvan init` again anytime to change this.")
            return

    config_path = config.save()
    try:
        config_path.chmod(0o600)
    except OSError as exc:
        from sylvan.logging import get_logger as _get_logger
        _get_logger(__name__).warning("config_chmod_failed", path=str(config_path), error=str(exc))
    typer.echo(f"\nConfig saved to {config_path}")


@app.command()
def index(
    path: str = typer.Argument(..., help="Path to the folder to index."),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name for the repo."),
    watch: Annotated[bool, typer.Option("--watch", "-w", help="Watch for changes and auto-reindex.")] = False,
) -> None:
    """Index a local folder for code symbol retrieval.

    Args:
        path: Filesystem path to the folder to index.
        name: Optional display name for the repository.
        watch: If True, watch the folder for changes and auto-reindex.
    """
    typer.echo(f"Indexing {path}...")
    result = asyncio.run(_async_index(path, name))
    typer.echo(json.dumps(result, indent=2))

    if watch:
        resolved = str(Path(path).resolve())
        repo_name = name or Path(path).resolve().name
        typer.echo(f"\nWatching {resolved} for changes (Ctrl+C to stop)...")
        from sylvan.indexing.post_processing.file_watcher import watch_folder
        asyncio.run(watch_folder(resolved, repo_name=repo_name))


async def _async_index(path: str, name: str | None) -> dict:
    """Async implementation of the index command.

    Sets up an async backend and delegates to the indexing orchestrator.

    Args:
        path: Filesystem path to the folder to index.
        name: Optional display name for the repository.

    Returns:
        Dict representation of the indexing result.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, drain_pending_tasks, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations
    from sylvan.indexing.pipeline.orchestrator import index_folder

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        result = await index_folder(path, name=name)
        await drain_pending_tasks()

    await backend.disconnect()
    return result.to_dict()


@app.command()
def remove(
    name: str = typer.Argument(..., help="Repository name to remove."),
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Remove an indexed repository and all its data.

    Args:
        name: Repository name (as shown in `sylvan status`).
        force: Skip the confirmation prompt.
    """
    if not force:
        confirm = typer.confirm(f"Remove '{name}' and all its indexed data?")
        if not confirm:
            raise typer.Abort()

    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.context import SylvanContext, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.tools.meta.remove_repo import remove_repo

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)

        ctx = SylvanContext(backend=backend, config=cfg)
        async with using_context(ctx):
            result = await remove_repo(repo=name)

        await backend.disconnect()

        counts = result.get("deleted", {})
        typer.echo(f"Removed '{name}':")
        for table, count in counts.items():
            if count > 0:
                typer.echo(f"  {table}: {count}")

    asyncio.run(_run())


@app.command()
def status() -> None:
    """Show all indexed repositories with stats.
    """
    asyncio.run(_async_status())


async def _async_status() -> None:
    """Async implementation of the status command.

    Creates an async backend, queries repos, and prints stats.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations
    from sylvan.database.orm import FileRecord, Repo, Symbol

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        repos = await Repo.all().order_by("name").get()

        if not repos:
            typer.echo("No repositories indexed yet.")
            typer.echo("Use: sylvan index <path>")
            await backend.disconnect()
            return

        for r in repos:
            file_count = await FileRecord.where(repo_id=r.id).count()
            symbol_count = await (
                Symbol.query()
                .join("files", "files.id = symbols.file_id")
                .where("files.repo_id", r.id)
                .count()
            )
            badge = f" [{r.repo_type}]" if r.repo_type and r.repo_type != "local" else ""
            typer.echo(f"  {r.name}{badge}: {file_count} files, {symbol_count} symbols (indexed {r.indexed_at})")

    await backend.disconnect()


@app.command()
def doctor() -> None:
    """Diagnose sylvan installation health.

    Checks Python version, SQLite, sqlite-vec extension, embedding model
    availability, database status, configuration, and disk usage.
    """
    asyncio.run(_async_doctor())


async def _async_doctor() -> None:
    """Async implementation of the doctor command.
    """
    import sqlite3
    import sys
    from pathlib import Path

    checks_passed = 0
    checks_failed = 0

    def _check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal checks_passed, checks_failed
        icon = "[+]" if passed else "[-]"
        msg = f"  {icon} {name}"
        if detail:
            msg += f" -- {detail}"
        typer.echo(msg)
        if passed:
            checks_passed += 1
        else:
            checks_failed += 1

    typer.echo("Sylvan Doctor\n")

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    _check("Python version", sys.version_info >= (3, 12), py_ver)

    sqlite_ver = sqlite3.sqlite_version
    _check("SQLite version", True, sqlite_ver)

    try:
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        _check("sqlite-vec extension", True, "loaded")
        conn.close()
    except Exception as exc:
        _check("sqlite-vec extension", False, str(exc))

    try:
        from sylvan.config import get_config
        config = get_config()
        db_path = config.db_path
        db_exists = Path(db_path).exists()
        if db_exists:
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            _check("Database", True, f"{db_path} ({size_mb:.1f} MB)")
        else:
            _check("Database", True, f"{db_path} (will be created on first index)")
    except Exception as exc:
        _check("Database", False, str(exc))

    try:
        from sylvan.config import get_config
        config = get_config()
        _check(
            "Configuration",
            True,
            f"summary={config.summary.provider}, embedding={config.embedding.provider}",
        )
    except Exception as exc:
        _check("Configuration", False, str(exc))

    try:
        from sylvan.search.embeddings import get_embedding_provider
        provider = get_embedding_provider()
        if provider and provider.available():
            _check("Embedding model", True, f"{provider.name} ({provider.dimensions}d)")
        elif provider:
            _check("Embedding model", False, f"{provider.name} not available")
        else:
            _check("Embedding model", True, "none configured (heuristic search only)")
    except Exception as exc:
        _check("Embedding model", False, str(exc))

    try:
        from sylvan.config import get_config as _get_cfg
        from sylvan.context import SylvanContext, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations as _run_migrations
        from sylvan.database.orm import FileRecord, Repo

        _cfg = _get_cfg()
        _backend = SQLiteBackend(_cfg.db_path)
        await _backend.connect()
        await _run_migrations(_backend)

        _ctx = SylvanContext(backend=_backend, config=_cfg)
        async with using_context(_ctx):
            repos = await Repo.all().get()
            _check("Indexed repositories", True, f"{len(repos)} repos")
            for repo in repos:
                file_count = await FileRecord.where(repo_id=repo.id).count()
                typer.echo(f"      {repo.name}: {file_count} files")
        await _backend.disconnect()
    except Exception as exc:
        _check("Indexed repositories", False, str(exc))

    try:
        from tree_sitter_language_pack import get_parser
        get_parser("python")
        _check("Tree-sitter", True, "language pack available")
    except Exception as exc:
        _check("Tree-sitter", False, str(exc))

    typer.echo(f"\n  {checks_passed} passed, {checks_failed} failed")


@app.command()
def shell() -> None:
    """Start an interactive Python shell with the ORM preloaded.

    Opens a Python REPL with all ORM models, the database connection,
    and query builder already imported and ready to use. Useful for
    debugging, data exploration, and ad-hoc queries.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context_sync
    from sylvan.database.orm import (
        Blob,
        FileImport,
        FileRecord,
        Quality,
        Reference,
        Repo,
        Section,
        Symbol,
        Workspace,
    )
    from sylvan.database.orm.query.builder import QueryBuilder

    cfg = get_config()
    ctx = SylvanContext(config=cfg)

    namespace = {
        "Symbol": Symbol,
        "Section": Section,
        "FileRecord": FileRecord,
        "FileImport": FileImport,
        "Repo": Repo,
        "Blob": Blob,
        "Reference": Reference,
        "Quality": Quality,
        "Workspace": Workspace,
        "QueryBuilder": QueryBuilder,
    }

    banner = (
        "Sylvan Shell (async ORM -- use asyncio.run() for queries)\n"
        "Available: Symbol, Section, FileRecord, Repo, Blob\n"
        "Example: import asyncio; asyncio.run(Symbol.search('parse').where(kind='function').get())\n"
    )

    with using_context_sync(ctx):
        import code
        code.interact(banner=banner, local=namespace)


@app.command()
def export(
    repo: str = typer.Argument(..., help="Repository name to export."),
    output: str = typer.Option("-", "--output", "-o", help="Output file path (- for stdout)."),
    format: str = typer.Option("json", "--format", "-f", help="Export format: json."),
) -> None:
    """Export an indexed repository to JSON for debugging or migration.

    Dumps all symbols, sections, files, and imports for a repository
    as structured JSON. Useful for debugging index contents or migrating
    data between sylvan instances.

    Args:
        repo: Name of the indexed repository to export.
        output: Output file path, or '-' for stdout.
        format: Export format (currently only 'json' supported).
    """
    asyncio.run(_async_export(repo, output, format))


async def _async_export(repo: str, output: str, format: str) -> None:
    """Async implementation of the export command.

    Args:
        repo: Name of the indexed repository to export.
        output: Output file path, or '-' for stdout.
        format: Export format.
    """
    import sys

    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.backends.sqlite.backend import SQLiteBackend
    from sylvan.database.migrations.runner import run_migrations
    from sylvan.database.orm import FileImport, FileRecord, Repo, Section, Symbol

    cfg = get_config()
    backend = SQLiteBackend(cfg.db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(backend=backend, config=cfg)
    async with using_context(ctx):
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            typer.echo(f"Repository '{repo}' not found. Run 'sylvan status' to see indexed repos.")
            await backend.disconnect()
            raise typer.Exit(1)

        files = await FileRecord.where(repo_id=repo_obj.id).order_by("path").get()
        symbols = await (
            Symbol.query()
            .join("files", "files.id = symbols.file_id")
            .where("files.repo_id", repo_obj.id)
            .order_by("symbols.symbol_id")
            .get()
        )
        sections = await (
            Section.query()
            .join("files", "files.id = sections.file_id")
            .where("files.repo_id", repo_obj.id)
            .order_by("sections.section_id")
            .get()
        )
        imports = await (
            FileImport.query()
            .join("files", "files.id = file_imports.file_id")
            .where("files.repo_id", repo_obj.id)
            .get()
        )

        # Build symbol dicts with async file path resolution
        symbol_dicts = []
        for s in symbols:
            file_path = await s._resolve_file_path()
            symbol_dicts.append({
                "symbol_id": s.symbol_id,
                "name": s.name,
                "kind": s.kind,
                "language": s.language,
                "signature": s.signature or "",
                "file": file_path,
                "line_start": s.line_start,
                "line_end": s.line_end,
            })

        section_dicts = []
        for s in sections:
            file_path = await s._resolve_file_path()
            section_dicts.append({
                "section_id": s.section_id,
                "title": s.title,
                "level": s.level,
                "file": file_path,
            })

        data = {
            "repo": {
                "name": repo_obj.name,
                "source_path": repo_obj.source_path,
                "indexed_at": repo_obj.indexed_at,
                "git_head": repo_obj.git_head,
            },
            "files": [{"path": f.path, "language": f.language} for f in files],
            "symbols": symbol_dicts,
            "sections": section_dicts,
            "imports": [
                {"file_id": i.file_id, "specifier": i.specifier}
                for i in imports
            ],
            "summary": {
                "files": len(files),
                "symbols": len(symbols),
                "sections": len(sections),
                "imports": len(imports),
            },
        }

    await backend.disconnect()

    json_str = json.dumps(data, indent=2, default=str)

    if output == "-":
        sys.stdout.write(json_str + "\n")
    else:
        Path(output).write_text(json_str, encoding="utf-8")
        typer.echo(f"Exported {repo} to {output}")


@library_app.command("add")
def library_add(
    spec: str = typer.Argument(..., help="Package spec: manager/name[@version] (e.g., pip/django@4.2)"),
    timeout: int = typer.Option(120, "--timeout", "-t", help="Fetch timeout in seconds."),
) -> None:
    """Add a third-party library by fetching its source code.

    Args:
        spec: Package specification string.
        timeout: Network fetch timeout in seconds.
    """
    from sylvan.libraries.manager import add_library

    typer.echo(f"Adding library: {spec}")
    result = add_library(spec, timeout=timeout)

    if result.get("status") == "indexed":
        typer.echo(
            f"  Indexed {result['name']}: "
            f"{result['files_indexed']} files, "
            f"{result['symbols_extracted']} symbols, "
            f"{result['sections_extracted']} sections"
        )
    elif result.get("status") == "already_indexed":
        typer.echo(f"  {result['message']}")
    else:
        typer.echo(json.dumps(result, indent=2))


@library_app.command("list")
def library_list() -> None:
    """List all indexed third-party libraries.
    """
    from sylvan.libraries.manager import list_libraries

    libs = list_libraries()
    if not libs:
        typer.echo("No libraries indexed.")
        typer.echo("Use: sylvan library add pip/django@4.2")
        return

    for lib in libs:
        typer.echo(f"  {lib['name']}: {lib['files']} files, {lib['symbols']} symbols ({lib['manager']})")


@library_app.command("remove")
def library_remove(
    name: str = typer.Argument(..., help="Library name (e.g., django@4.2)"),
) -> None:
    """Remove an indexed library and its source files.

    Args:
        name: Library display name to remove.
    """
    from sylvan.libraries.manager import remove_library

    result = remove_library(name)
    if result.get("status") == "removed":
        typer.echo(f"  Removed: {result['name']}")
    else:
        typer.echo(f"  {result.get('message', 'Failed')}")


@library_app.command("update")
def library_update(
    name: str = typer.Argument(..., help="Library name to update to latest version."),
) -> None:
    """Update a library to the latest version.

    Args:
        name: Library display name to update.
    """
    from sylvan.libraries.manager import update_library

    typer.echo(f"Updating {name}...")
    result = update_library(name)
    if result.get("status") == "indexed":
        typer.echo(f"  Updated to {result['name']}: {result['symbols_extracted']} symbols")
    else:
        typer.echo(json.dumps(result, indent=2))


@library_app.command("map")
def library_map(
    spec: str = typer.Argument(..., help="Package spec: manager/name (e.g., pip/tiktoken)"),
    repo_url: str = typer.Argument(..., help="Git repo URL (e.g., https://github.com/openai/tiktoken)"),
) -> None:
    """Map a package to a git repo URL for library indexing.

    Use when a package's PyPI/npm metadata doesn't include a source repo URL.
    The mapping is saved globally in ``~/.sylvan/registry.toml`` and reused
    automatically by ``sylvan library add``.

    Args:
        spec: Package specification string (e.g. ``pip/tiktoken``).
        repo_url: Git repository URL to associate.
    """
    from sylvan.libraries.resolution.package_registry import save_override

    save_override(spec, repo_url)
    typer.echo(f"  Mapped {spec} -> {repo_url}")
    typer.echo(f"  Now run: sylvan library add {spec}")


@library_app.command("unmap")
def library_unmap(
    spec: str = typer.Argument(..., help="Package spec to remove (e.g., pip/tiktoken)"),
) -> None:
    """Remove a package -> repo URL mapping.

    Args:
        spec: Package specification string to unmap.
    """
    from sylvan.libraries.resolution.package_registry import remove_override

    if remove_override(spec):
        typer.echo(f"  Removed mapping for {spec}")
    else:
        typer.echo(f"  No mapping found for {spec}")


@library_app.command("mappings")
def library_mappings() -> None:
    """List all user-provided repo URL mappings.
    """
    from sylvan.libraries.resolution.package_registry import list_overrides

    overrides = list_overrides()
    if not overrides:
        typer.echo("No mappings configured.")
        typer.echo("Add one with: sylvan library map pip/package https://github.com/org/repo")
        return
    for key, url in sorted(overrides.items()):
        typer.echo(f"  {key} -> {url}")


@workspace_app.command("create")
def workspace_create(
    name: str = typer.Argument(..., help="Workspace name."),
    description: str = typer.Option("", "--description", "-d", help="Workspace description."),
    paths: Annotated[list[str] | None, typer.Option("--path", "-p", help="Paths to index and add (can repeat).")] = None,
) -> None:
    """Create a workspace, optionally indexing and adding projects.

    Args:
        name: Unique workspace name.
        description: Optional description.
        paths: Paths to index and add to the workspace.
    """
    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.context import SylvanContext, drain_pending_tasks, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.database.workspace import async_add_repo_to_workspace, async_create_workspace

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)

        ctx = SylvanContext(backend=backend, config=cfg)
        async with using_context(ctx):
            ws_id = await async_create_workspace(backend, name, description)
            typer.echo(f"Workspace '{name}' created (id={ws_id})")

            if paths:
                from sylvan.database.orm import Repo
                from sylvan.indexing.pipeline.orchestrator import index_folder

                for p in paths:
                    resolved = str(Path(p).resolve())
                    repo_name = Path(p).resolve().name
                    typer.echo(f"  Indexing {resolved}...")
                    result = await index_folder(resolved, name=repo_name)
                    typer.echo(f"    {result.files_indexed} files, {result.symbols_extracted} symbols")

                    repo = await Repo.where(name=repo_name).first()
                    if repo:
                        await async_add_repo_to_workspace(backend, ws_id, repo.id)
                        typer.echo(f"    Added '{repo_name}' to workspace")

                await drain_pending_tasks()

        await backend.disconnect()

    asyncio.run(_run())


@workspace_app.command("list")
def workspace_list() -> None:
    """List all workspaces with repo counts."""
    async def _run() -> list[dict]:
        from sylvan.config import get_config
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.database.workspace import async_list_workspaces

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)
        result = await async_list_workspaces(backend)
        await backend.disconnect()
        return result

    workspaces = asyncio.run(_run())
    if not workspaces:
        typer.echo("No workspaces.")
        typer.echo("Create one with: sylvan workspace create <name>")
        return
    for ws in workspaces:
        symbols = ws.get("total_symbols") or 0
        typer.echo(f"  {ws['name']}: {ws.get('repo_count', 0)} repos, {symbols} symbols")
        if ws.get("description"):
            typer.echo(f"    {ws['description']}")


@workspace_app.command("add")
def workspace_add(
    name: str = typer.Argument(..., help="Workspace name."),
    repo: str = typer.Option(..., "--repo", "-r", help="Repo name to add."),
) -> None:
    """Add an already-indexed repo to a workspace.

    Args:
        name: Workspace name.
        repo: Repository name (as shown in `sylvan status`).
    """
    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.context import SylvanContext, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.database.orm import Repo
        from sylvan.database.workspace import async_add_repo_to_workspace

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)

        ctx = SylvanContext(backend=backend, config=cfg)
        async with using_context(ctx):
            repo_obj = await Repo.where(name=repo).first()
            if not repo_obj:
                typer.echo(f"Repository '{repo}' not found. Index it first with: sylvan index <path>")
                raise typer.Exit(1)

            ws_row = await backend.fetch_one("SELECT id FROM workspaces WHERE name = ?", [name])
            if not ws_row:
                typer.echo(f"Workspace '{name}' not found. Create it first with: sylvan workspace create {name}")
                raise typer.Exit(1)

            await async_add_repo_to_workspace(backend, ws_row["id"], repo_obj.id)
            typer.echo(f"Added '{repo}' to workspace '{name}'")

        await backend.disconnect()

    asyncio.run(_run())


@workspace_app.command("remove")
def workspace_remove(
    name: str = typer.Argument(..., help="Workspace name to delete."),
) -> None:
    """Delete a workspace (does not delete the indexed repos).

    Args:
        name: Workspace name to remove.
    """
    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)

        ws_row = await backend.fetch_one("SELECT id FROM workspaces WHERE name = ?", [name])
        if not ws_row:
            typer.echo(f"Workspace '{name}' not found.")
            raise typer.Exit(1)

        await backend.execute("DELETE FROM workspace_repos WHERE workspace_id = ?", [ws_row["id"]])
        await backend.execute("DELETE FROM workspaces WHERE id = ?", [ws_row["id"]])
        await backend.commit()
        typer.echo(f"Workspace '{name}' removed")

        await backend.disconnect()

    asyncio.run(_run())


@workspace_app.command("show")
def workspace_show(
    name: str = typer.Argument(..., help="Workspace name."),
) -> None:
    """Show workspace details and its repos.

    Args:
        name: Workspace name.
    """
    async def _run() -> dict | None:
        from sylvan.config import get_config
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.database.workspace import async_get_workspace

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()
        await run_migrations(backend)
        result = await async_get_workspace(backend, name)
        await backend.disconnect()
        return result

    ws = asyncio.run(_run())
    if not ws:
        typer.echo(f"Workspace '{name}' not found.")
        raise typer.Exit(1)

    typer.echo(f"Workspace: {ws['name']}")
    if ws.get("description"):
        typer.echo(f"  {ws['description']}")
    typer.echo(f"  Created: {ws.get('created_at', '-')}")
    repos = ws.get("repos", [])
    if repos:
        typer.echo(f"  Repos ({len(repos)}):")
        for r in repos:
            typer.echo(f"    {r['name']}")
    else:
        typer.echo("  No repos added yet.")


@app.command()
def hook(
    event: Annotated[str, typer.Argument(help="Event type: worktree-create, worktree-remove")],
) -> None:
    """Handle Claude Code hook events for auto-indexing worktrees.

    Reads a JSON payload from stdin with the worktree path and triggers
    the appropriate action.

    Args:
        event: Event type string.
    """
    import sys

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as err:
        typer.echo("Error: expected JSON payload on stdin.", err=True)
        raise typer.Exit(1) from err

    match event:
        case "worktree-create":
            path = payload.get("worktreePath") or payload.get("worktree_path")
            if not path:
                typer.echo("Error: missing worktreePath in payload.", err=True)
                raise typer.Exit(1)
            typer.echo(f"Auto-indexing worktree: {path}")
            from sylvan.hooks import handle_worktree_create
            result = asyncio.run(handle_worktree_create(path))
            typer.echo(json.dumps(result, indent=2))
        case "worktree-remove":
            path = payload.get("worktreePath") or payload.get("worktree_path")
            if not path:
                typer.echo("Error: missing worktreePath in payload.", err=True)
                raise typer.Exit(1)
            from sylvan.hooks import handle_worktree_remove
            handle_worktree_remove(path)
            typer.echo(f"Worktree removed: {path}")
        case _:
            typer.echo(f"Unknown hook event: {event}", err=True)
            raise typer.Exit(1)


@migrate_app.callback(invoke_without_command=True)
def migrate_run(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending migrations without applying."),
) -> None:
    """Run all pending database migrations.

    Args:
        ctx: Typer invocation context.
        dry_run: If True, list pending migrations without executing them.
    """
    if ctx.invoked_subcommand is not None:
        return

    import asyncio

    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.context import SylvanContext, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import get_current_version, get_pending_migrations, run_migrations

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()

        async with using_context(SylvanContext(backend=backend, config=cfg)):
            current = await get_current_version(backend)
            pending = await get_pending_migrations(backend)

            if not pending:
                typer.echo(f"Database is up to date (version {current}).")
                await backend.disconnect()
                return

            typer.echo(f"Current version: {current}")
            typer.echo(f"Pending: {len(pending)} migration(s)")
            for version, name, _ in pending:
                typer.echo(f"  {version:03d}: {name}")

            if dry_run:
                typer.echo("\n--dry-run: no migrations applied.")
                await backend.disconnect()
                return

            applied = await run_migrations(backend)
            typer.echo(f"\nApplied {len(applied)} migration(s).")

        await backend.disconnect()

    asyncio.run(_run())


@migrate_app.command("create")
def migrate_create(
    description: str = typer.Argument(..., help="Description for the new migration."),
) -> None:
    """Create a new empty migration file.

    Args:
        description: Human-readable description for the migration.
    """
    from sylvan.database.migrations.runner import create_migration

    path = create_migration(description)
    typer.echo(f"Created: {path}")
    typer.echo("Edit up() and down(), then run: sylvan migrate")


@migrate_app.command("rollback")
def migrate_rollback() -> None:
    """Roll back the most recent migration.
    """
    import asyncio

    async def _run() -> None:
        from sylvan.config import get_config
        from sylvan.context import SylvanContext, using_context
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import get_current_version, rollback_migration

        cfg = get_config()
        backend = SQLiteBackend(cfg.db_path)
        await backend.connect()

        async with using_context(SylvanContext(backend=backend, config=cfg)):
            current = await get_current_version(backend)

            if current == 0:
                typer.echo("Nothing to roll back.")
                await backend.disconnect()
                return

            typer.echo(f"Current version: {current}")
            name = await rollback_migration(backend)

            if name:
                typer.echo(f"Rolled back: {name}")
            else:
                typer.echo("Rollback failed.")

        await backend.disconnect()

    asyncio.run(_run())


def main() -> None:
    """Entry point for the CLI.

    When called with no args (MCP server mode), bypass Typer entirely
    to avoid any stdout pollution that could corrupt the MCP stdio protocol.
    """
    import sys
    if len(sys.argv) <= 1:
        # Direct MCP server -- no Typer overhead
        from sylvan.server.startup import main as serve_main
        serve_main()
    else:
        app()


if __name__ == "__main__":
    main()
