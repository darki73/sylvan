"""Repo briefing service - pre-computed orientation data."""

from __future__ import annotations

import json
from pathlib import Path

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError

MANIFEST_FILES = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "pubspec.yaml",
    "Package.swift",
    "mix.exs",
    "deno.json",
    "deno.jsonc",
]

MAX_MANIFEST_SIZE = 5000


class BriefingService:
    """Generate and retrieve repo orientation briefings."""

    async def generate(self, repo_name: str) -> None:
        """Generate and store a briefing for a repo."""
        repo = await Repo.where(name=repo_name).first()
        if repo is None:
            raise RepoNotFoundError(repo=repo_name)

        briefing = await self._build(repo)
        await Repo.where(id=repo.id).update(briefing=json.dumps(briefing))

    async def get(self, repo_name: str) -> dict:
        """Get the stored briefing, generating on first access if needed."""
        repo = await Repo.where(name=repo_name).first()
        if repo is None:
            raise RepoNotFoundError(repo=repo_name)

        if repo.briefing:
            data = json.loads(repo.briefing)
            return {**data, "repo": repo_name, "repo_id": repo.id}

        await self.generate(repo_name)
        repo = await Repo.where(name=repo_name).first()
        data = json.loads(repo.briefing)
        return {**data, "repo": repo_name, "repo_id": repo.id}

    async def _build(self, repo: Repo) -> dict:
        """Build the raw briefing data structure."""
        repo_id = repo.id

        total_files = await FileRecord.where(repo_id=repo_id).count()
        total_symbols = await (
            Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo_id).count()
        )
        total_sections = await (
            Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo_id).count()
        )

        languages = await FileRecord.where(repo_id=repo_id).where_not_null("language").group_by("language").count()

        files = await FileRecord.where(repo_id=repo_id).select("path").get()
        tree = _build_directory_tree([f.path for f in files])

        manifests = {}
        if repo.source_path:
            manifests = _read_manifests(Path(repo.source_path))

        return {
            "stats": {
                "files": total_files,
                "symbols": total_symbols,
                "sections": total_sections,
            },
            "languages": languages if isinstance(languages, dict) else {},
            "directory_tree": tree,
            "manifests": manifests,
        }


def _build_directory_tree(paths: list[str]) -> dict[str, int]:
    """Build a flat directory-to-file-count mapping from file paths."""
    tree: dict[str, int] = {}
    for path in paths:
        parts = path.replace("\\", "/").split("/")
        if len(parts) == 1:
            tree.setdefault(".", 0)
            tree["."] += 1
        else:
            dir_path = "/".join(parts[:-1])
            tree.setdefault(dir_path, 0)
            tree[dir_path] += 1
    return dict(sorted(tree.items()))


def _read_manifests(root: Path) -> dict[str, str]:
    """Read raw manifest file contents from disk."""
    manifests: dict[str, str] = {}
    for name in MANIFEST_FILES:
        path = root / name
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if len(content) > MAX_MANIFEST_SIZE:
                    content = content[:MAX_MANIFEST_SIZE] + "\n... (truncated)"
                manifests[name] = content
            except Exception:  # noqa: S110
                pass
    return manifests
