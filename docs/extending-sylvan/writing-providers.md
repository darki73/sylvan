# Writing Providers

Two provider types power the indexing pipeline: **`SummaryProvider`** generates
one-line summaries for symbols and doc sections, and **`EmbeddingProvider`**
generates vector embeddings for semantic search. Both live in
`src/sylvan/providers/` and follow the same pattern: subclass, override,
register, import.

## Summary providers

### The base class

```python
# src/sylvan/providers/base.py

class SummaryProvider(ABC):
    """Subclasses implement available() and _generate_summary().
    The base provides summarize_symbol(), summarize_section(), summarize(), and name.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'ollama', 'claude-code')."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if the provider can generate summaries right now."""

    @abstractmethod
    def _generate_summary(self, prompt: str) -> str:
        """Send prompt, return summary text.
        No error handling needed -- the base class catches exceptions
        and falls back gracefully.
        """
```

The base class handles timing, logging, and fallback. If `_generate_summary`
raises or returns garbage, `summarize_symbol` falls back to the first docstring
line, then to the signature. You only implement the three abstract members.

### Minimal example

```python
# src/sylvan/providers/external/my_llm.py

from override import override

from sylvan.providers.base import SummaryProvider
from sylvan.providers.registry import register_summary_provider


@register_summary_provider("my-llm")
class MyLlmSummaryProvider(SummaryProvider):
    """Summarize code using my custom LLM endpoint."""

    name = "my-llm"

    @override
    def available(self) -> bool:
        """Check if the LLM service is reachable."""
        try:
            import httpx
            r = httpx.get("http://localhost:5000/health", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    @override
    def _generate_summary(self, prompt: str) -> str:
        """Call the LLM and return a one-line summary."""
        import httpx
        r = httpx.post(
            "http://localhost:5000/summarize",
            json={"prompt": prompt},
            timeout=10,
        )
        return r.json()["summary"]
```

### The heuristic provider (built-in reference)

The default provider uses no network and no models:

```python
@register_summary_provider("heuristic")
class HeuristicSummaryProvider(SummaryProvider):
    name = "heuristic"

    @override
    def available(self) -> bool:
        return True

    @override
    def _generate_summary(self, prompt: str) -> str:
        lines = prompt.split("\n")
        docstring = ""
        signature = ""
        for line in lines:
            if line.startswith("Docstring: "):
                docstring = line[11:].strip()
            elif line.startswith("Signature: "):
                signature = line[11:].strip()
        if docstring:
            return _first_sentence(docstring)
        if signature:
            return signature[:120]
        return ""
```

## Embedding providers

### The base class

```python
# src/sylvan/providers/base.py

class EmbeddingProvider(ABC):
    """Subclasses implement available() and _generate_embeddings().
    The base provides embed(), embed_one(), name, and dimensions.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding vector dimensionality."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if the provider can generate embeddings right now."""

    @abstractmethod
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors. Errors are caught by the base class."""
```

On failure, `embed()` returns zero vectors instead of crashing. You only
implement the four abstract members.

### Minimal example

```python
# src/sylvan/providers/external/my_embedder.py

from override import override

from sylvan.providers.base import EmbeddingProvider
from sylvan.providers.registry import register_embedding_provider


@register_embedding_provider("my-embedder")
class MyEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings via a custom service."""

    @property
    @override
    def name(self) -> str:
        return "my-embedder"

    @property
    @override
    def dimensions(self) -> int:
        return 768

    @override
    def available(self) -> bool:
        try:
            import httpx
            r = httpx.get("http://localhost:6000/health", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    @override
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        import httpx
        r = httpx.post(
            "http://localhost:6000/embed",
            json={"texts": texts},
            timeout=30,
        )
        return r.json()["embeddings"]
```

## Registration

The `@register_summary_provider` and `@register_embedding_provider` decorators
store your class in an in-memory registry:

```python
# src/sylvan/providers/registry.py

_SUMMARY_PROVIDERS: dict[str, type] = {}

def register_summary_provider(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _SUMMARY_PROVIDERS[name] = cls
        return cls
    return decorator
```

The name you pass to the decorator is the name users put in their config file.

## Triggering registration via import

Your module must be imported at startup so the decorator runs. Add it to the
`_PROVIDER_MODULES` list in `src/sylvan/providers/__init__.py`:

```python
# src/sylvan/providers/__init__.py

_PROVIDER_MODULES = [
    "sylvan.providers.builtin.heuristic",
    "sylvan.providers.builtin.sentence_transformers",
    "sylvan.providers.external.ollama.provider",
    "sylvan.providers.external.claude_code",
    "sylvan.providers.external.codex",
    "sylvan.providers.external.my_llm",        # <-- add yours
    "sylvan.providers.external.my_embedder",   # <-- add yours
]
```

## Configuration

Users select providers in `~/.sylvan/config.yaml`:

```yaml
summary:
  provider: "my-llm"

embedding:
  provider: "my-embedder"
  dimensions: 768
```

The `dimensions` field must match your `EmbeddingProvider.dimensions` property.
If omitted, it defaults to 384.

## Testing

Providers are plain classes -- no async, no database. Test them directly:

```python
def test_my_provider_available():
    provider = MyLlmSummaryProvider()
    assert isinstance(provider.available(), bool)

def test_my_provider_summarizes():
    provider = MyLlmSummaryProvider()
    result = provider.summarize_symbol(
        signature="def parse(data: bytes) -> dict",
        docstring="Parse binary data into a dictionary.",
        source="def parse(data: bytes) -> dict:\n    ...",
    )
    assert len(result) > 0
    assert len(result) <= 120
```
