"""Auto-documentation generator -- project overview, architecture, patterns.

All public functions are async, matching the async ORM.
"""

from collections import defaultdict

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.logging import get_logger

logger = get_logger(__name__)


async def async_generate_project_md(repo_name: str) -> str:
    """Generate ``project.md`` -- top-level project overview.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string for the project overview.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return f"# {repo_name}\n\nNot indexed yet.\n"

    files = await FileRecord.where(repo_id=repo.id).get()
    total_files = len(files)

    langs: dict[str, int] = defaultdict(int)
    for file_record in files:
        if file_record.language:
            langs[file_record.language] += 1

    symbols = await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo.id).get()
    kinds: dict[str, int] = defaultdict(int)
    for symbol in symbols:
        kinds[symbol.kind] += 1

    sections = await Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo.id).count()

    primary_lang = max(langs, key=langs.get) if langs else "unknown"

    lines = [
        f"# {repo_name}\n",
        f"**Primary language:** {primary_lang}",
        f"**Files:** {total_files}",
        f"**Symbols:** {len(symbols)} ({', '.join(f'{k}: {v}' for k, v in sorted(kinds.items(), key=lambda x: -x[1]))})",
        f"**Documentation sections:** {sections}",
        f"**Indexed at:** {repo.indexed_at}",
        "",
        "## Languages",
        "",
    ]
    for lang, count in sorted(langs.items(), key=lambda x: -x[1]):
        lines.append(f"- {lang}: {count} files")

    return "\n".join(lines) + "\n"


async def async_generate_architecture_overview(repo_name: str) -> str:
    """Generate ``architecture/overview.md`` -- directory-level module map.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    files = await FileRecord.where(repo_id=repo.id).order_by("path").get()

    dirs: dict[str, dict] = {}
    for file_record in files:
        parts = file_record.path.split("/")
        if len(parts) > 1:
            top_dir = parts[0]
            if top_dir not in dirs:
                dirs[top_dir] = {"files": 0, "symbols": 0, "languages": set()}
            dirs[top_dir]["files"] += 1
            if file_record.language:
                dirs[top_dir]["languages"].add(file_record.language)
            dirs[top_dir]["symbols"] += await Symbol.where(file_id=file_record.id).count()

    lines = ["# Architecture Overview\n", "## Module Map\n"]
    for dir_name, info in sorted(dirs.items()):
        langs = ", ".join(sorted(info["languages"]))
        lines.append(f"### `{dir_name}/`")
        lines.append(f"- Files: {info['files']}")
        lines.append(f"- Symbols: {info['symbols']}")
        lines.append(f"- Languages: {langs}")
        lines.append("")

    return "\n".join(lines) + "\n"


async def async_generate_module_doc(repo_name: str, module_path: str) -> str:
    """Generate a per-module document listing files and their symbols.

    Args:
        repo_name: Indexed repository name.
        module_path: Top-level directory path within the repo.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    files = await (FileRecord.where(repo_id=repo.id)
             .where_like("path", f"{module_path}/%")
             .order_by("path")
             .get())

    lines = [f"# Module: `{module_path}/`\n"]

    for file_record in files:
        symbols = await Symbol.where(file_id=file_record.id).order_by("line_start").get()
        if not symbols:
            continue

        lines.append(f"## `{file_record.path}`")
        lines.append("")
        for symbol in symbols:
            indent = "  " if symbol.parent_symbol_id else ""
            sig = symbol.signature[:80] if symbol.signature else symbol.name
            lines.append(f"{indent}- **{symbol.kind}** `{sig}`")
        lines.append("")

    return "\n".join(lines) + "\n"


async def async_generate_patterns_md(repo_name: str) -> str:
    """Generate ``architecture/patterns.md`` -- detected coding patterns.

    Args:
        repo_name: Indexed repository name.

    Returns:
        Markdown content string, or empty string if the repo is not found.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return ""

    lines = ["# Detected Patterns\n"]

    symbols = await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo.id).get()

    has_tests = any("test" in symbol.name.lower() for symbol in symbols)
    has_cli = any(symbol.name in ("main", "cli", "app") and symbol.kind == "function" for symbol in symbols)
    has_models = any("model" in (symbol.qualified_name or "").lower() and symbol.kind == "class" for symbol in symbols)
    has_api = any(symbol.name in ("get", "post", "put", "delete", "route", "router") for symbol in symbols)

    decorators: set[str] = set()
    for symbol in symbols:
        if symbol.decorators:
            for dec in symbol.decorators:
                decorators.add(dec)

    if has_tests:
        lines.append("- **Testing:** Test files detected")
    if has_cli:
        lines.append("- **CLI:** Command-line entry point found")
    if has_models:
        lines.append("- **Models:** Data model classes detected")
    if has_api:
        lines.append("- **API:** HTTP route handlers detected")
    if decorators:
        lines.append(f"- **Decorators used:** {', '.join(sorted(list(decorators)[:10]))}")

    lines.append("")
    lines.append("<!-- Agent: add patterns you observe during development -->")

    return "\n".join(lines) + "\n"
