"""Provider registry -- auto-detect and create summary/embedding providers."""

import contextlib
import importlib

from sylvan.config import get_config
from sylvan.logging import get_logger
from sylvan.providers.base import SummaryProvider
from sylvan.providers.registry import get_summary_provider_class

logger = get_logger(__name__)

_PROVIDER_MODULES = [
    "sylvan.providers.builtin.heuristic",
    "sylvan.providers.builtin.sentence_transformers",
    "sylvan.providers.external.ollama.provider",
    "sylvan.providers.external.claude_code",
    "sylvan.providers.external.codex",
]

for _mod in _PROVIDER_MODULES:
    with contextlib.suppress(ImportError):
        importlib.import_module(_mod)


def get_summary_provider() -> SummaryProvider:
    """Get the configured summary provider.

    Falls back to :class:`HeuristicSummaryProvider` when the configured
    provider is unavailable.

    Returns:
        A ready-to-use :class:`SummaryProvider` instance.
    """
    cfg = get_config()
    provider_name = cfg.summary.provider

    cls = get_summary_provider_class(provider_name)
    if cls is not None and provider_name != "heuristic":
        kwargs = {}
        if provider_name == "ollama":
            kwargs["endpoint"] = cfg.summary.endpoint or "http://localhost:11434"
            kwargs["model"] = cfg.summary.model or "llama3.2"
        provider = cls(**kwargs)
        if provider.available():
            return provider
        logger.debug(
            "%s not available, falling back to heuristic",
            provider_name,
        )

    fallback_cls = get_summary_provider_class("heuristic")
    return fallback_cls()
