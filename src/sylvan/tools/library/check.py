"""MCP tool: check_library_versions — compare installed vs indexed library versions."""

from pathlib import Path

from sylvan.database.orm import Repo
from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def check_library_versions(repo: str) -> dict:
    """Compare a project's installed dependencies against indexed library versions.

    Reads the project's dependency files (pyproject.toml, package.json, etc.)
    and cross-references each dependency against the sylvan library index.
    Reports which libraries are outdated, up-to-date, or not indexed.

    The agent uses this after running ``uv sync`` or ``npm install`` to
    detect version drift and decide which libraries to update in sylvan.

    Args:
        repo: Indexed repository name to check dependencies for.

    Returns:
        Tool response dict with ``outdated``, ``up_to_date``, and
        ``not_indexed`` lists plus ``_meta`` envelope.
    """
    meta = MetaBuilder()

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None or not repo_obj.source_path:
        return wrap_response(
            {"error": f"Repository '{repo}' not found or has no source path."},
            meta.build(),
        )

    from sylvan.git.dependency_files import parse_dependencies

    installed_deps = parse_dependencies(Path(repo_obj.source_path))

    if not installed_deps:
        return wrap_response(
            {
                "message": "No dependency files found in project root.",
                "outdated": [],
                "up_to_date": [],
                "not_indexed": [],
            },
            meta.build(),
        )

    indexed_libraries = await Repo.where(repo_type="library").get()

    indexed_by_package: dict[str, list[dict]] = {}
    for lib in indexed_libraries:
        if lib.package_manager and lib.package_name:
            key = f"{lib.package_manager}/{lib.package_name}"
            indexed_by_package.setdefault(key, []).append(
                {
                    "name": lib.name,
                    "version": lib.version,
                    "repo_id": lib.id,
                }
            )

    outdated: list[dict] = []
    up_to_date: list[dict] = []
    not_indexed: list[dict] = []

    for dep in installed_deps:
        manager = dep["manager"]
        name = dep["name"]
        installed_version = dep["version"] or "unknown"
        key = f"{manager}/{name}"

        if key not in indexed_by_package:
            not_indexed.append(
                {
                    "manager": manager,
                    "name": name,
                    "installed_version": installed_version,
                }
            )
            continue

        versions = indexed_by_package[key]
        indexed_versions = [v["version"] for v in versions]

        if installed_version in indexed_versions:
            up_to_date.append(
                {
                    "manager": manager,
                    "name": name,
                    "version": installed_version,
                }
            )
        else:
            outdated.append(
                {
                    "manager": manager,
                    "name": name,
                    "installed_version": installed_version,
                    "indexed_versions": indexed_versions,
                }
            )

    meta.set("total_deps", len(installed_deps))
    meta.set("outdated_count", len(outdated))
    meta.set("up_to_date_count", len(up_to_date))
    meta.set("not_indexed_count", len(not_indexed))

    return wrap_response(
        {
            "outdated": outdated,
            "up_to_date": up_to_date,
            "not_indexed": not_indexed,
        },
        meta.build(),
    )
