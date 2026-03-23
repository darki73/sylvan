"""Class hierarchy traversal -- ancestors and descendants."""

import re
from collections import deque

from sylvan.database.orm import Symbol

# Patterns to extract base classes from signatures
_EXTENDS_PATTERNS = [
    re.compile(r'class\s+\w+\s*\(([^)]+)\)'),      # Python
    re.compile(r'class\s+\w+\s+extends\s+(\w+)'),   # JS/TS/Java
    re.compile(r'class\s+\w+\s*:\s*(?:public|private|protected)?\s*(\w+)'),  # C++/C#
    re.compile(r'implements\s+([\w,\s]+)'),           # Java/TS interfaces
]


async def get_class_hierarchy(
    class_name: str,
    repo_name: str | None = None,
) -> dict:
    """Traverse class hierarchy: find ancestors and descendants.

    Args:
        class_name: Name of the class to start from.
        repo_name: Optional repo filter.

    Returns:
        Dictionary with "target", "ancestors", and "descendants" keys.
        Returns an error dict if the class is not found.
    """
    query = Symbol.classes().where("symbols.name", class_name)
    if repo_name:
        query = query.in_repo(repo_name)
    else:
        query = query.join("files", "files.id = symbols.file_id")
    query = query.select("symbols.*", "files.path as file_path")
    target = await query.first()

    if target is None:
        return {"error": "class_not_found", "class_name": class_name}

    target_dict = {
        "symbol_id": target.symbol_id,
        "name": target.name,
        "kind": target.kind,
        "signature": target.signature,
        "file_path": getattr(target, "file_path", ""),
    }

    bases = _extract_bases(target.signature or "")

    ancestors = []
    visited = {class_name}
    queue = deque(bases)

    while queue:
        base_name = queue.popleft()
        if base_name in visited:
            continue
        visited.add(base_name)

        base_sym = await (
            Symbol.where(name=base_name)
            .where_in("kind", ["class", "type"])
            .join("files f", "f.id = symbols.file_id")
            .select("symbols.symbol_id", "symbols.name", "symbols.kind",
                    "symbols.signature", "f.path as file_path", "symbols.line_start")
            .limit(1)
            .first()
        )

        if base_sym:
            base_dict = {
                "symbol_id": base_sym.symbol_id,
                "name": base_sym.name,
                "kind": base_sym.kind,
                "signature": base_sym.signature,
                "file_path": getattr(base_sym, "file_path", ""),
                "line_start": base_sym.line_start,
            }
            ancestors.append(base_dict)
            parent_bases = _extract_bases(base_sym.signature or "")
            queue.extend(parent_bases)
        else:
            ancestors.append({
                "name": base_name,
                "kind": "class",
                "file_path": "(external)",
                "line_start": 0,
            })

    all_classes = await (
        Symbol.where_in("kind", ["class", "type"])
        .join("files f", "f.id = symbols.file_id")
        .select("symbols.symbol_id", "symbols.name", "symbols.kind",
                "symbols.signature", "f.path as file_path", "symbols.line_start")
        .get()
    )

    children_of: dict[str, list[dict]] = {}
    for cls in all_classes:
        cls_dict = {
            "symbol_id": cls.symbol_id,
            "name": cls.name,
            "kind": cls.kind,
            "signature": cls.signature,
            "file_path": getattr(cls, "file_path", ""),
            "line_start": cls.line_start,
        }
        cls_bases = _extract_bases(cls.signature or "")
        for base in cls_bases:
            children_of.setdefault(base, []).append(cls_dict)

    descendants = []
    desc_visited = {class_name}
    desc_queue = deque([class_name])
    while desc_queue:
        current = desc_queue.popleft()
        for child in children_of.get(current, []):
            if child["name"] not in desc_visited:
                desc_visited.add(child["name"])
                descendants.append(child)
                desc_queue.append(child["name"])

    return {
        "target": {
            "symbol_id": target_dict["symbol_id"],
            "name": target_dict["name"],
            "kind": target_dict["kind"],
            "file": target_dict["file_path"],
        },
        "ancestors": ancestors,
        "descendants": descendants,
    }


def _extract_bases(signature: str) -> list[str]:
    """Extract base class names from a class signature.

    Args:
        signature: Class signature string.

    Returns:
        List of base class name strings.
    """
    if not signature:
        return []

    bases = []
    for pattern in _EXTENDS_PATTERNS:
        m = pattern.search(signature)
        if m:
            raw = m.group(1)
            for raw_name in raw.split(","):
                cleaned = raw_name.strip()
                cleaned = re.sub(r'<[^>]*>', '', cleaned).strip()
                cleaned = re.split(r'\s+', cleaned)[-1]
                if cleaned and cleaned[0].isupper() and cleaned not in ("object", "Object"):
                    bases.append(cleaned)
    return bases
