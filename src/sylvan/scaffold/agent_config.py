"""Agent configuration generator -- CLAUDE.md, .cursorrules, etc.

Generates agent instruction files that reference the ``sylvan/`` directory
for deep context.  Each agent format gets the same information, just
formatted differently.
"""

from collections import defaultdict
from pathlib import Path

from sylvan.database.orm import FileRecord, Repo
from sylvan.logging import get_logger

logger = get_logger(__name__)

# Supported agent formats
AGENT_FORMATS = {
    "claude": "CLAUDE.md",
    "cursor": ".cursorrules",
    "copilot": ".github/copilot-instructions.md",
    "generic": ".ai-instructions.md",
}


def generate_agent_config(
    repo_name: str,
    agent: str = "claude",
    project_root: Path | None = None,
) -> str:
    """Generate agent instructions (sync wrapper).

    Args:
        repo_name: Indexed repo name.
        agent: Agent format (``"claude"``, ``"cursor"``, ``"copilot"``,
            ``"generic"``).
        project_root: Project root path (for file paths in instructions).

    Returns:
        The generated instruction content as a string.
    """
    import asyncio
    return asyncio.run(async_generate_agent_config(repo_name, agent=agent, project_root=project_root))


async def async_generate_agent_config(
    repo_name: str,
    agent: str = "claude",
    project_root: Path | None = None,
) -> str:
    """Generate agent instructions that reference ``sylvan/`` for deep context.

    Args:
        repo_name: Indexed repo name.
        agent: Agent format (``"claude"``, ``"cursor"``, ``"copilot"``,
            ``"generic"``).
        project_root: Project root path (for file paths in instructions).

    Returns:
        The generated instruction content as a string.
    """
    repo = await Repo.where(name=repo_name).first()
    if not repo:
        return f"# {repo_name}\n\nProject not indexed.\n"

    files = await FileRecord.where(repo_id=repo.id).get()
    total_files = len(files)

    langs = defaultdict(int)
    for f in files:
        if f.language:
            langs[f.language] += 1
    primary_lang = max(langs, key=langs.get) if langs else "unknown"

    test_cmd = _detect_test_command(repo, files)
    run_cmd = _detect_run_command(repo, files)

    content = _build_instructions(
        repo_name=repo_name,
        primary_lang=primary_lang,
        total_files=total_files,
        languages=dict(langs),
        test_cmd=test_cmd,
        run_cmd=run_cmd,
        agent=agent,
    )

    return content


def get_agent_filename(agent: str) -> str:
    """Get the filename for an agent format.

    Args:
        agent: Agent format key.

    Returns:
        Filename string for the agent's instruction file.
    """
    return AGENT_FORMATS.get(agent, AGENT_FORMATS["generic"])


