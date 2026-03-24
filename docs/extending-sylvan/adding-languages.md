# Adding Languages

Language support is driven by `LanguageSpec` -- a frozen dataclass that tells
the tree-sitter extractor which AST node types map to symbols, where to find
names and parameters, and how to extract docstrings. All specs live in a single
registry dict.

**Quick start:** To add a language without modifying sylvan's source, create a Python file in `~/.sylvan/extensions/languages/` that uses `@register_language`. See the extension example below, then restart the server.

## The LanguageSpec dataclass

```python
# src/sylvan/indexing/source_code/language_specs.py

@dataclass(slots=True, frozen=True)
class LanguageSpec:
    ts_language: str                                    # tree-sitter grammar name
    symbol_node_types: dict[str, str]                   # AST node type -> symbol kind
    name_fields: dict[str, str]                         # AST node type -> name field
    param_fields: dict[str, str] = field(default_factory=dict)
    return_type_fields: dict[str, str] = field(default_factory=dict)
    docstring_strategy: str = "preceding_comment"       # or "next_sibling_string"
    decorator_node_type: str | None = None
    container_node_types: list[str] = field(default_factory=list)
    constant_patterns: list[str] = field(default_factory=list)
    type_patterns: list[str] = field(default_factory=list)
```

### Field reference

| Field | Purpose |
|---|---|
| `ts_language` | Name passed to `tree_sitter_language_pack.get_parser()` |
| `symbol_node_types` | Maps AST node types to symbol kinds: `"function"`, `"class"`, `"method"`, `"type"`, `"constant"` |
| `name_fields` | Which child field holds the symbol name for each node type |
| `param_fields` | Which child field holds the parameters (for signature extraction) |
| `return_type_fields` | Which child field holds the return type annotation |
| `docstring_strategy` | `"preceding_comment"` looks above the node; `"next_sibling_string"` looks below (Python-style) |
| `decorator_node_type` | AST node type for decorators/annotations (e.g., `"decorator"` for Python) |
| `container_node_types` | Node types that contain nested symbols (e.g., class bodies) |
| `constant_patterns` | AST patterns for detecting top-level constants |
| `type_patterns` | AST patterns for detecting type definitions |

## Adding a language: step by step

### 1. Verify tree-sitter support

```python
from tree_sitter_language_pack import get_parser
parser = get_parser("your_language")  # must not raise
```

If this fails, the language is not in `tree-sitter-language-pack` and cannot be
added without first extending that package.

### 2. Explore the AST

Print the AST to discover node types:

```python
from tree_sitter_language_pack import get_parser

parser = get_parser("your_language")
tree = parser.parse(b"""
def hello():
    pass
""")
print(tree.root_node.sexp())
```

Look for node types like `function_definition`, `class_definition`,
`method_declaration`, etc. Note the child field names -- these go into
`name_fields` and `param_fields`.

### 3. Add the spec to LANGUAGE_REGISTRY

```python
# src/sylvan/indexing/source_code/language_specs.py

LANGUAGE_REGISTRY: dict[str, LanguageSpec] = {
    # ... existing languages ...

    "your_language": LanguageSpec(
        ts_language="your_language",
        symbol_node_types={
            "function_definition": "function",
            "class_definition": "class",
        },
        name_fields={
            "function_definition": "name",
            "class_definition": "name",
        },
        param_fields={
            "function_definition": "parameters",
        },
        docstring_strategy="preceding_comment",
        container_node_types=["class_definition"],
    ),
}
```

### 4. Add file extensions to LANGUAGE_EXTENSIONS

```python
# Same file, near the top

LANGUAGE_EXTENSIONS: dict[str, str] = {
    # ... existing mappings ...
    ".yl": "your_language",
    ".ylx": "your_language",
}
```

### 5. Verify

```bash
uv run python -c "
from sylvan.indexing.source_code.language_specs import detect_language, get_spec
assert detect_language('test.yl') == 'your_language'
spec = get_spec('your_language')
assert spec is not None
assert spec.ts_language == 'your_language'
print('OK')
"
```

## Example: a simple language (Lua)

```python
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
```

Lua only has function declarations at the top level -- no classes, no types. The
spec is minimal.

## Example: a complex language (TypeScript)

```python
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
```

TypeScript has functions, classes, methods, interfaces, type aliases, and enums.
Methods live inside class containers, so `container_node_types` includes
`"class_declaration"`.

## Custom extraction languages

Some languages (ASM, Vue, CSS, TOML, YAML) use custom extraction logic instead
of the standard tree-sitter walker. These are listed in
`CUSTOM_EXTRACTION_LANGUAGES`:

```python
CUSTOM_EXTRACTION_LANGUAGES: frozenset[str] = frozenset({
    "asm", "vue", "css", "toml", "yaml",
})
```

If your language needs special handling beyond what `LanguageSpec` provides, add
it to this set and implement a custom extractor.

## Testing

```bash
uv run pytest tests/ -v -k "language"
```

Index a sample file and verify symbol extraction:

```bash
uv run sylvan index /path/to/sample/project -n test-lang
uv run sylvan shell
>>> from sylvan.database.orm.models import Symbol
>>> symbols = await Symbol.where(language="your_language").get()
>>> for s in symbols: print(s.name, s.kind)
```
