# Contributing to Sylvan

## Setup

```bash
git clone https://github.com/darki73/sylvan.git
cd sylvan
uv sync
uv run pre-commit install
```

## Running tests

```bash
uv run pytest tests/ -v              # all tests
uv run pytest tests/test_orm/ -v     # ORM tests only
uv run pytest tests/ --cov=sylvan    # with coverage
```

Tests use real SQLite backends with migrations, no mocks. All existing tests should pass locally before submitting a PR.

## Linting

Pre-commit hooks run ruff automatically on commit. To run manually:

```bash
uv run ruff check src/sylvan/ tests/        # lint
uv run ruff check --fix src/sylvan/ tests/  # lint with auto-fix
uv run ruff format src/sylvan/ tests/       # format
```

## Project structure

```
src/sylvan/
    server/         MCP server (tool registration, dispatch, transports)
    database/       Persistence (backends, builder, migrations, ORM)
    indexing/       Code + document indexing (pipeline, discovery, tree-sitter)
    analysis/       Code intelligence (blast radius, hierarchy, quality)
    search/         Embeddings (sqlite-vec storage + query)
    tools/          MCP tool implementations (57 tools)
    extensions/     User extension system
    cluster/        Multi-instance (discovery, heartbeat, proxy)
    dashboard/      Web dashboard (Starlette + HTMX)
    providers/      AI providers (summary, embeddings)
    libraries/      Third-party library indexing
    session/        Session tracking + usage stats
```

## Adding a tool

The quickest way is through the extension system - drop a Python file in `~/.sylvan/extensions/tools/`. See [Building Tools](https://darki73.github.io/sylvan/extending-sylvan/building-tools/) for details.

For core tools, the process is:

1. Write the handler in `src/sylvan/tools/`
2. Define the schema in `src/sylvan/tools/definitions/`
3. Register in `src/sylvan/server/__init__.py` (_get_handlers + _TOOL_CATEGORIES)
4. Add tests in `tests/test_tools/`
5. Update CHANGELOG.md

## Adding a language

Create a `LanguageSpec` in `src/sylvan/indexing/source_code/language_specs.py` or use the extension system at `~/.sylvan/extensions/languages/`. See [Adding Languages](https://darki73.github.io/sylvan/extending-sylvan/adding-languages/).

## Commit messages

Use prefixes: `feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`.

Keep them short and to the point. The first line should be under 72 characters.

## Pull requests

- One logical change per PR
- Tests must pass on CI (Ubuntu + Windows, Python 3.12/3.13/3.14)
- Update CHANGELOG.md for user-facing changes
- Update docs if adding tools, config options, or changing behavior
