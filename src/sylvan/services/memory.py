"""Memory service -- save, search, retrieve, delete agent memories."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime

from sylvan.database.orm.models import Memory, Repo
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.error_codes import MemoryNotFoundError, RepoNotFoundError
from sylvan.logging import get_logger
from sylvan.search.embeddings import (
    _vec_to_blob,
    embed_and_store_memories,
    get_embedding_provider,
)

logger = get_logger(__name__)

DEDUP_THRESHOLD = 0.92


class MemoryService:
    """Save and search agent project knowledge with vector deduplication."""

    async def _resolve_repo(self, repo: str) -> Repo:
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(f"Repository '{repo}' not found", repo=repo)
        return repo_obj

    async def save(
        self,
        repo: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict:
        """Save a memory with semantic deduplication.

        If content is >0.92 similar to an existing memory in the same repo,
        updates that memory instead of creating a new one.
        """
        repo_obj = await self._resolve_repo(repo)
        now = datetime.now(UTC).isoformat()
        provider = get_embedding_provider()

        if provider is not None:
            try:
                vectors = provider.embed([content])
            except Exception as e:
                logger.warning("memory_embed_failed", error=str(e))
                vectors = None

            if vectors:
                vec = vectors[0]
                blob = _vec_to_blob(vec)
                existing = await self._find_similar(blob, repo_obj.id)
                if existing is not None:
                    memory_id, distance = existing
                    similarity = 1.0 - distance
                    if similarity > DEDUP_THRESHOLD:
                        memory = await Memory.find(memory_id)
                        if memory is not None:
                            memory.content = content
                            memory.tags = tags or []
                            memory.updated_at = now
                            await memory.save()
                            await self._store_embedding(memory.id, blob)
                            result = {
                                "id": memory.id,
                                "status": "updated",
                                "similarity": round(similarity, 4),
                            }
                            self._emit("saved", result)
                            return result

        memory = Memory()
        memory.repo_id = repo_obj.id
        memory.content = content
        memory.tags = tags or []
        memory.created_at = now
        memory.updated_at = now
        await memory.save()

        if provider is not None and vectors:
            await self._store_embedding(memory.id, _vec_to_blob(vectors[0]))
        elif provider is not None:
            await embed_and_store_memories(provider, [memory.id], [content])

        result = {"id": memory.id, "status": "created"}
        self._emit("saved", result)
        return result

    async def search(
        self,
        repo: str,
        query: str,
        limit: int = 10,
    ) -> dict:
        """Search memories by semantic similarity."""
        repo_obj = await self._resolve_repo(repo)
        provider = get_embedding_provider()

        if provider is None:
            return {"memories": [], "note": "No embedding provider configured"}

        try:
            vectors = provider.embed([query])
        except Exception as e:
            logger.warning("memory_search_embed_failed", error=str(e))
            return {"memories": [], "note": f"Embedding failed: {e}"}

        blob = _vec_to_blob(vectors[0])
        backend = get_backend()

        rows = await backend.fetch_all(
            "SELECT v.memory_id, v.distance, m.content, m.tags, m.created_at, m.updated_at "
            "FROM memories_vec v "
            "JOIN memories m ON m.id = v.memory_id "
            "WHERE v.embedding MATCH ? AND k = ? "
            "AND m.repo_id = ? "
            "ORDER BY v.distance",
            [blob, limit * 3, repo_obj.id],
        )

        memories = []
        for row in rows:
            if len(memories) >= limit:
                break
            r = dict(row)
            tags = r["tags"]
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, TypeError):
                    tags = []
            memories.append(
                {
                    "id": r["memory_id"],
                    "content": r["content"],
                    "tags": tags or [],
                    "similarity": round(1.0 - r["distance"], 4),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )

        return {"memories": memories, "count": len(memories)}

    async def retrieve(self, repo: str, memory_id: int) -> dict:
        """Retrieve a single memory by ID."""
        repo_obj = await self._resolve_repo(repo)
        memory = await Memory.where(id=memory_id, repo_id=repo_obj.id).first()
        if memory is None:
            raise MemoryNotFoundError(
                f"Memory {memory_id} not found in repo '{repo}'",
                memory_id=memory_id,
                repo=repo,
            )
        return {
            "id": memory.id,
            "content": memory.content,
            "tags": memory.tags,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
        }

    async def delete(self, repo: str, memory_id: int) -> dict:
        """Delete a memory and its embedding."""
        repo_obj = await self._resolve_repo(repo)
        memory = await Memory.where(id=memory_id, repo_id=repo_obj.id).first()
        if memory is None:
            raise MemoryNotFoundError(
                f"Memory {memory_id} not found in repo '{repo}'",
                memory_id=memory_id,
                repo=repo,
            )

        backend = get_backend()
        with contextlib.suppress(Exception):
            await backend.execute(
                "DELETE FROM memories_vec WHERE memory_id = ?",
                [memory_id],
            )

        await memory.delete()
        result = {"id": memory_id, "status": "deleted"}
        self._emit("deleted", result)
        return result

    @staticmethod
    def _emit(action: str, data: dict) -> None:
        from sylvan.events import emit

        emit("memory_changed", {"action": action, **data})

    async def _find_similar(self, blob: bytes, repo_id: int) -> tuple[int, float] | None:
        """Find the nearest memory in the same repo. Returns (id, distance)."""
        backend = get_backend()
        try:
            rows = await backend.fetch_all(
                "SELECT v.memory_id, v.distance "
                "FROM memories_vec v "
                "JOIN memories m ON m.id = v.memory_id "
                "WHERE v.embedding MATCH ? AND k = 1 "
                "AND m.repo_id = ?",
                [blob, repo_id],
            )
        except Exception:
            return None

        if rows:
            row = dict(rows[0])
            return row["memory_id"], row["distance"]
        return None

    async def _store_embedding(self, memory_id: int, blob: bytes) -> None:
        """Store or replace a memory embedding."""
        backend = get_backend()
        try:
            await backend.execute(
                "INSERT OR REPLACE INTO memories_vec (memory_id, embedding) VALUES (?, ?)",
                [memory_id, blob],
            )
        except Exception as e:
            logger.debug("memory_embedding_store_failed", memory_id=memory_id, error=str(e))
