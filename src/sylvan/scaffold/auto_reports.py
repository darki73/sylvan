"""Auto-generated reports -- dependencies, quality, entry points, git history.

All public functions are async, matching the async ORM.
"""

from collections import defaultdict
from pathlib import Path

from sylvan.database.orm import FileImport, FileRecord, Repo, Symbol
from sylvan.logging import get_logger

logger = get_logger(__name__)


async def async_generate_dependencies_internal(repo_name: str) -> str:
    """Generate ``dependencies/internal.md`` -- module-to-module imports.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    imports = await (
        FileImport.query().join("files", "files.id = file_imports.file_id").where("files.repo_id", repo.id).get()
    )

    deps: dict[str, set[str]] = defaultdict(set)
    for imp in imports:
        src_file = await FileRecord.find(imp.file_id)
        if not src_file:
            continue
        src_module = src_file.path.split("/")[0] if "/" in src_file.path else "(root)"
        spec = imp.specifier
        if spec.startswith("."):
            continue
        deps[src_module].add(spec.split(".")[0].split("/")[0])

    lines = ["# Internal Dependencies\n"]
    for module, targets in sorted(deps.items()):
        lines.append(f"## `{module}/`")
        for t in sorted(targets):
            lines.append(f"- imports `{t}`")
        lines.append("")

    return "\n".join(lines) + "\n"


async def async_generate_dependencies_external(repo_name: str) -> str:
    """Generate ``dependencies/external.md`` from detected dependency files.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo or not repo.source_path:
        return "# External Dependencies\n\nNo source path available.\n"

    from sylvan.git.dependency_files import parse_dependencies

    deps = parse_dependencies(Path(repo.source_path))

    lines = ["# External Dependencies\n"]
    if not deps:
        lines.append("No dependency files detected.")
    else:
        by_manager: dict[str, list] = defaultdict(list)
        for dep in deps:
            by_manager[dep["manager"]].append(dep)

        for manager, pkgs in sorted(by_manager.items()):
            lines.append(f"## {manager}")
            for p in sorted(pkgs, key=lambda x: x["name"]):
                ver = p["version"] if p["version"] else "any"
                lines.append(f"- `{p['name']}` {ver}")
            lines.append("")

    return "\n".join(lines) + "\n"


async def async_generate_quality_report(repo_name: str) -> str:
    """Generate ``quality/report.md`` -- symbol counts and documentation coverage.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    base = Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo.id)
    total = await base.count()
    functions = await base.where(kind="function").count()
    classes = await base.where(kind="class").count()
    documented = await base.where_not_null("docstring").count()

    doc_pct = round(documented / total * 100) if total else 0

    lines = [
        "# Quality Report\n",
        f"**Total symbols:** {total}",
        f"**Functions:** {functions}",
        f"**Classes:** {classes}",
        f"**Documented (has docstring):** {documented} ({doc_pct}%)",
        "",
        "<!-- Auto-generated. Run `sylvan scaffold` to refresh. -->",
    ]

    return "\n".join(lines) + "\n"


async def async_generate_entry_points(repo_name: str) -> str:
    """Generate ``context/entry-points.md`` -- common entry point functions.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    entry_names = {"main", "app", "cli", "run", "start", "serve", "server"}
    entries = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo.id)
        .where(kind="function")
        .get()
    )

    found = [symbol for symbol in entries if symbol.name in entry_names]

    lines = ["# Entry Points\n"]
    if found:
        for symbol in found:
            await symbol.load("file")
            file_path = symbol.file.path if symbol.file else "?"
            lines.append(f"- `{symbol.name}()` in `{file_path}` (line {symbol.line_start})")
    else:
        lines.append("No standard entry points detected (main, app, cli, run, start, serve).")

    lines.append("")
    lines.append("<!-- Agent: add entry points you discover -->")

    return "\n".join(lines) + "\n"


async def async_generate_recent_changes(repo_name: str) -> str:
    """Generate ``context/recent-changes.md`` from git log.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo or not repo.source_path:
        return "# Recent Changes\n\nNo source path available.\n"

    from sylvan.git.diff import get_commit_log

    commits = get_commit_log(Path(repo.source_path), max_count=20)

    lines = ["# Recent Changes\n"]
    if commits:
        for commit in commits:
            lines.append(f"- `{commit['hash'][:7]}` {commit['message']} ({commit['author']}, {commit['date'][:10]})")
    else:
        lines.append("No git history available.")

    return "\n".join(lines) + "\n"


async def async_generate_hot_files(repo_name: str) -> str:
    """Generate ``context/hot-files.md`` -- most frequently changed files.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo or not repo.source_path:
        return "# Hot Files\n\nNo source path available.\n"

    from sylvan.git.blame import get_change_frequency

    root = Path(repo.source_path)

    files = await FileRecord.where(repo_id=repo.id).order_by("path").get()
    freq = []
    for file_record in files[:100]:
        count = get_change_frequency(root, file_record.path, max_count=50)
        if count > 0:
            freq.append((file_record.path, count))

    freq.sort(key=lambda x: -x[1])

    lines = ["# Hot Files\n", "Most frequently changed files (by commit count).\n"]
    for path, count in freq[:20]:
        lines.append(f"- `{path}`: {count} commits")

    return "\n".join(lines) + "\n"
