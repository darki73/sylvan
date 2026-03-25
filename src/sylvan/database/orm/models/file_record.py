"""FileRecord model -- indexed files."""

import zlib

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column
from sylvan.database.orm.primitives.relations import BelongsTo, HasMany


class FileRecord(Model):
    """Represents an indexed source or documentation file.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "files"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    repo_id = Column(int)
    """Foreign key to the repos table."""

    path = Column(str)
    """Relative file path within the repository."""

    language = Column(str, nullable=True)
    """Detected programming language."""

    content_hash = Column(str)
    """SHA-256 hash of the raw file content."""

    byte_size = Column(int)
    """File size in bytes."""

    mtime = Column(float, nullable=True)
    """File modification time as a Unix timestamp."""

    repo = BelongsTo("Repo", foreign_key="repo_id")
    """Parent repository."""

    symbols = HasMany("Symbol", foreign_key="file_id")
    """Symbols extracted from this file."""

    sections = HasMany("Section", foreign_key="file_id")
    """Documentation sections extracted from this file."""

    async def get_content(self) -> bytes | None:
        """Get decompressed file content from the blob store.

        Returns:
            The decompressed file content bytes, or None if not found.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        row = await backend.fetch_one("SELECT content FROM blobs WHERE content_hash = ?", [self.content_hash])
        if row is None:
            return None
        return zlib.decompress(row["content"])
