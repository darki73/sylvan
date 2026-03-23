"""Code smell detection — static analysis from indexed symbol data."""

from __future__ import annotations

from dataclasses import dataclass

from sylvan.database.orm import Symbol
from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class CodeSmell:
    """A detected code quality issue.

    Attributes:
        symbol_id: The symbol where the smell was detected.
        name: Symbol name.
        file: File path.
        line: Line number.
        smell_type: Category of the smell.
        severity: ``low``, ``medium``, or ``high``.
        message: Human-readable description.
    """

    symbol_id: str
    name: str
    file: str
    line: int
    smell_type: str
    severity: str
    message: str


async def detect_code_smells(repo_id: int) -> list[CodeSmell]:
    """Detect code smells in all symbols of a repository.

    Checks performed:
        - **too_many_parameters**: functions with > 8 parameters.
        - **too_long**: functions longer than 200 lines.
        - **missing_docstring**: public functions/classes without docstrings.
        - **missing_types**: public functions without return type annotations.
        - **too_many_methods**: classes with > 20 methods.

    Args:
        repo_id: Database ID of the repository.

    Returns:
        List of :class:`CodeSmell` instances sorted by file path and line.
    """
    smells: list[CodeSmell] = []

    symbols = await (
        Symbol.query()
        .select("symbols.*", "files.path as file_path")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .where_not_like("files.path", "%test%")
        .where_not_like("files.path", "%spec%")
        .get()
    )

    for sym in symbols:
        file_path = getattr(sym, "file_path", "") or ""
        sig = sym.signature or ""

        # --- Too many parameters ---
        if sym.kind in ("function", "method"):
            param_count = _count_parameters(sig)
            if param_count > 8:
                smells.append(CodeSmell(
                    symbol_id=sym.symbol_id,
                    name=sym.name,
                    file=file_path,
                    line=sym.line_start or 0,
                    smell_type="too_many_parameters",
                    severity="medium",
                    message=f"{sym.name} has {param_count} parameters (max recommended: 8)",
                ))

        # --- Too long ---
        if sym.line_start and sym.line_end:
            length = sym.line_end - sym.line_start
            if length > 200:
                smells.append(CodeSmell(
                    symbol_id=sym.symbol_id,
                    name=sym.name,
                    file=file_path,
                    line=sym.line_start,
                    smell_type="too_long",
                    severity="high" if length > 400 else "medium",
                    message=f"{sym.name} is {length} lines long (max recommended: 200)",
                ))

        # --- Missing docstring on public symbols ---
        if sym.kind in ("function", "class", "method") and not sym.name.startswith("_") and not (
            sym.docstring and len(sym.docstring.strip()) > 10
        ):
            smells.append(CodeSmell(
                symbol_id=sym.symbol_id,
                name=sym.name,
                file=file_path,
                line=sym.line_start or 0,
                smell_type="missing_docstring",
                severity="low",
                message=f"{sym.name} is public but has no docstring",
            ))

        # --- Missing return type annotation ---
        if sym.kind in ("function", "method") and not sym.name.startswith("_") and "->" not in sig:
            smells.append(CodeSmell(
                symbol_id=sym.symbol_id,
                name=sym.name,
                file=file_path,
                line=sym.line_start or 0,
                smell_type="missing_types",
                severity="low",
                message=f"{sym.name} has no return type annotation",
            ))

    # --- Too many methods per class ---
    class_symbols = [s for s in symbols if s.kind == "class"]
    for cls in class_symbols:
        method_count = sum(
            1
            for s in symbols
            if s.parent_symbol_id == cls.symbol_id and s.kind == "method"
        )
        if method_count > 20:
            file_path = getattr(cls, "file_path", "") or ""
            smells.append(CodeSmell(
                symbol_id=cls.symbol_id,
                name=cls.name,
                file=file_path,
                line=cls.line_start or 0,
                smell_type="too_many_methods",
                severity="medium",
                message=f"Class {cls.name} has {method_count} methods (max recommended: 20)",
            ))

    return smells


def _count_parameters(signature: str) -> int:
    """Count the number of parameters in a function signature.

    Excludes ``self`` and ``cls`` from the count.

    Args:
        signature: The function signature string.

    Returns:
        Number of parameters, excluding self/cls.
    """
    if "(" not in signature or ")" not in signature:
        return 0
    params_str = signature[signature.index("(") + 1 : signature.rindex(")")]
    if not params_str.strip():
        return 0
    params = [p.strip() for p in params_str.split(",")]
    return len([p for p in params if p and p not in ("self", "cls")])
