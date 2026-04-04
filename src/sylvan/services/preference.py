"""Preference service -- save, load, delete agent behavioral instructions."""

from __future__ import annotations

from datetime import UTC, datetime

from sylvan.database.orm.models import Preference, Repo, Workspace
from sylvan.error_codes import (
    InvalidScopeError,
    RepoNotFoundError,
    WorkspaceNotFoundError,
)
from sylvan.logging import get_logger
from sylvan.search.embeddings import get_embedding_provider

logger = get_logger(__name__)

VALID_SCOPES = ("global", "workspace", "repo")
SCOPE_PRIORITY = {"global": 0, "workspace": 1, "repo": 2}
DEDUP_THRESHOLD = 0.92


class PreferenceService:
    """Manage agent behavioral instructions with scope hierarchy.

    Three scopes: global (all repos), workspace, repo.
    Repo overrides workspace overrides global for the same key.
    """

    async def save(
        self,
        key: str,
        instruction: str,
        scope: str,
        scope_id: int | None = None,
    ) -> dict:
        """Save or update a preference. Upserts on (scope, scope_id, key)."""
        if scope not in VALID_SCOPES:
            raise InvalidScopeError(
                f"Invalid scope '{scope}', must be one of: {', '.join(VALID_SCOPES)}",
                scope=scope,
            )

        if scope == "global":
            scope_id = None
        elif scope_id is None:
            raise InvalidScopeError(
                f"scope_id is required for scope '{scope}'",
                scope=scope,
            )

        if scope == "repo":
            repo = await Repo.find(scope_id)
            if repo is None:
                raise RepoNotFoundError(f"Repo with id {scope_id} not found", repo_id=scope_id)
        elif scope == "workspace":
            ws = await Workspace.find(scope_id)
            if ws is None:
                raise WorkspaceNotFoundError(
                    f"Workspace with id {scope_id} not found",
                    workspace_id=scope_id,
                )

        existing = await self._find_preference(scope, scope_id, key)
        now = datetime.now(UTC).isoformat()

        if existing is not None:
            existing.instruction = instruction
            existing.updated_at = now
            await existing.save()
            result = {
                "id": existing.id,
                "key": key,
                "scope": scope,
                "status": "updated",
            }
            self._emit("saved", result)
            return result

        pref = Preference()
        pref.scope = scope
        pref.scope_id = scope_id
        pref.key = key
        pref.instruction = instruction
        pref.created_at = now
        pref.updated_at = now
        await pref.save()

        result = {
            "id": pref.id,
            "key": key,
            "scope": scope,
            "status": "created",
        }
        self._emit("saved", result)
        return result

    async def get_all(self, repo: str) -> dict:
        """Load all applicable preferences, merged from global + workspace + repo.

        Repo overrides workspace overrides global for the same key.
        Semantically similar instructions are deduplicated, keeping the
        narrower scope.
        """
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(f"Repository '{repo}' not found", repo=repo)

        merged: dict[str, dict] = {}

        global_prefs = await Preference.where(scope="global").where_null("scope_id").get()
        for p in global_prefs:
            merged[p.key] = self._pref_to_dict(p)

        await repo_obj.load("workspaces")
        workspaces = repo_obj.workspaces or []
        for ws in workspaces:
            ws_prefs = await Preference.where(scope="workspace", scope_id=ws.id).get()
            for p in ws_prefs:
                merged[p.key] = self._pref_to_dict(p)

        repo_prefs = await Preference.where(scope="repo", scope_id=repo_obj.id).get()
        for p in repo_prefs:
            merged[p.key] = self._pref_to_dict(p)

        preferences = list(merged.values())
        preferences = await self._deduplicate(preferences)

        return {
            "preferences": preferences,
            "count": len(preferences),
            "scopes_loaded": {
                "global": len(global_prefs),
                "workspace": sum(1 for p in preferences if p["scope"] == "workspace"),
                "repo": sum(1 for p in preferences if p["scope"] == "repo"),
            },
        }

    async def delete(
        self,
        key: str,
        scope: str,
        scope_id: int | None = None,
    ) -> dict:
        """Delete a preference by key and scope."""
        if scope not in VALID_SCOPES:
            raise InvalidScopeError(
                f"Invalid scope '{scope}', must be one of: {', '.join(VALID_SCOPES)}",
                scope=scope,
            )

        if scope == "global":
            scope_id = None

        existing = await self._find_preference(scope, scope_id, key)
        if existing is None:
            return {"key": key, "scope": scope, "status": "not_found"}

        await existing.delete()
        result = {"key": key, "scope": scope, "status": "deleted"}
        self._emit("deleted", result)
        return result

    @staticmethod
    def _emit(action: str, data: dict) -> None:
        from sylvan.events import emit

        emit("preference_changed", {"action": action, **data})

    async def _find_preference(self, scope: str, scope_id: int | None, key: str) -> Preference | None:
        """Find a preference by its unique (scope, scope_id, key) triple."""
        query = Preference.where(scope=scope, key=key)
        if scope_id is None:
            query = query.where_null("scope_id")
        else:
            query = query.where(scope_id=scope_id)
        return await query.first()

    def _pref_to_dict(self, pref: Preference) -> dict:
        return {
            "id": pref.id,
            "key": pref.key,
            "instruction": pref.instruction,
            "scope": pref.scope,
            "scope_id": pref.scope_id,
            "created_at": pref.created_at,
            "updated_at": pref.updated_at,
        }

    async def _deduplicate(self, preferences: list[dict]) -> list[dict]:
        """Remove semantically similar preferences, keeping narrower scope."""
        if len(preferences) <= 1:
            return preferences

        provider = get_embedding_provider()
        if provider is None:
            return preferences

        texts = [p["instruction"] for p in preferences]
        try:
            vectors = provider.embed(texts)
        except Exception as e:
            logger.debug("preference_dedup_embed_failed", error=str(e))
            return preferences

        drop = set()
        for i in range(len(vectors)):
            if i in drop:
                continue
            for j in range(i + 1, len(vectors)):
                if j in drop:
                    continue
                sim = self._cosine_similarity(vectors[i], vectors[j])
                if sim > DEDUP_THRESHOLD:
                    pi = SCOPE_PRIORITY.get(preferences[i]["scope"], 0)
                    pj = SCOPE_PRIORITY.get(preferences[j]["scope"], 0)
                    if pi < pj:
                        drop.add(i)
                    else:
                        drop.add(j)

        return [p for idx, p in enumerate(preferences) if idx not in drop]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
