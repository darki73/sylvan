"""Bulk registration for languages with tree-sitter specs only.

These languages have no custom import extraction, resolution, or complexity
patterns. They rely on tree-sitter for symbol extraction and text search
for everything else.
"""

from __future__ import annotations

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec


class _Stub:
    """No-capability language plugin."""

    pass


_SPECS: dict[str, tuple[list[str], LanguageSpec]] = {
    "scala": (
        [".scala", ".sc"],
        LanguageSpec(
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
    ),
    "dart": (
        [".dart"],
        LanguageSpec(
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
    ),
    "bash": (
        [".sh", ".bash"],
        LanguageSpec(
            ts_language="bash",
            symbol_node_types={"function_definition": "function"},
            name_fields={"function_definition": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "elixir": (
        [".ex", ".exs"],
        LanguageSpec(
            ts_language="elixir",
            symbol_node_types={"call": "function"},
            name_fields={"call": "target"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "lua": (
        [".lua"],
        LanguageSpec(
            ts_language="lua",
            symbol_node_types={"function_declaration": "function"},
            name_fields={"function_declaration": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "perl": (
        [".pl", ".pm", ".t"],
        LanguageSpec(
            ts_language="perl",
            symbol_node_types={"function_definition": "function"},
            name_fields={"function_definition": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "haskell": (
        [".hs", ".lhs"],
        LanguageSpec(
            ts_language="haskell",
            symbol_node_types={"function": "function", "signature": "type"},
            name_fields={"function": "name", "signature": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "erlang": (
        [".erl", ".hrl"],
        LanguageSpec(
            ts_language="erlang",
            symbol_node_types={"function_clause": "function"},
            name_fields={"function_clause": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "gleam": (
        [".gleam"],
        LanguageSpec(
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
    ),
    "hcl": (
        [".tf", ".hcl", ".tfvars"],
        LanguageSpec(
            ts_language="hcl",
            symbol_node_types={"block": "type"},
            name_fields={"block": "type"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "sql": (
        [".sql"],
        LanguageSpec(
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
    ),
    "graphql": (
        [".graphql", ".gql"],
        LanguageSpec(
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
    ),
    "proto": (
        [".proto"],
        LanguageSpec(
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
    ),
    "objc": (
        [".m", ".mm"],
        LanguageSpec(
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
    ),
    "groovy": (
        [".groovy", ".gradle"],
        LanguageSpec(
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
    ),
    "fortran": (
        [".f90", ".f95", ".f03", ".f08", ".f", ".for", ".fpp"],
        LanguageSpec(
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
    ),
    "nix": (
        [".nix"],
        LanguageSpec(
            ts_language="nix",
            symbol_node_types={"binding": "function"},
            name_fields={"binding": "attrpath"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "gdscript": (
        [".gd"],
        LanguageSpec(
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
    ),
    "r": (
        [".r", ".R"],
        LanguageSpec(
            ts_language="r",
            symbol_node_types={"function_definition": "function"},
            name_fields={"function_definition": "name"},
            docstring_strategy="preceding_comment",
        ),
    ),
    "julia": (
        [".jl"],
        LanguageSpec(
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
    ),
    "css": (
        [".css"],
        LanguageSpec(
            ts_language="css",
            symbol_node_types={
                "rule_set": "type",
                "media_statement": "type",
                "keyframes_statement": "function",
                "import_statement": "constant",
            },
            name_fields={
                "rule_set": "selectors",
                "keyframes_statement": "name",
                "media_statement": "condition",
            },
            docstring_strategy="preceding_comment",
        ),
    ),
}

for _name, (_exts, _spec) in _SPECS.items():
    register(name=_name, extensions=_exts, spec=_spec)(_Stub)
