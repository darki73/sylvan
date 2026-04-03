# Adding Languages

Language support is plugin-based. Each language is a Python module that
registers a tree-sitter spec and optionally provides import extraction,
import resolution, and complexity analysis.

**Without modifying source:** Drop a `.py` file in `~/.sylvan/extensions/languages/`
that uses the `@register` decorator. Restart the server. See the user extension
example below.

**Built-in languages:** Create a module in `src/sylvan/indexing/languages/` and
add it to `_load_builtin_languages` in `__init__.py`.

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

## Capability protocols

Languages can optionally implement these protocols to provide richer
functionality beyond tree-sitter symbol extraction:

| Protocol | Purpose | Method |
|---|---|---|
| `ImportExtractor` | Extract import statements from source | `extract_imports(content) -> list[dict]` |
| `ImportResolver` | Resolve import specifiers to file paths | `generate_candidates(specifier, source_path, context) -> list[str]` |
| `ComplexityProvider` | Cyclomatic complexity patterns | `decision_pattern`, `uses_braces`, `strip_receiver(params_str)` |

A language only needs to implement the protocols it supports. A tree-sitter-only
language (like Lua or Haskell) needs none of them.

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
`method_declaration`, etc. Note the child field names - these go into
`name_fields` and `param_fields`.

### 3. Create the language module

For a tree-sitter-only language, add it to `_tree_sitter_only.py`:

```python
# src/sylvan/indexing/languages/_tree_sitter_only.py

_SPECS = {
    # ... existing languages ...
    "your_language": (
        [".yl", ".ylx"],
        LanguageSpec(
            ts_language="your_language",
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
}
```

For a language with import extraction and resolution, create a dedicated module:

```python
# src/sylvan/indexing/languages/your_language.py

import re
from typing import TYPE_CHECKING

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec

if TYPE_CHECKING:
    from sylvan.indexing.languages.protocols import ResolverContext

_IMPORT_RE = re.compile(r"^\s*import\s+(\w+)", re.MULTILINE)
_DECISION = re.compile(r"\b(if|for|while|case)\b")


@register(
    name="your_language",
    extensions=[".yl", ".ylx"],
    spec=LanguageSpec(
        ts_language="your_language",
        symbol_node_types={"function_definition": "function"},
        name_fields={"function_definition": "name"},
        docstring_strategy="preceding_comment",
    ),
)
class YourLanguage:
    def extract_imports(self, content: str) -> list[dict]:
        return [
            {"specifier": m.group(1), "names": []}
            for m in _IMPORT_RE.finditer(content)
        ]

    def generate_candidates(
        self, specifier: str, source_path: str, context: ResolverContext,
    ) -> list[str]:
        return [f"{specifier}.yl", f"src/{specifier}.yl"]

    decision_pattern = _DECISION
    uses_braces = True

    def strip_receiver(self, params_str: str) -> str:
        return params_str
```

### 4. Register the module

Add the import to `_load_builtin_languages` in `src/sylvan/indexing/languages/__init__.py`:

```python
def _load_builtin_languages() -> None:
    from sylvan.indexing.languages import (
        # ... existing imports ...
        your_language,
    )
```

### 5. Language aliases

If multiple language names share the same plugin (like TypeScript and JavaScript
sharing import extraction), use `register_alias`:

```python
from sylvan.indexing.languages import register_alias

register_alias(
    name="your_dialect",
    extensions=[".yld"],
    spec=LanguageSpec(
        ts_language="your_dialect",
        symbol_node_types={...},
        name_fields={...},
    ),
    plugin_cls=YourLanguage,
)
```

The alias gets its own tree-sitter spec but shares the plugin instance's
extraction, resolution, and complexity capabilities.

### 6. Verify

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

## Example: tree-sitter only (Lua)

Lua only has function declarations - no classes, no types. It goes in
`_tree_sitter_only.py` since it doesn't need import extraction or resolution.

```python
"lua": (
    [".lua"],
    LanguageSpec(
        ts_language="lua",
        symbol_node_types={"function_declaration": "function"},
        name_fields={"function_declaration": "name"},
        docstring_strategy="preceding_comment",
    ),
),
```

## Example: full plugin (PHP)

PHP has import extraction (use statements with group syntax), import resolution
(PSR-4 via composer.json), and complexity analysis.

```python
# src/sylvan/indexing/languages/php.py

@register(
    name="php",
    extensions=[".php"],
    spec=LanguageSpec(
        ts_language="php",
        symbol_node_types={
            "function_definition": "function",
            "class_declaration": "class",
            "method_declaration": "method",
            "interface_declaration": "type",
            "trait_declaration": "type",
            "enum_declaration": "type",
        },
        name_fields={...},
        param_fields={...},
        container_node_types=["class_declaration", "interface_declaration", "trait_declaration"],
    ),
)
class PhpLanguage:
    def extract_imports(self, content): ...    # use statements + group use
    def generate_candidates(self, ...): ...    # PSR-4 resolution from composer.json
    decision_pattern = _PHP_DECISION
    uses_braces = True
    def strip_receiver(self, params_str): ...
```

The resolver reads PSR-4 mappings from the `ResolverContext` which the orchestrator
populates from `composer.json` before resolution runs.

## User extensions (no source modification)

Drop a `.py` file in `~/.sylvan/extensions/languages/` and restart the server.
The extension loader imports it automatically, firing any `@register` decorators.

```python
# ~/.sylvan/extensions/languages/zig.py

from sylvan.indexing.languages import register
from sylvan.indexing.source_code.language_specs import LanguageSpec


@register(
    name="zig",
    extensions=[".zig"],
    spec=LanguageSpec(
        ts_language="zig",
        symbol_node_types={
            "FnDecl": "function",
            "TestDecl": "function",
        },
        name_fields={
            "FnDecl": "name",
            "TestDecl": "name",
        },
        docstring_strategy="preceding_comment",
    ),
)
class ZigLanguage:
    pass
```

This registers Zig for tree-sitter extraction. Add `extract_imports` or
`generate_candidates` methods to the class to enable import extraction
and resolution.

## Architecture

```
src/sylvan/indexing/languages/
    __init__.py          # register(), register_alias(), capability lookups
    protocols.py         # ImportExtractor, ImportResolver, ComplexityProvider
    python.py            # Python plugin (full capabilities)
    javascript.py        # JS/TS/TSX/JSX (with tsconfig alias resolution)
    php.py               # PHP (with PSR-4 resolution)
    go.py, rust.py, ...  # Other full plugins
    stylesheets.py       # SCSS/LESS/Stylus (import extraction only)
    swift.py             # Swift (import extraction only)
    _tree_sitter_only.py # 20+ languages with tree-sitter specs only
```

The `@register` decorator stores the spec in the base registry and inspects the
class for protocol conformance. Dispatchers in `import_extraction.py`,
`import_resolver.py`, and `complexity.py` look up the appropriate plugin via
`get_import_extractor()`, `get_import_resolver()`, and
`get_complexity_provider()`.

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
