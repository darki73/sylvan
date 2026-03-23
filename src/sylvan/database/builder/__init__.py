"""Fluent schema builder for database migrations.

Public API::

    from sylvan.database.builder import Schema, Blueprint
    from sylvan.database.builder import Column, ColumnType
    from sylvan.database.builder import FtsTable, VecTable
"""

from sylvan.database.builder.blueprint import (
    Blueprint,
    Column,
    ColumnType,
    CompositePK,
    FtsTable,
    IndexDef,
    VecTable,
)
from sylvan.database.builder.schema import Schema

__all__ = [
    "Blueprint",
    "Column",
    "ColumnType",
    "CompositePK",
    "FtsTable",
    "IndexDef",
    "Schema",
    "VecTable",
]
