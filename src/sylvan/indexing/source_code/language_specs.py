"""Language registry mapping file extensions to tree-sitter languages and extraction config."""

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class LanguageSpec:
    """Configuration for extracting symbols from a specific language.

    Attributes:
        ts_language: Tree-sitter language name.
        symbol_node_types: Mapping of AST node types to symbol kinds.
        name_fields: Mapping of AST node types to field names for extracting the symbol name.
        param_fields: Mapping of node types to parameter field names.
        return_type_fields: Mapping of node types to return type field names.
        docstring_strategy: Strategy for extracting docstrings.
        decorator_node_type: AST node type for decorators/annotations, if applicable.
        container_node_types: AST node types that contain nested symbols (e.g., class bodies).
        constant_patterns: AST patterns for constant detection.
        type_patterns: AST patterns for type definition detection.
    """

    ts_language: str
    symbol_node_types: dict[str, str]
    name_fields: dict[str, str]
    param_fields: dict[str, str] = field(default_factory=dict)
    return_type_fields: dict[str, str] = field(default_factory=dict)
    docstring_strategy: str = "preceding_comment"  # preceding_comment | next_sibling_string
    decorator_node_type: str | None = None
    container_node_types: list[str] = field(default_factory=list)
    constant_patterns: list[str] = field(default_factory=list)
    type_patterns: list[str] = field(default_factory=list)


LANGUAGE_EXTENSIONS: dict[str, str] = {
    # Python
    ".py": "python", ".pyi": "python", ".pyx": "python",
    # JavaScript
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    # TypeScript
    ".ts": "typescript", ".tsx": "tsx",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rust",
    # Java
    ".java": "java",
    # Kotlin
    ".kt": "kotlin", ".kts": "kotlin",
    # C
    ".c": "c",
    # C++
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    # C header (defaults to C, heuristic may upgrade to C++)
    ".h": "c",
    # C#
    ".cs": "c_sharp",
    # Swift
    ".swift": "swift",
    # Ruby
    ".rb": "ruby", ".rake": "ruby",
    # PHP
    ".php": "php",
    # Scala
    ".scala": "scala", ".sc": "scala",
    # Dart
    ".dart": "dart",
    # Elixir
    ".ex": "elixir", ".exs": "elixir",
    # Lua
    ".lua": "lua",
    # Perl
    ".pl": "perl", ".pm": "perl", ".t": "perl",
    # Bash/Shell
    ".sh": "bash", ".bash": "bash",
    # Haskell
    ".hs": "haskell", ".lhs": "haskell",
    # Julia
    ".jl": "julia",
    # R
    ".r": "r", ".R": "r",
    # Erlang
    ".erl": "erlang", ".hrl": "erlang",
    # Fortran
    ".f90": "fortran", ".f95": "fortran", ".f03": "fortran", ".f08": "fortran",
    ".f": "fortran", ".for": "fortran", ".fpp": "fortran",
    # SQL
    ".sql": "sql",
    # Objective-C
    ".m": "objc", ".mm": "objc",
    # Protocol Buffers
    ".proto": "proto",
    # HCL/Terraform
    ".tf": "hcl", ".hcl": "hcl", ".tfvars": "hcl",
    # GraphQL
    ".graphql": "graphql", ".gql": "graphql",
    # Groovy
    ".groovy": "groovy", ".gradle": "groovy",
    # Nix
    ".nix": "nix",
    # Vue
    ".vue": "vue",
    # GDScript (Godot)
    ".gd": "gdscript",
    # Gleam
    ".gleam": "gleam",
    # CSS
    ".css": "css",
    # TOML
    ".toml": "toml",
    # YAML
    ".yaml": "yaml", ".yml": "yaml",
    # Assembly
    ".asm": "asm", ".s": "asm", ".S": "asm", ".inc": "asm",
    # XML
    ".xml": "xml", ".xul": "xml",
}
"""Mapping of file extensions to language identifiers."""

