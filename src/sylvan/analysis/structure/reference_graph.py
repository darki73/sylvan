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
        symbols_by_file.setdefault(fid, []).append(
            {
                "symbol_id": sym.symbol_id,
                "name": sym.name,
                "file_id": sym.file_id,
            }
        )

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
        .select(
            '"references".source_symbol_id',
            '"references".target_specifier',
            '"references".line',
            "s.name",
            "s.qualified_name",
            "s.kind",
            "s.language",
            "s.signature",
            "f.path as file_path",
        )
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
            "line": getattr(r, "line", None),
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
        target_symbol_id, target_specifier, line, name, qualified_name,
        kind, language, signature, and file_path.
    """
    refs = await (
        Reference.query()
        .select(
            '"references".target_symbol_id',
            '"references".target_specifier',
            '"references".line',
            "s.name",
            "s.qualified_name",
            "s.kind",
            "s.language",
            "s.signature",
            "f.path as file_path",
        )
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
            "line": getattr(r, "line", None),
            "name": getattr(r, "name", None),
            "qualified_name": getattr(r, "qualified_name", None),
            "kind": getattr(r, "kind", None),
            "language": getattr(r, "language", None),
            "signature": getattr(r, "signature", None),
            "file_path": getattr(r, "file_path", None),
        }
        for r in refs
    ]


async def resolve_call_sites(repo_id: int) -> int:
    """Resolve unresolved call sites to known symbol IDs.

    Two-pass resolution:
    1. Name-based (fast) - matches specifier names against the symbol index.
       Resolves simple calls, self.method, and class references instantly.
    2. Jedi (precise) - semantic analysis for anything name-based couldn't
       resolve. Handles inherited methods, cross-module dotted calls, and
       type inference through chains. Only runs on leftover references.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        Number of references resolved.
    """
    backend = get_backend()

    unresolved = await (
        Reference.query()
        .select(
            '"references".id',
            '"references".source_symbol_id',
            '"references".target_specifier',
            '"references".line',
            "f.path as file_path",
            "f.content_hash as file_hash",
        )
        .left_join("symbols s", 's.symbol_id = "references".source_symbol_id')
        .left_join("files f", "f.id = s.file_id")
        .where_null('"references".target_symbol_id')
        .where_group(lambda q: q.where("f.repo_id", repo_id).or_where('"references".source_symbol_id', "__module__"))
        .get()
    )

    if not unresolved:
        return 0

    symbols_rows = await (
        Symbol.query()
        .select("symbols.symbol_id", "symbols.name", "symbols.qualified_name", "symbols.file_id")
        .join("files f", "f.id = symbols.file_id")
        .where("f.repo_id", repo_id)
        .get()
    )

    by_name: dict[str, list[str]] = {}
    by_qualified: dict[str, str] = {}
    for sym in symbols_rows:
        by_name.setdefault(sym.name, []).append(sym.symbol_id)
        if sym.qualified_name:
            by_qualified[sym.qualified_name] = sym.symbol_id

    resolved = 0

    needs_jedi = []
    for ref in unresolved:
        spec = ref.target_specifier
        if not spec:
            continue

        if "." in spec and not spec.startswith("self."):
            needs_jedi.append(ref)
            continue

        target_id = _match_specifier(spec, by_name, by_qualified, ref.source_symbol_id)
        if target_id is not None:
            await Reference.where(id=ref.id).update(target_symbol_id=target_id)
            resolved += 1
        else:
            needs_jedi.append(ref)

    if needs_jedi:
        from sylvan.database.orm import Repo

        repo_obj = await Repo.where(id=repo_id).first()
        project_root = repo_obj.source_path if repo_obj else None

        if project_root:
            resolved += await _resolve_with_jedi(needs_jedi, project_root, by_name, by_qualified)

    if resolved:
        await backend.commit()
    return resolved


async def _resolve_with_jedi(
    refs: list,
    project_root: str,
    by_name: dict[str, list[str]],
    by_qualified: dict[str, str],
) -> int:
    """Resolve references using jedi semantic analysis.

    Deduplicates by specifier - each unique dotted name is resolved once
    via jedi, then the result is applied to all matching references.
    This reduces ~12k goto calls to ~1.5k for a typical codebase.

    Args:
        refs: List of unresolved reference objects (after name-based pass).
        project_root: Absolute path to the project root for jedi.
        by_name: Symbol name -> symbol_id lookup.
        by_qualified: Qualified name -> symbol_id lookup.

    Returns:
        Number of references resolved by jedi.
    """
    import asyncio
    from pathlib import Path

    try:
        from sylvan.analysis.structure.jedi_setup import ensure_patched

        ensure_patched()
        import jedi
    except ImportError:
        return 0

    from sylvan.database.orm.models.blob import Blob

    spec_to_refs: dict[str, list[int]] = {}
    spec_sample: dict[str, tuple[str, str, int]] = {}

    for ref in refs:
        spec = ref.target_specifier
        fpath = getattr(ref, "file_path", None)
        fhash = getattr(ref, "file_hash", None)
        line = getattr(ref, "line", None)

        if not spec or not fpath or not fpath.endswith(".py") or not line:
            continue

        root_name = spec.split(".")[0]
        if root_name not in by_name:
            continue

        spec_to_refs.setdefault(spec, []).append(ref.id)
        if spec not in spec_sample:
            spec_sample[spec] = (fpath, fhash, line)

    if not spec_sample:
        return 0

    root = Path(project_root)

    try:
        project = jedi.Project(path=str(root))
    except Exception:
        return 0

    by_file: dict[str, list[tuple[str, int]]] = {}
    file_hashes: dict[str, str] = {}
    for spec, (fpath, fhash, line) in spec_sample.items():
        by_file.setdefault(fpath, []).append((spec, line))
        file_hashes[fpath] = fhash

    spec_results: dict[str, str] = {}

    for file_path, work_items in by_file.items():
        fhash = file_hashes[file_path]
        content = await Blob.get(fhash)
        if content is None:
            continue

        source = content.decode("utf-8", errors="replace")
        lines = source.splitlines()
        abs_path = root / file_path

        jedi_work = []
        for spec, line_no in work_items:
            if line_no > len(lines):
                continue
            line_text = lines[line_no - 1]
            leaf = spec.split(".")[-1] if "." in spec else spec
            col = line_text.find(leaf)
            if col < 0:
                col = line_text.find(spec.split(".")[0] if "." in spec else spec)
            if col < 0:
                continue
            jedi_work.append((spec, line_no, col))

        if not jedi_work:
            continue

        def _resolve_batch(src, path, proj, items):
            try:
                script = jedi.Script(src, path=path, project=proj)
            except Exception:
                return []
            results = []
            for spec_name, line_no, col in items:
                try:
                    defs = script.goto(line_no, col)
                    if defs:
                        results.append((spec_name, defs[0]))
                except Exception:  # noqa: S110
                    pass
            return results

        batch_results = await asyncio.to_thread(_resolve_batch, source, str(abs_path), project, jedi_work)

        for spec_name, definition in batch_results:
            target_id = _match_jedi_result(definition, by_name, by_qualified)
            if target_id is not None:
                spec_results[spec_name] = target_id

    resolved = 0
    for spec, target_id in spec_results.items():
        ref_ids = spec_to_refs.get(spec, [])
        for ref_id in ref_ids:
            await Reference.where(id=ref_id).update(target_symbol_id=target_id)
            resolved += 1

    return resolved


def _match_jedi_result(
    definition,
    by_name: dict[str, list[str]],
    by_qualified: dict[str, str],
) -> str | None:
    """Match a jedi definition result to a symbol ID in our index.

    Args:
        definition: A jedi Name object from goto().
        by_name: Symbol name -> symbol_id lookup.
        by_qualified: Qualified name -> symbol_id lookup.

    Returns:
        Matching symbol ID, or None.
    """
    name = definition.name
    full_name = definition.full_name or ""

    if definition.in_builtin_module():
        return None

    if full_name:
        parts = full_name.split(".")
        for i in range(len(parts)):
            candidate = ".".join(parts[i:])
            if candidate in by_qualified:
                return by_qualified[candidate]

    if name and name in by_name:
        if len(by_name[name]) == 1:
            return by_name[name][0]
        if definition.module_path:
            def_path = str(definition.module_path).replace("\\", "/")
            for sid in by_name[name]:
                if def_path.endswith(sid.split("::")[1].split("::")[0] if "::" in sid else ""):
                    return sid
        return by_name[name][0]

    return None


def _match_specifier(
    spec: str,
    by_name: dict[str, list[str]],
    by_qualified: dict[str, str],
    caller_symbol_id: str = "",
) -> str | None:
    """Match a call site specifier to a known symbol ID.

    Tries multiple strategies:
    1. Exact name match (simple calls like "foo")
    2. Qualified name match ("Class.method")
    3. self.method scoped to caller's class
    4. Root name from dotted path ("Repo.where" -> "Repo")
    5. Unique leaf name (last segment, only if unambiguous)

    Args:
        spec: The target_specifier from a call site.
        by_name: Map of symbol name -> list of symbol IDs.
        by_qualified: Map of qualified name -> symbol ID.
        caller_symbol_id: Symbol ID of the caller, used for self. scoping.

    Returns:
        Matching symbol ID, or None.
    """
    clean = spec

    if clean in by_name:
        return by_name[clean][0]

    if clean in by_qualified:
        return by_qualified[clean]

    if "." not in clean:
        return None

    parts = clean.split(".")

    if parts[0] == "self" and len(parts) >= 2:
        method_name = parts[1]
        caller_class = _extract_class_from_symbol_id(caller_symbol_id)
        if caller_class:
            qualified = f"{caller_class}.{method_name}"
            if qualified in by_qualified:
                return by_qualified[qualified]
        if method_name in by_name:
            return by_name[method_name][0]
        return None

    qualified_attempt = ".".join(parts[:2]) if len(parts) >= 2 else None
    if qualified_attempt and qualified_attempt in by_qualified:
        return by_qualified[qualified_attempt]

    root = parts[0]
    if root in by_name:
        return by_name[root][0]

    leaf = parts[-1]
    if leaf in by_name and len(by_name[leaf]) == 1:
        return by_name[leaf][0]

    return None


def _extract_class_from_symbol_id(symbol_id: str) -> str | None:
    """Extract the class name from a method's symbol ID.

    Symbol IDs for methods look like:
    "repo::path/file.py::ClassName.method_name#method"

    Args:
        symbol_id: Full symbol ID string.

    Returns:
        Class name, or None if not a method.
    """
    if not symbol_id or "::" not in symbol_id:
        return None
    tail = symbol_id.rsplit("::", maxsplit=1)[-1]
    if "#" in tail:
        tail = tail.rsplit("#", maxsplit=1)[0]
    if "." in tail:
        return tail.rsplit(".", maxsplit=1)[0]
    return None


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
    pattern = r"\b" + re.escape(name) + r"\b"
    return bool(re.search(pattern, text))
