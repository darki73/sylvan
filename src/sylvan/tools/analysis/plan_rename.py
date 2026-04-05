"""Tool: plan_rename - find all edit locations for renaming a string across a repo."""

from sylvan.tools.base import Tool, ToolParams
from sylvan.tools.base.params import HasRepo, schema_field


class PlanRename(Tool):
    name = "plan_rename"
    category = "analysis"
    description = (
        "Finds all locations where a string appears in a repo and classifies "
        "each by context: string literal, import path, class name, code identifier, "
        "documentation, or comment. Returns structured edit entries for rename-safe "
        "occurrences and skip entries with reasons for the rest. "
        "Accepts a single rename or a batch mapping."
    )

    class Params(HasRepo, ToolParams):
        old_name: str = schema_field(
            description="The string to find and rename",
        )
        new_name: str = schema_field(
            description="The replacement string",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.search import SearchService

        svc = SearchService()
        matches = await svc.text(
            query=p.old_name,
            repo=p.repo,
            max_results=500,
            context_lines=0,
        )

        edits = []
        skipped = []

        for match in matches.get("matches", []):
            line_text = match.get("match", "")
            file_path = match.get("file_path", "")
            line_num = match.get("line", 0)

            classification = _classify_occurrence(
                line_text,
                file_path,
                p.old_name,
            )

            entry = {
                "file": file_path,
                "line": line_num,
                "text": line_text.strip(),
                "context": classification,
            }

            if classification in ("string_literal", "documentation", "comment"):
                entry["old_text"] = p.old_name
                entry["new_text"] = p.new_name
                edits.append(entry)
            else:
                entry["reason"] = _skip_reason(classification)
                skipped.append(entry)

        from sylvan.tools.base.meta import get_meta

        meta = get_meta()
        meta.repo(p.repo)
        meta.extra("edits_count", len(edits))
        meta.extra("skipped_count", len(skipped))
        meta.extra("total_occurrences", len(edits) + len(skipped))
        meta.extra("old_name", p.old_name)
        meta.extra("new_name", p.new_name)

        return {
            "edits": edits,
            "skipped": skipped,
        }


class BatchPlanRename(Tool):
    name = "batch_plan_rename"
    category = "analysis"
    description = (
        "Plan renames for multiple strings in one call. "
        "Takes a mapping of old_name -> new_name pairs and returns "
        "classified edit locations for each. More efficient than "
        "calling plan_rename repeatedly."
    )

    class Params(HasRepo, ToolParams):
        renames: dict = schema_field(
            description=('Mapping of old names to new names, e.g. {"get_symbol": "read_symbol", "get_toc": "doc_toc"}'),
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.search import SearchService

        svc = SearchService()
        results = {}
        total_edits = 0
        total_skipped = 0

        for old_name, new_name in p.renames.items():
            if old_name == new_name:
                continue

            matches = await svc.text(
                query=old_name,
                repo=p.repo,
                max_results=500,
                context_lines=0,
            )

            edits = []
            skipped = []

            for match in matches.get("matches", []):
                line_text = match.get("match", "")
                file_path = match.get("file_path", "")
                line_num = match.get("line", 0)

                classification = _classify_occurrence(
                    line_text,
                    file_path,
                    old_name,
                )

                entry = {
                    "file": file_path,
                    "line": line_num,
                    "text": line_text.strip(),
                    "context": classification,
                }

                if classification in ("string_literal", "documentation", "comment"):
                    entry["old_text"] = old_name
                    entry["new_text"] = new_name
                    edits.append(entry)
                else:
                    entry["reason"] = _skip_reason(classification)
                    skipped.append(entry)

            results[old_name] = {
                "new_name": new_name,
                "edits": edits,
                "skipped": skipped,
            }
            total_edits += len(edits)
            total_skipped += len(skipped)

        from sylvan.tools.base.meta import get_meta

        meta = get_meta()
        meta.repo(p.repo)
        meta.extra("renames_planned", len(results))
        meta.extra("total_edits", total_edits)
        meta.extra("total_skipped", total_skipped)

        return {"renames": results}


def _classify_occurrence(line_text: str, file_path: str, name: str) -> str:
    """Classify a line containing the target string by context.

    Returns one of:
    - string_literal: name appears inside quotes (rename-safe)
    - documentation: file is markdown, rst, or similar (rename-safe)
    - comment: line is a code comment (rename-safe)
    - import_path: line is a Python import statement (skip)
    - class_name: line defines a class (skip)
    - code_identifier: name is used as a Python identifier (skip)
    """
    stripped = line_text.strip()

    # Documentation files
    if _is_doc_file(file_path):
        return "documentation"

    # Python import statements
    if _is_import_line(stripped):
        return "import_path"

    # Class definitions
    if _is_class_definition(stripped, name):
        return "class_name"

    # Inside string quotes (including backtick-wrapped in string literals)
    if _is_in_string(stripped, name):
        return "string_literal"

    # Docstrings (triple-quoted lines in Python)
    if _is_docstring_line(stripped, file_path):
        return "string_literal"

    # Comments
    if _is_comment(stripped, file_path):
        return "comment"

    # Default: code identifier
    return "code_identifier"


def _is_doc_file(file_path: str) -> bool:
    """Check if the file is a documentation file."""
    lower = file_path.lower()
    return any(lower.endswith(ext) for ext in (".md", ".rst", ".txt", ".adoc"))


def _is_import_line(line: str) -> bool:
    """Check if the line is a Python import statement."""
    return line.startswith("import ") or line.startswith("from ")


def _is_class_definition(line: str, name: str) -> bool:
    """Check if the line defines a class related to the name."""
    if not line.startswith("class "):
        return False
    # Convert snake_case to PascalCase for comparison
    pascal = "".join(word.capitalize() for word in name.split("_"))
    return pascal in line


def _is_in_string(line: str, name: str) -> bool:
    """Check if the name appears inside string quotes or backticks on this line."""
    # Backtick-wrapped (common in markdown inside Python strings)
    if f"`{name}`" in line:
        return True

    # Check for common string patterns
    patterns = [
        f'"{name}"',
        f"'{name}'",
        f'"{name}(',
        f"'{name}(",
        f'"{name},',
        f"'{name},",
        f'"{name} ',
        f'= "{name}"',
        f"= '{name}'",
        f'["{name}"]',
        f"['{name}']",
    ]
    for pat in patterns:
        if pat in line:
            return True

    # Check if name is between any quotes on the line
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif (in_single or in_double) and line[i:].startswith(name):
            # Verify it's a word boundary
            before_ok = i == 0 or not line[i - 1].isalpha()
            after_pos = i + len(name)
            after_ok = after_pos >= len(line) or not line[after_pos].isalpha()
            if before_ok and after_ok:
                return True
        i += 1

    return False


def _is_docstring_line(line: str, file_path: str) -> bool:
    """Check if the line is a docstring boundary or continuation."""
    if not file_path.lower().endswith(".py"):
        return False
    stripped = line.strip()
    # Triple-quote boundaries
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return True
    return stripped.endswith('"""') or stripped.endswith("'''")


def _is_comment(line: str, file_path: str) -> bool:
    """Check if the line is a comment."""
    lower = file_path.lower()
    stripped = line.strip()

    if lower.endswith(".py"):
        return stripped.startswith("#")
    if lower.endswith((".js", ".ts", ".vue", ".go", ".java", ".rs")):
        return stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*")
    if lower.endswith((".yaml", ".yml", ".toml")):
        return stripped.startswith("#")

    return False


def _skip_reason(classification: str) -> str:
    """Human-readable reason for skipping."""
    reasons = {
        "import_path": "Python import path, rename the file instead",
        "class_name": "Class definition, rename the class separately",
        "code_identifier": "Code identifier, not a string reference",
    }
    return reasons.get(classification, f"Classified as {classification}")
