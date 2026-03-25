# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in sylvan, please report it responsibly.

**Do not open a public issue.** Instead, use [GitHub's private vulnerability reporting](https://github.com/darki73/sylvan/security/advisories/new) to submit your report. This keeps the details private until a fix is available.

Critical issues will be patched and released as soon as possible.

## Scope

Sylvan runs as a local MCP server. Security concerns include:

- **Path traversal** during indexing (mitigated by path validation and symlink rejection)
- **Secret detection** in indexed files (mitigated by pattern-based filtering)
- **Extension loading** from `~/.sylvan/extensions/` (user-controlled, validated at startup)
- **SQL injection** through tool parameters (mitigated by parameterized queries throughout)
- **Cluster API** on localhost (HTTP endpoints for leader/follower communication)

## Supported versions

Only the latest release receives security patches.
