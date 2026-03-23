"""FileImport model -- import/require statements."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo


class FileImport(Model):
    """Represents an import or require statement extracted from a source file.

    Attributes:
        __table__: Database table name.
    """

    __table__ = "file_imports"

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    file_id = Column(int)
    """Foreign key to the files table."""

    specifier = Column(str)
    """The import specifier (e.g., 'os.path' or 'react')."""

    names = JsonColumn(list)
    """List of imported names from the specifier."""

    resolved_file_id = Column(int, nullable=True)
    """Foreign key to the resolved target file, if known."""

    file = BelongsTo("FileRecord", foreign_key="file_id")
    """Source file containing this import."""

    resolved_file = BelongsTo("FileRecord", foreign_key="resolved_file_id")
    """Resolved target file, if the import could be resolved."""
