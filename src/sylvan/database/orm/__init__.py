"""Sylvan ORM — Async Active Record with native FTS5 + sqlite-vec support.

Usage:
    from sylvan.database.orm import Symbol, Section, FileRecord, Repo

    # Fluent queries — filter methods are sync, terminals are async
    symbols = await Symbol.where(kind="function").order_by("name").limit(10).get()

    # FTS5 search
    results = await Symbol.search("parse file").where(language="go").get()

    # Vector similarity (the sauce)
    results = await Symbol.similar_to("authentication login", k=10).get()

    # Hybrid search (BM25 + vector, RRF fusion)
    results = await Symbol.search("auth").similar_to("login", weight=0.3).get()

    # Relationships — eager load or explicit async load
    symbols = await Symbol.where(kind="function").with_("file", "children").get()
    await symbol.load("file")   # explicit async load

    # Scopes
    await Symbol.functions().in_repo("sylvan").get()

    # CRUD — all async
    sym = await Symbol.create(name="foo", kind="function", file_id=1)
    await sym.update(summary="Updated")
    await sym.delete()
"""

from sylvan.database.orm.exceptions import ModelNotFoundError, ORMError, QueryError, ValidationError
from sylvan.database.orm.model.base import Model
from sylvan.database.orm.models import (
    Blob,
    CodingSession,
    FileImport,
    FileRecord,
    Instance,
    Quality,
    Reference,
    Repo,
    Section,
    Symbol,
    UsageStats,
    Workspace,
)
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import (
    BelongsTo,
    BelongsToMany,
    HasMany,
    HasOne,
    RelationNotLoadedError,
)
from sylvan.database.orm.primitives.scopes import scope
from sylvan.database.orm.query.builder import QueryBuilder
from sylvan.database.orm.query.execution import Avg, Count, Max, Min, Sum
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.database.orm.runtime.transaction import transaction

__all__ = [
    "AutoPrimaryKey",
    "Avg",
    "BelongsTo",
    "BelongsToMany",
    "Blob",
    "CodingSession",
    "Column",
    "Count",
    "FileImport",
    "FileRecord",
    "HasMany",
    "HasOne",
    "Instance",
    "JsonColumn",
    "Max",
    "Min",
    "Model",
    "ModelNotFoundError",
    "ORMError",
    "Quality",
    "QueryBuilder",
    "QueryError",
    "Reference",
    "RelationNotLoadedError",
    "Repo",
    "Section",
    "Sum",
    "Symbol",
    "UsageStats",
    "ValidationError",
    "Workspace",
    "get_backend",
    "scope",
    "transaction",
]
