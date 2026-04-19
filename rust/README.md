# sylvan rust workspace

Rust implementation of sylvan, compiled into the `sylvan._rust` Python
extension via maturin.

## Crates

| Crate | Owns |
|-------|------|
| `sylvan-core` | Shared types, port traits, errors |
| `sylvan-indexing` | Discovery, parsing, extraction, pipeline |
| `sylvan-security` | Filter rules, secret detection, path validation |
| `sylvan-git` | Git operations |
| `sylvan-database` | Persistence adapters |
| `sylvan-search` | Vector storage and query |
| `sylvan-providers` | Embedding and summarization providers |
| `sylvan-analysis` | Blast radius, hierarchy, complexity, quality |
| `sylvan-tools` | MCP tool implementations |
| `sylvan-server` | MCP transports and dispatch |
| `sylvan-dashboard` | Dashboard backend |
| `sylvan-cli` | Native CLI |
| `sylvan-py` | PyO3 bindings (cdylib imported as `sylvan._rust`) |

All crates are placeholders until their stage lands.

## Build

```bash
cargo build --workspace
cargo test --workspace --exclude sylvan-py
cargo clippy --all-targets --workspace -- -D warnings
cargo fmt --all -- --check
cargo doc --no-deps --workspace -- -D warnings
```

`cargo test -p sylvan-py` does not work: the `extension-module` PyO3 feature
leaves libpython unresolved at link time. Exercise the binding layer through
Python (`uv run pytest tests/`).

## Build through Python

```bash
uv sync
uv run maturin develop
uv run python -c "from sylvan._rust import version; print(version())"
```
