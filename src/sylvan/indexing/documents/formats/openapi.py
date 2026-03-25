"""OpenAPI / Swagger specification parser."""

import json
import re
from typing import Any

from sylvan.database.validation import Section
from sylvan.indexing.documents.registry import register_parser
from sylvan.indexing.documents.section_builder import (
    compute_section_hash,
    extract_references,
    extract_tags,
    make_hierarchical_slug,
    make_section_id,
    wire_hierarchy,
)


def sniff_openapi(content: str, ext: str) -> bool:
    """Return True if *content* looks like an OpenAPI or Swagger specification.

    Args:
        content: Raw file content.
        ext: File extension (e.g., ".yaml", ".json").

    Returns:
        True if the content appears to be an OpenAPI/Swagger spec.
    """
    if ext in (".yaml", ".yml"):
        return bool(re.search(r"^(openapi|swagger)\s*:", content, re.MULTILINE))
    if ext in (".json", ".jsonc"):
        try:
            data = json.loads(content)
            return isinstance(data, dict) and ("openapi" in data or "swagger" in data)
        except (json.JSONDecodeError, ValueError):
            return False
    return False


def _load_spec(content: str, ext: str) -> dict[str, Any]:
    """Load the spec from YAML or JSON text.

    Args:
        content: Raw spec content.
        ext: File extension for format selection.

    Returns:
        Parsed specification dictionary, or empty dict on failure.
    """
    if ext in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            return {}
        return yaml.safe_load(content) or {}
    # JSON
    return json.loads(content)


def _render_parameters(params: list[dict[str, Any]]) -> str:
    """Render a list of OpenAPI parameter objects as text.

    Args:
        params: List of parameter definition dictionaries.

    Returns:
        Markdown-formatted parameter documentation.
    """
    if not params:
        return ""
    lines = ["**Parameters:**", ""]
    for p in params:
        name = p.get("name", "?")
        location = p.get("in", "?")
        required = "required" if p.get("required") else "optional"
        desc = p.get("description", "")
        schema = p.get("schema", {})
        ptype = schema.get("type", "") if isinstance(schema, dict) else ""
        lines.append(f"- `{name}` ({location}, {ptype}, {required}): {desc}")
    lines.append("")
    return "\n".join(lines)


def _render_request_body(body: dict[str, Any] | None) -> str:
    """Render an OpenAPI request body object as text.

    Args:
        body: Request body definition dictionary, or None.

    Returns:
        Markdown-formatted request body documentation.
    """
    if not body:
        return ""
    desc = body.get("description", "")
    content_map = body.get("content", {})
    lines = ["**Request body:**", ""]
    if desc:
        lines.append(desc)
        lines.append("")
    for media_type, media_obj in content_map.items():
        lines.append(f"- Content-Type: `{media_type}`")
        schema = media_obj.get("schema", {})
        if isinstance(schema, dict):
            lines.append(f"  Schema type: {schema.get('type', 'object')}")
    lines.append("")
    return "\n".join(lines)


def _render_responses(responses: dict[str, Any]) -> str:
    """Render OpenAPI response definitions as text.

    Args:
        responses: Mapping of status codes to response definitions.

    Returns:
        Markdown-formatted response documentation.
    """
    if not responses:
        return ""
    lines = ["**Responses:**", ""]
    for code, resp in responses.items():
        desc = resp.get("description", "") if isinstance(resp, dict) else str(resp)
        lines.append(f"- `{code}`: {desc}")
    lines.append("")
    return "\n".join(lines)


@register_parser("openapi", [".yaml", ".yml", ".json", ".jsonc"], sniffer=sniff_openapi)
def parse_openapi(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse an OpenAPI/Swagger spec into sections grouped by tag.

    Args:
        content: Raw specification content (JSON or YAML).
        doc_path: Path to the specification file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    ext = ""
    for e in (".yaml", ".yml", ".json", ".jsonc"):
        if doc_path.endswith(e):
            ext = e
            break

    spec = _load_spec(content, ext)
    if not spec:
        return []

    content.encode("utf-8")
    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()
    byte_cursor = 0

    def _sec(title: str, level: int, body: str) -> Section:
        """Build a Section and advance the byte cursor.

        Args:
            title: Section heading text.
            level: Heading depth level.
            body: Section body text.

        Returns:
            A populated Section object.
        """
        nonlocal byte_cursor
        body_bytes = body.encode("utf-8")
        start = byte_cursor
        byte_cursor += len(body_bytes)
        slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
        return Section(
            section_id=make_section_id(repo, doc_path, slug, level),
            title=title,
            level=level,
            byte_start=start,
            byte_end=byte_cursor,
            content_hash=compute_section_hash(body),
            tags=extract_tags(body),
            references=extract_references(body),
        )

    info = spec.get("info", {})
    api_title = info.get("title", "API")
    api_version = info.get("version", "")
    api_desc = info.get("description", "")
    root_body = f"{api_title} {api_version}\n{api_desc}\n"
    sections.append(_sec(api_title, 1, root_body))

    paths = spec.get("paths", {})
    tag_ops: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "options", "head", "trace"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            op_tags = op.get("tags", ["Untagged"])
            for tag_name in op_tags:
                tag_ops.setdefault(tag_name, []).append((method.upper(), path, op))

    for tag_name, ops in tag_ops.items():
        tag_body = f"Tag: {tag_name}\n"
        sections.append(_sec(tag_name, 2, tag_body))

        for method, path, op in ops:
            op_summary = op.get("summary", op.get("operationId", ""))
            op_title = f"{method} {path}"
            parts = [f"{op_title}\n"]
            if op_summary:
                parts.append(f"{op_summary}\n")
            desc = op.get("description", "")
            if desc:
                parts.append(f"{desc}\n")
            parts.append(_render_parameters(op.get("parameters", [])))
            parts.append(_render_request_body(op.get("requestBody")))
            parts.append(_render_responses(op.get("responses", {})))
            body = "\n".join(parts)
            sections.append(_sec(op_title, 3, body))

    wire_hierarchy(sections)
    return sections
