"""Blob model -- content-addressable file storage (zlib compressed)."""

import zlib

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import Column


class Blob(Model):
    """Content-addressable blob store for file contents.

    Files are stored compressed with zlib and deduplicated by content hash.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "blobs"

    content_hash = Column(str, primary_key=True)
    """SHA-256 hash serving as the primary key."""

    content = Column(bytes)
    """Zlib-compressed file content."""

    @classmethod
    async def store(cls, content_hash: str, raw_content: bytes) -> None:
        """Store file content by hash (zlib compressed, deduped).

        Args:
            content_hash: SHA-256 hash of the raw content.
            raw_content: Uncompressed file content bytes.
        """
        compressed = zlib.compress(raw_content, level=6)
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        await backend.execute(
            "INSERT OR IGNORE INTO blobs (content_hash, content) VALUES (?, ?)",
            [content_hash, compressed],
        )

    @classmethod
    async def get(cls, content_hash: str) -> bytes | None:
        """Retrieve and decompress file content by hash.

        Args:
            content_hash: SHA-256 hash to look up.

        Returns:
            The decompressed file content, or None if not found.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        row = await backend.fetch_one(
            "SELECT content FROM blobs WHERE content_hash = ?", [content_hash]
        )
        if row is None:
            return None
        return zlib.decompress(row["content"])
