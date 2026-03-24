"""Configuration — single source of truth for all sylvan settings.

Loads from ``~/.sylvan/config.yaml``. Every part of the application
accesses settings through ``get_config()``. One file, one object,
one access pattern.

The config hierarchy:

.. code-block:: yaml

    database:
      backend: sqlite
      path: ~/.sylvan/sylvan.db
      pool_size: 1

    server:
      transport: stdio
      host: 127.0.0.1
      port: 8420
      max_concurrent_tools: 8
      request_timeout: 30

    indexing:
      max_file_size: 512000
      max_files_local: 5000
      max_files_github: 10000

    summary:
      provider: heuristic
      endpoint: ""
      model: ""

    embedding:
      provider: sentence-transformers
      endpoint: ""
      model: sentence-transformers/all-MiniLM-L6-v2
      dimensions: 384

    search:
      default_max_results: 20
      token_budget: null
      fts_weight: 0.7
      vector_weight: 0.3

    logging:
      level: INFO
      file_max_bytes: 10485760
      file_backup_count: 3

    session:
      flush_interval: 5

    libraries:
      path: ~/.sylvan/libraries
      fetch_timeout: 120
      overrides: {}

    security:
      validate_paths: true
      detect_secrets: true
      reject_symlinks: true
"""

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _sylvan_home() -> Path:
    """Return the sylvan home directory, creating it if needed.

    Respects the ``SYLVAN_HOME`` environment variable; defaults to
    ``~/.sylvan``.

    Returns:
        Absolute path to the sylvan home directory.
    """
    p = Path(os.environ.get("SYLVAN_HOME", Path.home() / ".sylvan"))
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass(slots=True)
class DatabaseConfig:
    """Database connection settings.

    Attributes:
        backend: Storage backend type (``"sqlite"`` or ``"postgres"``).
        path: File path for SQLite, or DSN for PostgreSQL.
        pool_size: Connection pool size (1 for SQLite, higher for PostgreSQL).
    """

    backend: str = "sqlite"
    path: str = ""
    pool_size: int = 1

    def __post_init__(self) -> None:
        """Set default path if empty.
        """
        if not self.path:
            self.path = str(_sylvan_home() / "sylvan.db")

    @property
    def resolved_path(self) -> Path:
        """Return the database path as a resolved Path object.

        Returns:
            Absolute path to the database file (SQLite) or the DSN string as Path.
        """
        return Path(self.path)


@dataclass(slots=True)
class ServerConfig:
    """MCP server settings.

    Attributes:
        transport: Transport mode (``"stdio"``, ``"sse"``, ``"http"``).
        host: Bind address for SSE/HTTP modes.
        port: Port number for SSE/HTTP modes.
        max_concurrent_tools: Maximum parallel tool calls (semaphore size).
        request_timeout: Seconds to wait for the semaphore before returning server_busy.
    """

    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8420
    max_concurrent_tools: int = 8
    request_timeout: int = 30
    dashboard_port: int = 32400
    dashboard_random_port: bool = False
    workflow_gate: bool = True


@dataclass(slots=True)
class ClusterConfig:
    """Multi-instance cluster settings.

    Attributes:
        enabled: Whether multi-instance support is active.
        port: HTTP port for cluster communication and dashboard.
        heartbeat_interval: Seconds between session stat flushes.
        leader_timeout: Seconds before a dead leader is considered gone.
    """

    enabled: bool = True
    port: int = 32400
    heartbeat_interval: int = 10
    leader_timeout: int = 30


@dataclass(slots=True)
class IndexingConfig:
    """Indexing pipeline settings.

    Attributes:
        max_file_size: Maximum file size in bytes to index.
        max_files_local: Maximum files to index for a local repository.
        max_files_github: Maximum files to index for a remote repository.
        source_roots: Prefix paths to try when resolving import specifiers.
    """

    max_file_size: int = 512_000
    max_files_local: int = 5_000
    max_files_github: int = 10_000
    source_roots: list[str] = field(default_factory=lambda: ["", "src/", "lib/", "app/"])


