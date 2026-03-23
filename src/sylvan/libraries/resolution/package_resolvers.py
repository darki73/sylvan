"""Per-ecosystem package resolvers -- PyPI, npm, crates.io, Go proxy."""

import httpx

from sylvan.logging import get_logger

logger = get_logger(__name__)

from sylvan.libraries.resolution.package_registry import REGISTRY_TIMEOUT, PackageInfo, validate_repo_url

RESOLVERS: dict[str, callable] = {}
"""Dispatch table mapping package manager names to resolver functions."""


def _register(name: str) -> callable:
    """Decorator to register a resolver function under the given manager name.

    Args:
        name: Package manager key (e.g. ``"pip"``).

    Returns:
        Decorator that registers the function.
    """
    def decorator(fn: callable) -> callable:
        """Add the function to the RESOLVERS table.

        Args:
            fn: Resolver function to register.

        Returns:
            The unmodified function.
        """
        RESOLVERS[name] = fn
        return fn
    return decorator


@_register("pip")
def resolve_pypi(name: str, version: str) -> PackageInfo:
    """Resolve a Python package from PyPI.

    Args:
        name: PyPI package name.
        version: Desired version, or ``"latest"``.

    Returns:
        Resolved :class:`PackageInfo`.

    Raises:
        ValueError: If no source repository can be found.
    """
    if version == "latest":
        url = f"https://pypi.org/pypi/{name}/json"
    else:
        url = f"https://pypi.org/pypi/{name}/{version}/json"

    response = httpx.get(url, timeout=REGISTRY_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    data = response.json()

    info = data["info"]
    resolved_version = info["version"]

    repo_url = _extract_repo_url(info)
    if not repo_url:
        raise ValueError(
            f"Cannot find source repository for PyPI package '{name}'. "
            f"Fix with: sylvan library map pip/{name} https://github.com/org/repo"
        )

    from sylvan.libraries.resolution.package_registry import guess_tag
    tag = guess_tag(resolved_version, repo_url)

    return PackageInfo(
        name=name,
        version=resolved_version,
        repo_url=validate_repo_url(repo_url),
        tag=tag,
        manager="pip",
    )


@_register("npm")
def resolve_npm(name: str, version: str) -> PackageInfo:
    """Resolve a JavaScript/TypeScript package from npm.

    Args:
        name: npm package name.
        version: Desired version, or ``"latest"``.

    Returns:
        Resolved :class:`PackageInfo`.

    Raises:
        ValueError: If no source repository can be found.
    """
    if version == "latest":
        url = f"https://registry.npmjs.org/{name}/latest"
    else:
        url = f"https://registry.npmjs.org/{name}/{version}"

    response = httpx.get(url, timeout=REGISTRY_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    data = response.json()

    resolved_version = data.get("version", version)

    repo = data.get("repository", {})
    if isinstance(repo, str):
        repo_url = repo
    elif isinstance(repo, dict):
        repo_url = repo.get("url", "")
    else:
        repo_url = ""

    repo_url = repo_url.replace("git+", "").replace("git://", "https://")
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]

    if not repo_url:
        raise ValueError(
            f"Cannot find source repository for npm package '{name}'. "
            f"Fix with: sylvan library map npm/{name} https://github.com/org/repo"
        )

    return PackageInfo(
        name=name,
        version=resolved_version,
        repo_url=validate_repo_url(repo_url),
        tag=f"v{resolved_version}",
        manager="npm",
    )


@_register("cargo")
def resolve_cargo(name: str, version: str) -> PackageInfo:
    """Resolve a Rust crate from crates.io.

    Args:
        name: Crate name.
        version: Desired version, or ``"latest"``.

    Returns:
        Resolved :class:`PackageInfo`.

    Raises:
        ValueError: If no source repository can be found.
    """
    url = f"https://crates.io/api/v1/crates/{name}"
    headers = {"User-Agent": "sylvan (https://github.com/sylvan)"}

    response = httpx.get(url, timeout=REGISTRY_TIMEOUT, headers=headers, follow_redirects=True)
    response.raise_for_status()
    data = response.json()

    crate = data.get("crate", {})
    repo_url = crate.get("repository", "")

    if not repo_url:
        raise ValueError(
            f"Cannot find source repository for crate '{name}'. "
            f"Fix with: sylvan library map cargo/{name} https://github.com/org/repo"
        )

    if version == "latest":
        resolved_version = crate.get("max_version", crate.get("newest_version", ""))
    else:
        resolved_version = version

    from sylvan.libraries.resolution.package_registry import guess_tag
    tag = guess_tag(resolved_version, repo_url)

    return PackageInfo(
        name=name,
        version=resolved_version,
        repo_url=validate_repo_url(repo_url),
        tag=tag,
        manager="cargo",
    )


@_register("go")
def resolve_go(module: str, version: str) -> PackageInfo:
    """Resolve a Go module (module path IS the repo URL).

    Args:
        module: Go module path (e.g. ``"github.com/gin-gonic/gin"``).
        version: Desired version, or ``"latest"``.

    Returns:
        Resolved :class:`PackageInfo`.
    """
    if module.startswith("github.com/"):
        parts = module.split("/")
        if len(parts) >= 3:
            repo_url = f"https://github.com/{parts[1]}/{parts[2]}"
        else:
            repo_url = f"https://{module}"
    elif module.startswith("gitlab.com/"):
        repo_url = f"https://{module}"
    else:
        repo_url = f"https://{module}"

    if version == "latest":
        try:
            response = httpx.get(
                f"https://proxy.golang.org/{module}/@latest",
                timeout=REGISTRY_TIMEOUT,
                follow_redirects=True,
            )
            if response.status_code == 200:
                version = response.json().get("Version", "latest")
        except Exception as exc:
            logger.debug("go_version_lookup_failed", error=str(exc))

    tag = version if version.startswith("v") else f"v{version}"

    return PackageInfo(
        name=module,
        version=version,
        repo_url=validate_repo_url(repo_url),
        tag=tag,
        manager="go",
    )


def _extract_repo_url(info: dict) -> str:
    """Extract GitHub/GitLab repo URL from PyPI package metadata.

    Strips fragments, query strings, and deep paths to return only
    the base ``https://github.com/org/repo`` URL.

    Args:
        info: The ``info`` dict from the PyPI JSON API response.

    Returns:
        Clean repository URL string, or empty string if not found.
    """
    urls = info.get("project_urls") or {}

    for key in ("Source", "Source Code", "Repository", "GitHub", "Code", "Homepage"):
        url = urls.get(key, "")
        cleaned = _clean_repo_url(url)
        if cleaned:
            return cleaned

    home = info.get("home_page") or ""
    cleaned = _clean_repo_url(home)
    if cleaned:
        return cleaned

    for url in urls.values():
        if isinstance(url, str):
            cleaned = _clean_repo_url(url)
            if cleaned:
                return cleaned

    return ""


def _clean_repo_url(url: str) -> str:
    """Strip a GitHub/GitLab URL down to its base org/repo form.

    Handles URLs with fragments (#readme), deep paths (/blob/main/...),
    /issues, /wiki, etc. Returns only ``https://host/org/repo``.

    Args:
        url: Raw URL string from PyPI metadata.

    Returns:
        Clean repo URL, or empty string if not a recognized host.
    """
    if not url:
        return ""
    for host in ("github.com", "gitlab.com"):
        if host not in url:
            continue
        url = url.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].rstrip("/")
        idx = url.index(host)
        path = url[idx + len(host):]
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return f"https://{host}/{parts[0]}/{parts[1]}"
    return ""
