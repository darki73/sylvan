"""Business logic layer.

Services contain orchestration logic shared by MCP tools, CLI commands,
and dashboard WebSocket handlers. They work with user-facing names
(not internal IDs) and return Result objects wrapping ORM models.
"""