@dataclass(slots=True)
class SummaryConfig:
    """AI summary provider settings.

    Attributes:
        provider: Provider name (``"heuristic"``, ``"ollama"``, ``"claude-code"``, ``"codex"``).
        endpoint: Remote endpoint URL (for ollama/custom providers).
        model: Model identifier for the provider.
    """

    provider: str = "heuristic"
    endpoint: str = ""
    model: str = ""


@dataclass(slots=True)
class EmbeddingConfig:
    """Embedding vector provider settings.

    Attributes:
        provider: Provider name (``"sentence-transformers"``, ``"ollama"``).
        endpoint: Remote endpoint URL (for ollama provider).
        model: Model identifier for embedding generation.
        dimensions: Dimensionality of the embedding vectors.
    """

    provider: str = "sentence-transformers"
    endpoint: str = ""
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 384


@dataclass(slots=True)
class SearchConfig:
    """Search behavior settings.

    Attributes:
        default_max_results: Default number of results for search tools.
        token_budget: Default token budget for result packing (None = unlimited).
        fts_weight: FTS relevance weight in hybrid search (0-1).
        vector_weight: Vector similarity weight in hybrid search (0-1).
    """

    default_max_results: int = 20
    token_budget: int | None = None
    fts_weight: float = 0.7
    vector_weight: float = 0.3


@dataclass(slots=True)
class LoggingConfig:
    """Logging settings.

    Attributes:
        level: Minimum log level for console output.
        file_max_bytes: Maximum log file size before rotation.
        file_backup_count: Number of rotated log files to keep.
    """

    level: str = "INFO"
    file_max_bytes: int = 10 * 1024 * 1024
    file_backup_count: int = 3


@dataclass(slots=True)
class SessionConfig:
    """Session tracking settings.

    Attributes:
        flush_interval: Number of tool calls between usage stat flushes.
    """

    flush_interval: int = 5


