"""Symbol-level reference graph -- build and query who-calls-what."""

import json
import re

from sylvan.database.orm import FileImport, FileRecord, Reference, Symbol
from sylvan.database.orm.runtime.connection_manager import get_backend


async def build_reference_graph(repo_id: int) -> int:
    """Build symbol-level reference edges from file imports + text matching.

    For each file import, checks which symbols in the target file are
    actually referenced by name in the source file's content.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        Number of reference edges created.
    """
    from sylvan.database.orm.models.blob import Blob

    backend = get_backend()

    imports = await (
        FileImport.query()
        .select("file_imports.*", "f_src.path as src_path", "f_src.content_hash as src_hash")
        .join("files f_src", "f_src.id = file_imports.file_id")
        .where("f_src.repo_id", repo_id)
        .get()
    )

    symbols_rows = await (
        Symbol.query()
        .select("symbols.symbol_id", "symbols.name", "symbols.file_id")
        .join("files f", "f.id = symbols.file_id")
        .where("f.repo_id", repo_id)
        .get()
    )
    symbols_by_file: dict[int, list[dict]] = {}
    for sym in symbols_rows:
        fid = sym.file_id
        symbols_by_file.setdefault(fid, []).append({
            "symbol_id": sym.symbol_id,
            "name": sym.name,
            "file_id": sym.file_id,
        })

    file_records = await FileRecord.where(repo_id=repo_id).get()
    file_paths = {}
    for fr in file_records:
        file_paths[fr.path] = fr.id
        stem = fr.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        file_paths.setdefault(stem, fr.id)

    edges = 0

    for imp in imports:
        src_file_id = imp.file_id
        names_raw = getattr(imp, "names", None)
        if isinstance(names_raw, str):
            names = json.loads(names_raw) if names_raw else []
        elif isinstance(names_raw, list):
            names = names_raw
        else:
            names = []
        resolved_fid = imp.resolved_file_id
        src_path = getattr(imp, "src_path", "")
        src_hash = getattr(imp, "src_hash", "")

        if resolved_fid is None:
            spec = imp.specifier
            for candidate in [spec, spec.lstrip("./"), spec.replace(".", "/")]:
                if candidate in file_paths:
                    resolved_fid = file_paths[candidate]
                    break

        if resolved_fid is None:
            continue

        target_symbols = symbols_by_file.get(resolved_fid, [])
        if not target_symbols:
            continue

        src_content = await Blob.get(src_hash)
        if src_content is None:
            continue
        src_text = src_content.decode("utf-8", errors="replace")

        for tsym in target_symbols:
            sym_name = tsym["name"]
            if names and sym_name not in names:
                continue
            if not names and not _name_appears_in(sym_name, src_text):
                continue

            src_symbols = symbols_by_file.get(src_file_id, [])
            if src_symbols:
                for ssym in src_symbols:
                    await Reference.insert_or_ignore(
                        source_symbol_id=ssym["symbol_id"],
                        target_symbol_id=tsym["symbol_id"],
                        target_specifier=imp.specifier,
                        target_names=names or None,
                    )
                    edges += 1
                    break
            else:
                await Reference.insert_or_ignore(
                    source_symbol_id=f"__file__:{src_path}",
                    target_symbol_id=tsym["symbol_id"],
                    target_specifier=imp.specifier,
                    target_names=names or None,
                )
                edges += 1

    await backend.commit()
    return edges


async def get_references_to(symbol_id: str) -> list[dict]:
    """Get all symbols that reference a given symbol (callers/importers).

    Args:
        symbol_id: Unique identifier of the target symbol.

    Returns:
        List of dicts describing referencing symbols, each containing
        source_symbol_id, target_specifier, name, qualified_name,
        kind, language, signature, and file_path.
    """
    refs = await (
        Reference.query()
        .select('"references".source_symbol_id', '"references".target_specifier',
                's.name', 's.qualified_name', 's.kind', 's.language',
                's.signature', 'f.path as file_path')
        .left_join("symbols s", 's.symbol_id = "references".source_symbol_id')
        .left_join("files f", "f.id = s.file_id")
        .where('"references".target_symbol_id', symbol_id)
        .order_by("f.path")
        .get()
    )
    return [
        {
            "source_symbol_id": r.source_symbol_id,
            "target_specifier": r.target_specifier,
            "name": getattr(r, "name", None),
            "qualified_name": getattr(r, "qualified_name", None),
            "kind": getattr(r, "kind", None),
            "language": getattr(r, "language", None),
            "signature": getattr(r, "signature", None),
            "file_path": getattr(r, "file_path", None),
        }
        for r in refs
    ]


async def get_references_from(symbol_id: str) -> list[dict]:
    """Get all symbols that a given symbol references (callees/dependencies).

    Args:
        symbol_id: Unique identifier of the source symbol.

    Returns:
        List of dicts describing referenced symbols, each containing
        target_symbol_id, target_specifier, name, qualified_name,
        kind, language, signature, and file_path.
    """
    refs = await (
        Reference.query()
        .select('"references".target_symbol_id', '"references".target_specifier',
                's.name', 's.qualified_name', 's.kind', 's.language',
                's.signature', 'f.path as file_path')
        .left_join("symbols s", 's.symbol_id = "references".target_symbol_id')
        .left_join("files f", "f.id = s.file_id")
        .where('"references".source_symbol_id', symbol_id)
        .order_by("f.path")
        .get()
    )
    return [
        {
            "target_symbol_id": r.target_symbol_id,
            "target_specifier": r.target_specifier,
            "name": getattr(r, "name", None),
            "qualified_name": getattr(r, "qualified_name", None),
            "kind": getattr(r, "kind", None),
            "language": getattr(r, "language", None),
            "signature": getattr(r, "signature", None),
            "file_path": getattr(r, "file_path", None),
        }
        for r in refs
    ]


def _name_appears_in(name: str, text: str) -> bool:
    """Check if a symbol name appears as a word in text.

    Args:
        name: Symbol name to search for.
        text: Source text to search within.

    Returns:
        True if the name appears as a whole word in the text.
    """
    if len(name) < 2:
        return False
    pattern = r'\b' + re.escape(name) + r'\b'
    return bool(re.search(pattern, text))
