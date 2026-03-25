## What changed

<!-- Brief description of the change. Link to related issue if applicable. -->

## Why

<!-- What problem this solves or what feature it adds. -->

## How to test

<!-- Steps for the reviewer to verify this works. -->

## Checklist

- [ ] Tests pass locally (`uv run pytest tests/ -v`)
- [ ] Lint clean (`uv run ruff check src/sylvan/`)
- [ ] Formatted (`uv run ruff format src/sylvan/`)
- [ ] CHANGELOG.md updated (if user-facing change)
- [ ] Docs updated (if new tool, config option, or behavior change)
- [ ] No secrets, credentials, or personal paths in the diff
