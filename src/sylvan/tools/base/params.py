"""Param traits for tool input standardization.

Each trait defines one or more canonical field names with their type,
default, validation, and MCP schema description. Tools compose traits
via multiple inheritance on their Params class to guarantee consistent
field naming across all tools.

Usage::

    class Params(HasRepo, HasSymbol, HasDepth, ToolParams):
        pass

The MCP ``inputSchema`` is generated automatically from the combined
type hints via ``ToolParams.to_schema()``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, get_type_hints

# Sentinel for required fields (no default).
REQUIRED = object()


class _FieldSpec:
    """Metadata for a single param field."""

    __slots__ = ("default", "description", "enum", "ge", "le")

    def __init__(
        self,
        *,
        description: str,
        default: Any = REQUIRED,
        ge: int | None = None,
        le: int | None = None,
        enum: list[str] | None = None,
    ) -> None:
        self.default = default
        self.description = description
        self.ge = ge
        self.le = le
        self.enum = enum

    @property
    def is_required(self) -> bool:
        return self.default is REQUIRED


def schema_field(
    *,
    description: str,
    default: Any = REQUIRED,
    ge: int | None = None,
    le: int | None = None,
    enum: list[str] | None = None,
) -> Any:
    """Declare a param field with MCP schema metadata.

    Args:
        description: Human-readable description for the MCP schema.
        default: Default value. Omit for required fields.
        ge: Minimum value (inclusive) for numeric fields.
        le: Maximum value (inclusive) for numeric fields.
        enum: Allowed string values.

    Returns:
        A ``_FieldSpec`` that ToolParams reads during schema generation.
    """
    return _FieldSpec(
        description=description,
        default=default,
        ge=ge,
        le=le,
        enum=enum,
    )


class HasRepo:
    """Tool accepts a required repository name."""

    repo: str = schema_field(description="Repository name (as shown in list_repos)")


class HasOptionalRepo:
    """Tool accepts an optional repository filter."""

    repo: str | None = schema_field(
        default=None,
        description="Filter to a specific repository (as shown in list_repos)",
    )


class HasSymbol:
    """Tool accepts a required symbol identifier."""

    symbol_id: str = schema_field(
        description="Symbol identifier (from search_symbols or get_file_outline results)",
    )


class HasOptionalSymbol:
    """Tool accepts an optional symbol identifier."""

    symbol_id: str | None = schema_field(
        default=None,
        description="Symbol identifier (from search_symbols or get_file_outline results)",
    )


class HasQuery:
    """Tool accepts a required search query."""

    query: str = schema_field(
        description="Search query (name, keyword, or description)",
    )


class HasFilePath:
    """Tool accepts a required relative file path."""

    file_path: str = schema_field(
        description="Relative file path within the repository (e.g., 'src/main.py')",
    )


class HasOptionalFilePath:
    """Tool accepts an optional file path filter."""

    file_path: str | None = schema_field(
        default=None,
        description="Relative file path within the repository (e.g., 'src/main.py')",
    )


class HasPagination:
    """Tool accepts a max_results pagination param."""

    max_results: int = schema_field(
        default=20,
        ge=1,
        le=1000,
        description="Maximum results to return",
    )


class HasDepth:
    """Tool accepts an import-hop depth param."""

    depth: int = schema_field(
        default=2,
        ge=1,
        le=3,
        description="Import hops to follow (1-3)",
    )


class HasKindFilter:
    """Tool accepts an optional symbol kind filter."""

    kind: str | None = schema_field(
        default=None,
        description="Filter by symbol kind",
        enum=["function", "class", "method", "constant", "type"],
    )


class HasLanguageFilter:
    """Tool accepts an optional language filter."""

    language: str | None = schema_field(
        default=None,
        description="Filter by programming language (e.g., python, typescript, go)",
    )


class HasFileFilter:
    """Tool accepts an optional glob pattern to filter files."""

    file_pattern: str | None = schema_field(
        default=None,
        description="Glob pattern to filter by file path (e.g., 'src/**/*.py')",
    )


class HasWorkspace:
    """Tool accepts a required workspace name."""

    workspace: str = schema_field(description="Workspace name")


class HasProjectPath:
    """Tool accepts a project path for editor configuration."""

    project_path: str = schema_field(
        description="Absolute path to the project directory",
    )


class HasOptionalProjectPath:
    """Tool accepts an optional project path."""

    project_path: str | None = schema_field(
        default=None,
        description="Absolute path to the project directory",
    )


class HasContextLines:
    """Tool accepts a context_lines param for surrounding code."""

    context_lines: int = schema_field(
        default=0,
        ge=0,
        le=50,
        description="Number of surrounding lines to include",
    )


class HasVerify:
    """Tool accepts a verify flag for content hash validation."""

    verify: bool = schema_field(
        default=False,
        description="Verify content hasn't drifted since indexing",
    )


class HasDirection:
    """Tool accepts a direction param for graph traversal."""

    direction: str = schema_field(
        default="both",
        description="Traversal direction",
        enum=["imports", "importers", "both"],
    )


class HasMaxDepth:
    """Tool accepts a max_depth param for tree traversal."""

    max_depth: int = schema_field(
        default=3,
        ge=1,
        le=10,
        description="Maximum depth to expand",
    )


class HasDocPath:
    """Tool accepts an optional document path filter."""

    doc_path: str | None = schema_field(
        default=None,
        description="Filter to a specific document",
    )


class HasSymbolIds:
    """Tool accepts a list of symbol identifiers."""

    symbol_ids: list[str] = schema_field(
        description="List of symbol identifiers",
    )


class HasFilePaths:
    """Tool accepts a list of file paths."""

    file_paths: list[str] = schema_field(
        description="List of relative file paths",
    )


class HasSectionId:
    """Tool accepts a required section identifier."""

    section_id: str = schema_field(
        description="Section identifier (from search_sections or get_toc results)",
    )


class HasSectionIds:
    """Tool accepts a list of section identifiers."""

    section_ids: list[str] = schema_field(
        description="List of section identifiers",
    )


# Python type -> JSON schema type
_TYPE_MAP: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolParams:
    """Base class for tool Params.

    Collects fields from all trait parents via MRO, generates MCP JSON
    schema, and constructs instances from raw dicts. Handles the field
    ordering problem by sorting required fields before optional ones
    internally.

    Usage::

        class Params(HasRepo, HasPagination, ToolParams):
            custom: str = schema_field(description="Custom field")

    For mutually-exclusive optional fields where at least one is required::

        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]

    For fields that cannot be provided together::

        class Params(HasOptionalSymbol, HasSymbolIds, ToolParams):
            mutually_exclusive = [("symbol_id", "symbol_ids")]
    """

    require_any_of: ClassVar[list[tuple[str, ...]]] = []
    mutually_exclusive: ClassVar[list[tuple[str, ...]]] = []

    def __init__(self, **kwargs: Any) -> None:
        """Construct params, coercing types and applying defaults."""
        field_specs = self._collect_fields()
        hints = self._collect_hints()

        for name, spec in field_specs.items():
            if name in kwargs:
                raw = kwargs[name]
                expected = hints.get(name)
                setattr(self, name, _coerce(raw, expected))
            elif not spec.is_required:
                setattr(self, name, spec.default)
            else:
                raise TypeError(f"Missing required parameter: {name}")

        self._validate_constraints()

    def _validate_constraints(self) -> None:
        """Check require_any_of and mutually_exclusive after field assignment."""
        for group in self.__class__.require_any_of:
            values = [getattr(self, name, None) for name in group]
            if all(v is None for v in values):
                names = ", ".join(group)
                raise TypeError(f"Provide at least one of: {names}")

        for group in self.__class__.mutually_exclusive:
            provided = [name for name in group if getattr(self, name, None) is not None]
            if len(provided) > 1:
                names = ", ".join(group)
                raise TypeError(f"Provide only one of: {names}")

    @classmethod
    def _collect_hints(cls) -> dict[str, Any]:
        """Collect resolved type hints from the MRO."""
        hints: dict[str, Any] = {}
        for parent in reversed(cls.__mro__):
            if parent is object:
                continue
            try:
                resolved = get_type_hints(parent)
                hints.update(resolved)
            except Exception:
                ann = getattr(parent, "__annotations__", {})
                hints.update(ann)
        return hints

    @classmethod
    def _collect_fields(cls) -> dict[str, _FieldSpec]:
        """Walk the MRO and collect all _FieldSpec fields from traits.

        Returns fields in a stable order: required first, then optional.
        """
        fields: dict[str, _FieldSpec] = {}

        # Walk MRO in reverse so more specific classes override base ones
        for parent in reversed(cls.__mro__):
            if parent is object or parent is ToolParams:
                continue
            for attr_name, attr_val in vars(parent).items():
                if isinstance(attr_val, _FieldSpec):
                    fields[attr_name] = attr_val  # noqa: PERF403

        # Sort: required first, then optional (stable within each group)
        required = {k: v for k, v in fields.items() if v.is_required}
        optional = {k: v for k, v in fields.items() if not v.is_required}
        return {**required, **optional}

    @classmethod
    def to_schema(cls) -> dict:
        """Generate an MCP-compatible JSON schema from collected fields.

        Returns:
            ``{"type": "object", "properties": {...}, "required": [...]}``
        """
        field_specs = cls._collect_fields()
        hints = cls._collect_hints()

        properties: dict[str, dict] = {}
        required: list[str] = []

        for name, spec in field_specs.items():
            raw_type = hints.get(name, str)
            prop = _type_to_schema(raw_type)

            prop["description"] = spec.description
            if spec.ge is not None:
                prop["minimum"] = spec.ge
            if spec.le is not None:
                prop["maximum"] = spec.le
            if spec.enum is not None:
                prop["enum"] = spec.enum

            if spec.is_required:
                required.append(name)
            else:
                prop["default"] = spec.default

            properties[name] = prop

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    @classmethod
    def from_dict(cls, data: dict) -> ToolParams:
        """Construct a Params instance from a raw arguments dict.

        Filters out unknown keys and applies defaults for missing fields.
        """
        valid_names = set(cls._collect_fields())
        filtered = {k: v for k, v in data.items() if k in valid_names}
        return cls(**filtered)


def _coerce(value: Any, expected_type: Any) -> Any:
    """Coerce a raw MCP value to the expected Python type.

    MCP clients sometimes send ``"5"`` instead of ``5``, or ``"true"``
    instead of ``True``. This handles the common cases without failing
    on values that are already the right type.
    """
    if value is None or expected_type is None:
        return value

    # Unwrap Optional (X | None) to get the inner type
    origin = getattr(expected_type, "__origin__", None)
    args = getattr(expected_type, "__args__", ())

    if origin is None and hasattr(expected_type, "__args__"):
        args = expected_type.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _coerce(value, non_none[0])

    if origin is not None:
        import typing

        if origin is typing.Union:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _coerce(value, non_none[0])
        return value

    # str -> int
    if expected_type is int and isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return value

    # str -> float
    if expected_type is float and isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    # str -> bool
    if expected_type is bool and isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        return value

    # int/float -> str (when field expects string)
    if expected_type is str and not isinstance(value, str):
        return str(value)

    return value


def _type_to_schema(raw_type: Any) -> dict:
    """Convert a Python type annotation to a JSON schema fragment.

    Handles ``str``, ``int``, ``float``, ``bool``, ``list[X]``,
    ``X | None`` (Optional), and ``Literal["a", "b"]``.
    """
    origin = getattr(raw_type, "__origin__", None)
    args = getattr(raw_type, "__args__", ())

    # types.UnionType (3.10+ X | Y)
    if origin is None and hasattr(raw_type, "__args__"):
        args = raw_type.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_schema(non_none[0])

    # typing.Union / Optional
    if origin is not None:
        import typing

        if origin is typing.Union:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _type_to_schema(non_none[0])

        # typing.Literal
        if origin is Literal:
            return {"type": "string", "enum": list(args)}

        # list[X]
        if origin is list:
            item_schema = _type_to_schema(args[0]) if args else {"type": "string"}
            return {"type": "array", "items": item_schema}

    # Simple types
    json_type = _TYPE_MAP.get(raw_type, "string")
    return {"type": json_type}
