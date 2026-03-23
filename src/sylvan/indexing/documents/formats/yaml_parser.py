"""YAML documentation parser -- converts to JSON and delegates to the JSON parser."""

from sylvan.database.validation import Section
from sylvan.indexing.documents.formats.json_parser import parse_json_doc
from sylvan.indexing.documents.formats.text import parse_text
from sylvan.indexing.documents.registry import register_parser


@register_parser("yaml", [".yaml", ".yml"])
def parse_yaml_doc(content: str, doc_path: str, repo: str) -> list[Section]:
    """Load YAML content and route through the JSON doc parser.

    Args:
        content: Raw YAML content string.
        doc_path: Path to the YAML file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return parse_text(content, doc_path, repo)

    try:
        data = yaml.safe_load(content)
    except Exception:
        return parse_text(content, doc_path, repo)

    if not isinstance(data, dict):
        return parse_text(content, doc_path, repo)

    import json

    json_content = json.dumps(data, indent=2, ensure_ascii=False)
    return parse_json_doc(json_content, doc_path, repo)