@dataclass(slots=True)
class LibraryConfig:
    """Third-party library management settings.

    Attributes:
        path: Directory for downloaded library sources.
        fetch_timeout: Timeout in seconds for fetching library source code.
        overrides: Manual package-to-repo URL mappings for resolution.
    """

    path: str = ""
    fetch_timeout: int = 120
    overrides: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set default path if empty.
        """
        if not self.path:
            self.path = str(_sylvan_home() / "libraries")

    @property
    def resolved_path(self) -> Path:
        """Return the library path as a resolved Path object.

        Returns:
            Absolute path to the library storage directory.
        """
        return Path(self.path)


@dataclass(slots=True)
class QualityConfig:
    """Quality gate thresholds for the quality report.

    Attributes:
        max_complexity: Maximum cyclomatic complexity before flagging.
        max_function_length: Maximum function length in lines.
        max_parameters: Maximum parameters per function.
        min_doc_coverage: Minimum documentation coverage percentage.
        min_test_coverage: Minimum test coverage percentage.
        security_scan: Enable security pattern scanning.
        duplication_min_lines: Minimum function length for duplication detection.
    """

    max_complexity: int = 25
    max_function_length: int = 200
    max_parameters: int = 8
    min_doc_coverage: float = 80.0
    min_test_coverage: float = 60.0
    security_scan: bool = True
    duplication_min_lines: int = 5


@dataclass(slots=True)
class SecurityConfig:
    """Security settings.

    Attributes:
        validate_paths: Enable path traversal validation during indexing.
        detect_secrets: Enable secret file detection and exclusion.
        reject_symlinks: Reject symlinks that escape the project root.
    """

    validate_paths: bool = True
    detect_secrets: bool = True
    reject_symlinks: bool = True


@dataclass(slots=True)
class ExtensionConfig:
    """User extension settings.

    Attributes:
        enabled: Whether to load extensions from ~/.sylvan/extensions/.
        exclude: List of extension files to skip (e.g. "tools/broken.py").
    """

    enabled: bool = True
    exclude: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Config:
    """Global sylvan configuration — the single source of truth.

    Loaded from ``~/.sylvan/config.yaml``. Every part of the application
    accesses this through ``get_config()``.

    Attributes:
        database: Database connection settings.
        server: MCP server settings.
        cluster: Multi-instance cluster settings.
        indexing: Indexing pipeline settings.
        summary: AI summary provider settings.
        embedding: Embedding vector provider settings.
        search: Search behavior settings.
        logging: Logging settings.
        session: Session tracking settings.
        libraries: Third-party library management settings.
        quality: Quality gate thresholds for the quality report.
        security: Security settings.
        extensions: User extension settings.
    """

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    libraries: LibraryConfig = field(default_factory=LibraryConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    extensions: ExtensionConfig = field(default_factory=ExtensionConfig)

    @property
    def db_path(self) -> Path:
        """Shortcut for ``database.resolved_path``.

        Returns:
            Path to the database file.
        """
        return self.database.resolved_path

    @property
    def library_path(self) -> Path:
        """Shortcut for ``libraries.resolved_path``.

        Returns:
            Path to the library storage directory.
        """
        return self.libraries.resolved_path

    @property
    def max_file_size(self) -> int:
        """Shortcut for ``indexing.max_file_size``.

        Returns:
            Maximum file size in bytes.
        """
        return self.indexing.max_file_size

    @property
    def max_files_local(self) -> int:
        """Shortcut for ``indexing.max_files_local``.

        Returns:
            Maximum files for local repos.
        """
        return self.indexing.max_files_local

    @property
    def max_files_github(self) -> int:
        """Shortcut for ``indexing.max_files_github``.

        Returns:
            Maximum files for remote repos.
        """
        return self.indexing.max_files_github

    @property
    def overrides(self) -> dict[str, str]:
        """Shortcut for ``libraries.overrides``.

        Returns:
            Package-to-repo URL mapping dict.
        """
        return self.libraries.overrides

    def set_override(self, key: str, repo_url: str) -> None:
        """Add or update a package-to-repo URL mapping.

        Args:
            key: Package spec key (e.g. ``"pip/asyncpg"``).
            repo_url: Git repository URL.
        """
        self.libraries.overrides[key] = repo_url
        self.save()

    def remove_override(self, key: str) -> bool:
        """Remove a package-to-repo URL mapping.

        Args:
            key: Package spec key to remove.

        Returns:
            True if the key existed and was removed.
        """
        if key not in self.libraries.overrides:
            return False
        del self.libraries.overrides[key]
        self.save()
        return True

    def to_yaml(self) -> str:
        """Serialize this config to a YAML string.

        Only includes non-default sections to keep the file clean.

        Returns:
            YAML-formatted configuration string.
        """
        data: dict = {}
        defaults = Config()

        if self.database != defaults.database:
            data["database"] = _dataclass_to_dict(self.database)
        if self.server != defaults.server:
            data["server"] = _dataclass_to_dict(self.server)
        if self.cluster != defaults.cluster:
            data["cluster"] = _dataclass_to_dict(self.cluster)
        if self.indexing != defaults.indexing:
            data["indexing"] = _dataclass_to_dict(self.indexing)
        if self.summary != defaults.summary:
            data["summary"] = _dataclass_to_dict(self.summary)
        if self.embedding != defaults.embedding:
            data["embedding"] = _dataclass_to_dict(self.embedding)
        if self.search != defaults.search:
            data["search"] = _dataclass_to_dict(self.search)
        if self.logging != defaults.logging:
            data["logging"] = _dataclass_to_dict(self.logging)
        if self.session != defaults.session:
            data["session"] = _dataclass_to_dict(self.session)
        if self.quality != defaults.quality:
            data["quality"] = _dataclass_to_dict(self.quality)
        if self.libraries.overrides:
            data.setdefault("libraries", {})["overrides"] = dict(sorted(self.libraries.overrides.items()))
        if self.libraries.fetch_timeout != defaults.libraries.fetch_timeout:
            data.setdefault("libraries", {})["fetch_timeout"] = self.libraries.fetch_timeout
        if self.security != defaults.security:
            data["security"] = _dataclass_to_dict(self.security)

        return yaml.dump(data, default_flow_style=False, sort_keys=False) if data else ""

    def save(self, path: Path | None = None) -> Path:
        """Save this config to a YAML file.

        Args:
            path: File path to write. Defaults to ``~/.sylvan/config.yaml``.

        Returns:
            The path the config was saved to.
        """
        if path is None:
            path = _sylvan_home() / "config.yaml"
        path.write_text(self.to_yaml(), encoding="utf-8")
        return path


def _dataclass_to_dict(obj: object) -> dict:
    """Convert a dataclass to a dict, excluding empty strings and default-like values.

    Args:
        obj: A dataclass instance.

    Returns:
        Dict with non-empty field values.
    """
    from dataclasses import fields as dc_fields
    result = {}
    for f in dc_fields(obj):
        val = getattr(obj, f.name)
        if val != "" and val is not None:
            result[f.name] = val
    return result


def load_config() -> Config:
    """Load config from ``~/.sylvan/config.yaml``, falling back to defaults.

    Returns:
        A fully populated Config instance.
    """
    config_path = _sylvan_home() / "config.yaml"

    if not config_path.exists():
        return Config()

    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:
        from sylvan.logging import get_logger
        get_logger(__name__).warning("config_parse_failed", error=str(exc), path=str(config_path))
        return Config()

    return _parse_config(raw)


def _parse_section(raw: dict, cls: type, defaults: object | None = None) -> object:
    """Parse a config section dict into a dataclass instance.

    Args:
        raw: Raw dict from YAML/TOML for this section.
        cls: The dataclass class to instantiate.
        defaults: Optional default instance for fallback values.

    Returns:
        A populated dataclass instance.
    """
    from dataclasses import fields as dc_fields
    kwargs = {}
    for f in dc_fields(cls):
        if f.name in raw:
            kwargs[f.name] = raw[f.name]
    return cls(**kwargs)


_SECTION_MAP: dict[str, type] = {
    "database": DatabaseConfig,
    "server": ServerConfig,
    "cluster": ClusterConfig,
    "indexing": IndexingConfig,
    "summary": SummaryConfig,
    "embedding": EmbeddingConfig,
    "search": SearchConfig,
    "logging": LoggingConfig,
    "session": SessionConfig,
    "libraries": LibraryConfig,
    "quality": QualityConfig,
    "security": SecurityConfig,
    "extensions": ExtensionConfig,
}
"""Maps YAML section names to their dataclass types."""


def _parse_config(raw: dict) -> Config:
    """Parse a raw config dict into a Config instance.

    Iterates over known section names and parses each into its
    corresponding dataclass. Unknown keys are silently ignored.

    Args:
        raw: Dictionary loaded from YAML.

    Returns:
        A populated Config instance.
    """
    config = Config()
    for section_name, section_cls in _SECTION_MAP.items():
        if section_name in raw and isinstance(raw[section_name], dict):
            setattr(config, section_name, _parse_section(raw[section_name], section_cls))
    return config


@functools.cache
def get_config() -> Config:
    """Get the global config singleton.

    Uses :func:`functools.cache` so the config file is read at most once
    per process lifetime.

    Returns:
        The shared Config instance.
    """
    return load_config()


def reset_config() -> None:
    """Reset config singleton and ORM connection state (for testing).
    """
    get_config.cache_clear()
    try:
        from sylvan.tools.support.response import reset_orm
        reset_orm()
    except ImportError:
        pass