LANGUAGE_REGISTRY: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        ts_language="python",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
        },
        param_fields={"function_definition": "parameters"},
        return_type_fields={"function_definition": "return_type"},
        docstring_strategy="next_sibling_string",
        decorator_node_type="decorator",
        container_node_types=["class_definition"],
        constant_patterns=["assignment"],
    ),
    "javascript": LanguageSpec(
        ts_language="javascript",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "class"],
    ),
    "typescript": LanguageSpec(
        ts_language="typescript",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
            "interface_declaration": "type",
            "type_alias_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
            "interface_declaration": "name",
            "type_alias_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        return_type_fields={
            "function_declaration": "return_type",
            "method_definition": "return_type",
        },
        docstring_strategy="preceding_comment",
        decorator_node_type="decorator",
        container_node_types=["class_declaration", "class"],
    ),
    "tsx": LanguageSpec(
        ts_language="tsx",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "method_definition": "method",
            "interface_declaration": "type",
            "type_alias_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "method_definition": "name",
            "interface_declaration": "name",
            "type_alias_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        decorator_node_type="decorator",
        container_node_types=["class_declaration", "class"],
    ),
    "go": LanguageSpec(
        ts_language="go",
        symbol_node_types={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "type",
            "const_declaration": "constant",
        },
        name_fields={
            "function_declaration": "name",
            "method_declaration": "name",
            "type_declaration": "name",
        },
        param_fields={
            "function_declaration": "parameters",
            "method_declaration": "parameters",
        },
        return_type_fields={
            "function_declaration": "result",
            "method_declaration": "result",
        },
        docstring_strategy="preceding_comment",
    ),
    "rust": LanguageSpec(
        ts_language="rust",
        symbol_node_types={
            "function_item": "function",
            "struct_item": "type",
            "enum_item": "type",
            "trait_item": "type",
            "impl_item": "type",
            "type_item": "type",
            "const_item": "constant",
            "static_item": "constant",
        },
        name_fields={
            "function_item": "name",
            "struct_item": "name",
            "enum_item": "name",
            "trait_item": "name",
            "impl_item": "trait",
            "type_item": "name",
            "const_item": "name",
            "static_item": "name",
        },
        param_fields={"function_item": "parameters"},
        return_type_fields={"function_item": "return_type"},
        docstring_strategy="preceding_comment",
        container_node_types=["impl_item", "trait_item"],
    ),
    "java": LanguageSpec(
        ts_language="java",
        symbol_node_types={
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "type",
            "enum_declaration": "type",
            "constructor_declaration": "method",
        },
        name_fields={
            "method_declaration": "name",
            "class_declaration": "name",
            "interface_declaration": "name",
            "enum_declaration": "name",
            "constructor_declaration": "name",
        },
        param_fields={
            "method_declaration": "parameters",
            "constructor_declaration": "parameters",
        },
        return_type_fields={"method_declaration": "type"},
        docstring_strategy="preceding_comment",
        decorator_node_type="marker_annotation",
        container_node_types=["class_declaration", "interface_declaration", "enum_declaration"],
    ),
    "c": LanguageSpec(
        ts_language="c",
        symbol_node_types={
            "function_definition": "function",
            "struct_specifier": "type",
            "enum_specifier": "type",
            "union_specifier": "type",
            "type_definition": "type",
        },
        name_fields={
            "function_definition": "declarator",
            "struct_specifier": "name",
            "enum_specifier": "name",
            "union_specifier": "name",
            "type_definition": "declarator",
        },
        docstring_strategy="preceding_comment",
    ),
    "cpp": LanguageSpec(
        ts_language="cpp",
        symbol_node_types={
            "function_definition": "function",
            "class_specifier": "class",
            "struct_specifier": "type",
            "enum_specifier": "type",
            "namespace_definition": "type",
            "template_declaration": "template",
        },
        name_fields={
            "function_definition": "declarator",
            "class_specifier": "name",
            "struct_specifier": "name",
            "enum_specifier": "name",
            "namespace_definition": "name",
            "template_declaration": "declarator",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_specifier", "struct_specifier", "namespace_definition"],
    ),
    "c_sharp": LanguageSpec(
        ts_language="csharp",
        symbol_node_types={
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "type",
            "enum_declaration": "type",
            "struct_declaration": "type",
            "constructor_declaration": "method",
        },
        name_fields={
            "method_declaration": "name",
            "class_declaration": "name",
            "interface_declaration": "name",
            "enum_declaration": "name",
            "struct_declaration": "name",
            "constructor_declaration": "name",
        },
        param_fields={
            "method_declaration": "parameters",
            "constructor_declaration": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "interface_declaration", "struct_declaration"],
    ),
    "ruby": LanguageSpec(
        ts_language="ruby",
        symbol_node_types={
            "method": "method",
            "singleton_method": "method",
            "class": "class",
            "module": "class",
        },
        name_fields={
            "method": "name",
            "singleton_method": "name",
            "class": "name",
            "module": "name",
        },
        param_fields={"method": "parameters", "singleton_method": "parameters"},
        docstring_strategy="preceding_comment",
        container_node_types=["class", "module"],
    ),
    "php": LanguageSpec(
        ts_language="php",
        symbol_node_types={
            "function_definition": "function",
            "method_declaration": "method",
            "class_declaration": "class",
            "interface_declaration": "type",
            "trait_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={
            "function_definition": "name",
            "method_declaration": "name",
            "class_declaration": "name",
            "interface_declaration": "name",
            "trait_declaration": "name",
            "enum_declaration": "name",
        },
        param_fields={
            "function_definition": "parameters",
            "method_declaration": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "interface_declaration", "trait_declaration"],
    ),
    "swift": LanguageSpec(
        ts_language="swift",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "struct_declaration": "type",
            "enum_declaration": "type",
            "protocol_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "struct_declaration": "name",
            "enum_declaration": "name",
            "protocol_declaration": "name",
        },
        param_fields={"function_declaration": "parameters"},
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "struct_declaration"],
    ),
    "kotlin": LanguageSpec(
        ts_language="kotlin",
        symbol_node_types={
            "function_declaration": "function",
            "class_declaration": "class",
            "object_declaration": "class",
            "interface_declaration": "type",
        },
        name_fields={
            "function_declaration": "name",
            "class_declaration": "name",
            "object_declaration": "name",
            "interface_declaration": "name",
        },
        param_fields={"function_declaration": "value_parameters"},
        docstring_strategy="preceding_comment",
        container_node_types=["class_declaration", "object_declaration", "interface_declaration"],
    ),
    "scala": LanguageSpec(
        ts_language="scala",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
            "object_definition": "class",
            "trait_definition": "type",
            "val_definition": "constant",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
            "object_definition": "name",
            "trait_definition": "name",
            "val_definition": "pattern",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_definition", "object_definition", "trait_definition"],
    ),
    "dart": LanguageSpec(
        ts_language="dart",
        symbol_node_types={
            "function_signature": "function",
            "method_signature": "method",
            "class_definition": "class",
            "mixin_declaration": "type",
            "enum_declaration": "type",
            "extension_declaration": "type",
        },
        name_fields={
            "function_signature": "name",
            "method_signature": "name",
            "class_definition": "name",
            "mixin_declaration": "name",
            "enum_declaration": "name",
            "extension_declaration": "name",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_definition", "mixin_declaration"],
    ),
    "bash": LanguageSpec(
        ts_language="bash",
        symbol_node_types={
            "function_definition": "function",
        },
        name_fields={
            "function_definition": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "elixir": LanguageSpec(
        ts_language="elixir",
        symbol_node_types={
            "call": "function",  # def/defp/defmodule are all call nodes in elixir grammar
        },
        name_fields={
            "call": "target",
        },
        docstring_strategy="preceding_comment",
    ),
    "lua": LanguageSpec(
        ts_language="lua",
        symbol_node_types={
            "function_declaration": "function",
        },
        name_fields={
            "function_declaration": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "perl": LanguageSpec(
        ts_language="perl",
        symbol_node_types={
            "function_definition": "function",
        },
        name_fields={
            "function_definition": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "haskell": LanguageSpec(
        ts_language="haskell",
        symbol_node_types={
            "function": "function",
            "signature": "type",
        },
        name_fields={
            "function": "name",
            "signature": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "erlang": LanguageSpec(
        ts_language="erlang",
        symbol_node_types={
            "function_clause": "function",
        },
        name_fields={
            "function_clause": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "gleam": LanguageSpec(
        ts_language="gleam",
        symbol_node_types={
            "function": "function",
            "type_definition": "type",
            "constant": "constant",
        },
        name_fields={
            "function": "name",
            "type_definition": "name",
            "constant": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "hcl": LanguageSpec(
        ts_language="hcl",
        symbol_node_types={
            "block": "type",  # resource, data, module blocks
        },
        name_fields={
            "block": "type",
        },
        docstring_strategy="preceding_comment",
    ),
    "sql": LanguageSpec(
        ts_language="sql",
        symbol_node_types={
            "create_function_statement": "function",
            "create_table_statement": "type",
            "create_view_statement": "type",
            "create_index_statement": "type",
        },
        name_fields={
            "create_function_statement": "name",
            "create_table_statement": "name",
            "create_view_statement": "name",
            "create_index_statement": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "graphql": LanguageSpec(
        ts_language="graphql",
        symbol_node_types={
            "type_definition": "type",
            "field_definition": "function",
            "operation_definition": "function",
        },
        name_fields={
            "type_definition": "name",
            "field_definition": "name",
            "operation_definition": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "proto": LanguageSpec(
        ts_language="proto",
        symbol_node_types={
            "message": "type",
            "enum": "type",
            "service": "type",
            "rpc": "function",
        },
        name_fields={
            "message": "name",
            "enum": "name",
            "service": "name",
            "rpc": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "objc": LanguageSpec(
        ts_language="objc",
        symbol_node_types={
            "class_interface": "class",
            "class_implementation": "class",
            "method_declaration": "method",
            "function_definition": "function",
        },
        name_fields={
            "class_interface": "name",
            "class_implementation": "name",
            "method_declaration": "selector",
            "function_definition": "declarator",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_interface", "class_implementation"],
    ),
    "groovy": LanguageSpec(
        ts_language="groovy",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
            "method_declaration": "method",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
            "method_declaration": "name",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_definition"],
    ),
    "fortran": LanguageSpec(
        ts_language="fortran",
        symbol_node_types={
            "function": "function",
            "subroutine": "function",
            "module": "type",
            "program": "type",
        },
        name_fields={
            "function": "name",
            "subroutine": "name",
            "module": "name",
            "program": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "nix": LanguageSpec(
        ts_language="nix",
        symbol_node_types={
            "binding": "function",  # let bindings
        },
        name_fields={
            "binding": "attrpath",
        },
        docstring_strategy="preceding_comment",
    ),
    "gdscript": LanguageSpec(
        ts_language="gdscript",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_definition"],
    ),
    "r": LanguageSpec(
        ts_language="r",
        symbol_node_types={
            "function_definition": "function",
        },
        name_fields={
            "function_definition": "name",
        },
        docstring_strategy="preceding_comment",
    ),
    "julia": LanguageSpec(
        ts_language="julia",
        symbol_node_types={
            "function_definition": "function",
            "short_function_definition": "function",
            "struct_definition": "type",
            "module_definition": "type",
        },
        name_fields={
            "function_definition": "name",
            "short_function_definition": "name",
            "struct_definition": "name",
            "module_definition": "name",
        },
        docstring_strategy="preceding_comment",
    ),
}
"""Language extraction specs indexed by language identifier."""

CUSTOM_EXTRACTION_LANGUAGES: frozenset[str] = frozenset({
    "asm", "vue", "css", "toml", "yaml",
})
"""Languages where tree-sitter extraction may be incomplete."""


from sylvan.indexing.source_code.language_registry import (
    get_language_for_extension,
    get_language_spec,
    register_language,
)

for _name, _spec in LANGUAGE_REGISTRY.items():
    _exts = [ext for ext, lang in LANGUAGE_EXTENSIONS.items() if lang == _name]
    register_language(_name, _exts)(_spec)


def detect_language(filename: str) -> str | None:
    """Detect language from file extension.

    Args:
        filename: File name or relative path.

    Returns:
        Language identifier string, or None if unrecognized.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return get_language_for_extension(ext)


def get_spec(language: str) -> LanguageSpec | None:
    """Get the extraction spec for a language.

    Args:
        language: Language identifier (e.g., "python", "typescript").

    Returns:
        LanguageSpec for the language, or None if unsupported.
    """
    return get_language_spec(language)
