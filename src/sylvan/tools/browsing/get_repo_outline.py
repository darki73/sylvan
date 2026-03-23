"""MCP tool: get_repo_outline -- high-level summary of an indexed repo."""

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_repo_outline(repo: str) -> dict:
    """Get a high-level outline of an indexed repository.

    Shows file count, symbol count by kind, language distribution,
    and documentation overview.

    Args:
        repo: Repository name.

    Returns:
        Tool response dict with repo statistics and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()

    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

    repo_id = repo_obj.id

    languages = await (FileRecord.where(repo_id=repo_id)
                 .where_not_null("language")
                 .group_by("language")
                 .count())

    symbol_kinds = await (Symbol.query()
                    .join("files", "files.id = symbols.file_id")
                    .where("files.repo_id", repo_id)
                    .group_by("symbols.kind")
                    .count())

    total_files = await FileRecord.where(repo_id=repo_id).count()

    total_symbols = await (Symbol.query()
                     .join("files", "files.id = symbols.file_id")
                     .where("files.repo_id", repo_id)
                     .count())

    total_sections = await (Section.query()
                      .join("files", "files.id = sections.file_id")
                      .where("files.repo_id", repo_id)
                      .count())

    doc_files = await (FileRecord.query()
                 .select("DISTINCT files.id")
                 .join("sections sec", "sec.file_id = files.id")
                 .where("files.repo_id", repo_id)
                 .count())

    result = {
        "repo": repo,
        "indexed_at": repo_obj.indexed_at,
        "git_head": repo_obj.git_head,
        "files": total_files,
        "symbols": total_symbols,
        "sections": total_sections,
        "doc_files": doc_files,
        "languages": languages if isinstance(languages, dict) else {},
        "symbol_kinds": symbol_kinds if isinstance(symbol_kinds, dict) else {},
    }

    meta.set("repo", repo)
    return wrap_response(result, meta.build())
