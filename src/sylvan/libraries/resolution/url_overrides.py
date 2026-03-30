"""User-provided repo URL overrides — delegates to the global Config.

All override data lives in ``~/.sylvan/config.yaml`` under the
``overrides:`` key. This module provides convenience functions that
read from and write to the global Config singleton.
"""

from sylvan.logging import get_logger

logger = get_logger(__name__)


def load_overrides() -> dict[str, str]:
    """Load package -> repo URL mappings fresh from disk.

    Reads the config YAML directly so overrides added by the CLI
    or another process are visible without restarting the server.

    Returns:
        Dictionary mapping ``"manager/package"`` to repository URL strings.
    """
    from sylvan.config import _sylvan_home, get_config

    config_path = _sylvan_home() / "config.yaml"
    if config_path.exists():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            disk_overrides = raw.get("libraries", {}).get("overrides", {})
            if isinstance(disk_overrides, dict):
                cfg = get_config()
                cfg.libraries.overrides.update(disk_overrides)
                return dict(cfg.libraries.overrides)
        except Exception:
            logger.debug("overrides_reload_failed")
    return dict(get_config().overrides)


def save_override(key: str, repo_url: str) -> None:
    """Save a mapping to the global config.

    Args:
        key: Package spec key (e.g. ``"pip/tiktoken"``).
        repo_url: Git repository URL to associate.
    """
    from sylvan.config import get_config

    get_config().set_override(key, repo_url)
    logger.info("registry_override_saved", key=key, repo_url=repo_url)


def remove_override(key: str) -> bool:
    """Remove a mapping from the global config.

    Args:
        key: Package spec key to remove.

    Returns:
        ``True`` if the key existed and was removed.
    """
    from sylvan.config import get_config

    removed = get_config().remove_override(key)
    if removed:
        logger.info("registry_override_removed", key=key)
    return removed


def list_overrides() -> dict[str, str]:
    """Return all user-provided repo URL overrides.

    Returns:
        Dictionary mapping spec keys to repository URLs.
    """
    return load_overrides()
