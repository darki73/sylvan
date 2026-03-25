"""Package registry -- resolve packages to source repositories."""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from sylvan.logging import get_logger

logger = get_logger(__name__)

REGISTRY_TIMEOUT = 15

# Re-export override functions so existing callers keep working
from sylvan.libraries.resolution.url_overrides import (  # noqa: F401
    list_overrides,
    load_overrides,
    remove_override,
    save_override,
)


@dataclass(slots=True, frozen=True)
class PackageInfo:
    """Resolved package metadata from a registry.

    Attributes:
        name: Package name as known by the registry.
        version: Resolved version string.
        repo_url: Source repository URL.
        tag: Git tag corresponding to the resolved version.
        manager: Package manager identifier (e.g. ``"pip"``).
    """

    name: str
    version: str
    repo_url: str
    tag: str
    manager: str


def resolve(manager: str, name: str, version: str = "latest") -> PackageInfo:
    """Resolve a package to its source repository and version.

    Checks user overrides in ``~/.sylvan/registry.toml`` first, then
    queries the package registry.

    Args:
        manager: Package manager name (e.g. ``"pip"``, ``"npm"``).
        name: Package name.
        version: Desired version, or ``"latest"``.

    Returns:
        A :class:`PackageInfo` with the resolved metadata.

    Raises:
        ValueError: If the package manager is unknown.
    """
    from sylvan.libraries.resolution.package_resolvers import RESOLVERS

    resolver = RESOLVERS.get(manager)
    if resolver is None:
        raise ValueError(f"Unknown package manager: {manager}. Supported: {', '.join(RESOLVERS)}")

    overrides = load_overrides()
    override_key = f"{manager}/{name}"
    if override_key in overrides:
        repo_url = overrides[override_key]
        logger.info("using_registry_override", key=override_key, repo_url=repo_url)
        resolved_version = version if version != "latest" else _resolve_version_only(manager, name)
        tag = guess_tag(resolved_version, repo_url)
        return PackageInfo(
            name=name,
            version=resolved_version,
            repo_url=validate_repo_url(repo_url),
            tag=tag,
            manager=manager,
        )

    return resolver(name, version)


def parse_package_spec(spec: str) -> tuple[str, str, str]:
    """Parse ``'manager/name[@version]'`` into ``(manager, name, version)``.

    Examples::

        'pip/django@4.2'     -> ('pip', 'django', '4.2')
        'npm/react'          -> ('npm', 'react', 'latest')
        'go/github.com/gin-gonic/gin@v1.9.1' -> ('go', 'github.com/gin-gonic/gin', 'v1.9.1')

    Args:
        spec: Package specification string.

    Returns:
        A ``(manager, name, version)`` tuple.

    Raises:
        ValueError: If the spec does not contain a ``/`` separator.
    """
    if "/" not in spec:
        raise ValueError(f"Invalid package spec '{spec}'. Use: manager/name[@version]")

    manager, rest = spec.split("/", 1)
    manager = manager.lower()

    if "@" in rest:
        if manager == "go":
            # Go modules can have slashes -- split on LAST @
            idx = rest.rfind("@")
            name = rest[:idx]
            version = rest[idx + 1 :]
        else:
            name, version = rest.rsplit("@", 1)
    else:
        name = rest
        version = "latest"

    return manager, name, version


def validate_repo_url(url: str) -> str:
    """Validate a repository URL to prevent SSRF.

    Args:
        url: URL string to validate.

    Returns:
        The validated URL.

    Raises:
        ValueError: If the URL scheme is not HTTP(S) or points to a
            private/loopback network.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    if parsed.hostname:
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError(f"URL points to private/loopback network: {url}")
        except ValueError as e:
            if "private" in str(e) or "loopback" in str(e):
                raise
    return url


def guess_tag(version: str, repo_url: str) -> str:
    """Guess the git tag format for a version.

    Args:
        version: Version string.
        repo_url: Repository URL (unused, reserved for future heuristics).

    Returns:
        The guessed tag string (currently returns the version as-is).
    """
    return version


def _resolve_version_only(manager: str, name: str) -> str:
    """Resolve just the latest version number (no repo URL needed).

    Args:
        manager: Package manager name.
        name: Package name.

    Returns:
        The latest version string, or ``"latest"`` on failure.
    """
    try:
        match manager:
            case "pip":
                r = httpx.get(f"https://pypi.org/pypi/{name}/json", timeout=REGISTRY_TIMEOUT, follow_redirects=True)
                r.raise_for_status()
                return r.json()["info"]["version"]
            case "npm":
                r = httpx.get(
                    f"https://registry.npmjs.org/{name}/latest", timeout=REGISTRY_TIMEOUT, follow_redirects=True
                )
                r.raise_for_status()
                return r.json().get("version", "latest")
    except Exception as exc:
        logger.debug("latest_version_lookup_failed", error=str(exc))
    return "latest"
