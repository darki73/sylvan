"""MCP tool: compare_library_versions — diff symbols between two library versions."""

from sylvan.database.orm import Repo, Symbol
from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def compare_library_versions(
    package: str,
    from_version: str,
    to_version: str,
) -> dict:
    """Compare two indexed versions of the same library.

    Generates a migration-relevant diff: symbols added, removed, and
    changed (signature differences). The agent uses this to assess
    breaking changes before upgrading a workspace's pinned version.

    Both versions must already be indexed via ``add_library``.

    Args:
        package: Package name without manager prefix (e.g. ``"numpy"``).
        from_version: The old version string (e.g. ``"1.1.1"``).
        to_version: The new version string (e.g. ``"2.2.2"``).

    Returns:
        Tool response dict with added, removed, and changed symbol lists.
    """
    meta = MetaBuilder()

    old_name = f"{package}@{from_version}"
    new_name = f"{package}@{to_version}"

    old_repo = await Repo.where(name=old_name).where(repo_type="library").first()
    new_repo = await Repo.where(name=new_name).where(repo_type="library").first()

    if old_repo is None:
        return wrap_response(
            {"error": f"Library '{old_name}' is not indexed. Run add_library first."},
            meta.build(),
        )
    if new_repo is None:
        return wrap_response(
            {"error": f"Library '{new_name}' is not indexed. Run add_library first."},
            meta.build(),
        )

    old_symbols = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", old_repo.id)
        .where(kind="function")
        .or_where(kind="class")
        .or_where(kind="method")
        .get()
    )

    new_symbols = await (
        Symbol.query()
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", new_repo.id)
        .where(kind="function")
        .or_where(kind="class")
        .or_where(kind="method")
        .get()
    )

    old_by_name: dict[str, dict] = {}
    for symbol in old_symbols:
        old_by_name[symbol.qualified_name] = {
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "signature": symbol.signature or "",
        }

    new_by_name: dict[str, dict] = {}
    for symbol in new_symbols:
        new_by_name[symbol.qualified_name] = {
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "signature": symbol.signature or "",
        }

    old_names = set(old_by_name.keys())
    new_names = set(new_by_name.keys())

    added = [new_by_name[name] for name in sorted(new_names - old_names)]
    removed = [old_by_name[name] for name in sorted(old_names - new_names)]

    changed = []
    for name in sorted(old_names & new_names):
        old_sig = old_by_name[name]["signature"]
        new_sig = new_by_name[name]["signature"]
        if old_sig != new_sig:
            changed.append({
                "qualified_name": name,
                "kind": old_by_name[name]["kind"],
                "old_signature": old_sig,
                "new_signature": new_sig,
            })

    meta.set("from_version", from_version)
    meta.set("to_version", to_version)
    meta.set("added_count", len(added))
    meta.set("removed_count", len(removed))
    meta.set("changed_count", len(changed))
    meta.set("breaking_risk", "high" if removed or changed else "low")

    return wrap_response({
        "package": package,
        "from_version": from_version,
        "to_version": to_version,
        "added": added[:50],
        "removed": removed[:50],
        "changed": changed[:50],
        "summary": {
            "total_added": len(added),
            "total_removed": len(removed),
            "total_changed": len(changed),
            "breaking_risk": "high" if removed or changed else "low",
        },
    }, meta.build())
