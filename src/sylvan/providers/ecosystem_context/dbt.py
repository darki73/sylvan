"""dbt context provider -- enriches SQL models with business metadata."""

import re
from pathlib import Path
from typing import override

from sylvan.logging import get_logger

logger = get_logger(__name__)

from sylvan.providers.ecosystem_context.base import ContextProvider, FileContext, register_provider


@register_provider
class DbtContextProvider(ContextProvider):
    """Enriches dbt model files with descriptions, tags, and column metadata."""

    def __init__(self) -> None:
        """Initialize the dbt context provider with empty state.
        """
        self._models: dict[str, dict] = {}
        self._doc_blocks: dict[str, str] = {}
        self._project_root: Path | None = None

    @property
    @override
    def name(self) -> str:
        """Return the provider name.

        Returns:
            ``"dbt"``.
        """
        return "dbt"

    @override
    def detect(self, folder_path: Path) -> bool:
        """Check whether a ``dbt_project.yml`` file exists in the folder hierarchy.

        Args:
            folder_path: Root directory to search.

        Returns:
            ``True`` if a ``dbt_project.yml`` is found within 3 levels.
        """
        return any(
            list(folder_path.glob("*/" * depth + "dbt_project.yml"))
            for depth in range(3)
        )

    @override
    def load(self, folder_path: Path) -> None:
        """Load dbt model metadata from ``schema.yml`` and doc blocks.

        Args:
            folder_path: Root directory of the dbt project.
        """
        for depth in range(3):
            candidates = list(folder_path.glob("*/" * depth + "dbt_project.yml"))
            if candidates:
                self._project_root = candidates[0].parent
                break

        if self._project_root is None:
            return

        for md_file in self._project_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(
                    r"\{%\s*docs\s+(\w+)\s*%\}(.*?)\{%\s*enddocs\s*%\}",
                    content, re.DOTALL,
                ):
                    self._doc_blocks[m.group(1)] = m.group(2).strip()
            except OSError:
                pass

        try:
            import yaml
        except ImportError:
            return

        for schema_file in self._project_root.rglob("schema.yml"):
            try:
                with schema_file.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

                for model in data.get("models", []):
                    name = model.get("name", "")
                    if not name:
                        continue

                    desc = model.get("description", "")
                    # Resolve doc references
                    desc = re.sub(
                        r"\{\{\s*doc\(['\"](\w+)['\"]\)\s*\}\}",
                        lambda m: self._doc_blocks.get(m.group(1), m.group(0)),
                        desc,
                    )

                    columns = {}
                    for col in model.get("columns", []):
                        col_name = col.get("name", "")
                        col_desc = col.get("description", "")
                        if col_name:
                            columns[col_name] = col_desc

                    self._models[name] = {
                        "description": desc,
                        "tags": model.get("tags", []),
                        "columns": columns,
                    }
            except Exception as exc:
                logger.debug("dbt_model_parse_failed", error=str(exc))

    @override
    def get_file_context(self, file_path: str) -> FileContext | None:
        """Return context for a dbt model matched by file stem.

        Args:
            file_path: Relative path to a file within the project.

        Returns:
            A :class:`FileContext` if the file stem matches a known dbt model,
            otherwise ``None``.
        """
        stem = Path(file_path).stem
        meta = self._models.get(stem)
        if meta is None:
            return None

        return FileContext(
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            properties=meta.get("columns", {}),
        )

    @override
    def stats(self) -> dict:
        """Return statistics about loaded dbt metadata.

        Returns:
            Dictionary with ``models_loaded`` and ``doc_blocks`` counts.
        """
        return {
            "models_loaded": len(self._models),
            "doc_blocks": len(self._doc_blocks),
        }

    @override
    def get_metadata(self) -> dict:
        """Return structured column metadata for all loaded dbt models.

        Returns:
            Dictionary with a ``dbt_columns`` key mapping model names to
            their column descriptions.
        """
        columns = {}
        for model_name, meta in self._models.items():
            if meta.get("columns"):
                columns[model_name] = meta["columns"]
        return {"dbt_columns": columns}