def _build_instructions(
    repo_name: str,
    primary_lang: str,
    total_files: int,
    languages: dict,
    test_cmd: str,
    run_cmd: str,
    agent: str,
) -> str:
    """Build the instruction content.

    Args:
        repo_name: Repository display name.
        primary_lang: Dominant programming language.
        total_files: Total indexed file count.
        languages: Language-to-file-count mapping.
        test_cmd: Detected test command, or empty string.
        run_cmd: Detected run command, or empty string.
        agent: Target agent format identifier.

    Returns:
        Markdown instruction content string.
    """

    lines = [
        f"# {repo_name}\n",
        "## Project Overview\n",
        f"- **Primary language:** {primary_lang}",
        f"- **Files:** {total_files}",
        f"- **Languages:** {', '.join(f'{k} ({v})' for k, v in sorted(languages.items(), key=lambda x: -x[1]))}",
    ]

    if run_cmd:
        lines.append(f"- **Run:** `{run_cmd}`")
    if test_cmd:
        lines.append(f"- **Test:** `{test_cmd}`")

    lines.append("")
    lines.append("## Sylvan Project Context\n")
    lines.append("This project has a `sylvan/` directory with auto-generated and maintained project intelligence.")
    lines.append("**Read these before starting work:**\n")
    lines.append("| File | What it contains |")
    lines.append("|------|-----------------|")
    lines.append("| `sylvan/project.md` | Project overview, languages, symbol counts |")
    lines.append("| `sylvan/architecture/overview.md` | Module map with file/symbol counts |")
    lines.append("| `sylvan/architecture/patterns.md` | Detected code patterns |")
    lines.append("| `sylvan/architecture/conventions.md` | Coding conventions (may have user notes) |")
    lines.append("| `sylvan/context/entry-points.md` | Main functions and entry points |")
    lines.append("| `sylvan/context/recent-changes.md` | Recent git commits |")
    lines.append("| `sylvan/context/hot-files.md` | Most frequently changed files |")
    lines.append("| `sylvan/dependencies/external.md` | Third-party dependencies |")
    lines.append("| `sylvan/dependencies/internal.md` | Module-to-module imports |")
    lines.append("| `sylvan/quality/report.md` | Code quality overview |")
    lines.append("")
    lines.append("## How to Use sylvan/ During Development\n")
    lines.append("### Reading context")
    lines.append("- **Before starting:** Read `sylvan/project.md` and `sylvan/architecture/overview.md`")
    lines.append("- **Before editing a module:** Read `sylvan/architecture/modules/<module>.md`")
    lines.append("- **Before refactoring:** Read `sylvan/dependencies/internal.md` and `sylvan/quality/report.md`")
    lines.append("- **For user preferences:** Read `sylvan/notes/` and `sylvan/decisions/`")
    lines.append("")
    lines.append("### Writing context")
    lines.append("- **Design decisions:** Write to `sylvan/decisions/<name>.md`")
    lines.append("- **Conventions observed:** Update `sylvan/architecture/conventions.md`")
    lines.append("- **Task tracking:**")
    lines.append("  - New task identified: create `sylvan/plans/future/<task>.md`")
    lines.append("  - Starting work: move to `sylvan/plans/working/`")
    lines.append("  - Task done: move to `sylvan/plans/completed/`")
    lines.append("- **Notes for future sessions:** Write to `sylvan/notes/`")
    lines.append("")
    lines.append("## Sylvan MCP Tools\n")
    lines.append("This project is indexed by Sylvan. Use these tools instead of reading files directly:\n")
    lines.append("- `search_symbols` -- find code by name, signature, or meaning")
    lines.append("- `get_symbol` -- get exact source of a function/class")
    lines.append("- `get_file_outline` -- see what's in a file without reading it")
    lines.append("- `search_sections` -- find documentation sections")
    lines.append("- `get_blast_radius` -- check impact before changing something")
    lines.append("")
    lines.append("Run `sylvan scaffold` to regenerate auto-generated files after significant changes.")

    return "\n".join(lines) + "\n"


def _detect_test_command(repo, files) -> str:
    """Detect the test command from project files.

    Args:
        repo: Repository ORM instance.
        files: List of :class:`FileRecord` instances.

    Returns:
        Detected test command string, or empty string.
    """
    paths = {f.path for f in files}

    if "pyproject.toml" in paths:
        return "uv run pytest tests/"
    if "package.json" in paths:
        return "npm test"
    if "go.mod" in paths:
        return "go test ./..."
    if "Cargo.toml" in paths:
        return "cargo test"
    if any("test" in p for p in paths):
        return "pytest"
    return ""


def _detect_run_command(repo, files) -> str:
    """Detect the run command from project files.

    Args:
        repo: Repository ORM instance.
        files: List of :class:`FileRecord` instances.

    Returns:
        Detected run command string, or empty string.
    """
    paths = {f.path for f in files}

    if "pyproject.toml" in paths:
        return ""
    if "package.json" in paths:
        return "npm start"
    if "go.mod" in paths:
        return "go run ."
    if "Cargo.toml" in paths:
        return "cargo run"
    return ""
