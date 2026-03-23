"""Source fetcher -- git clone or tarball download at a specific version."""

import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import httpx

from sylvan.logging import get_logger

logger = get_logger(__name__)

_SAFE_TAG = re.compile(r'^[a-zA-Z0-9._\-/]+$')


def _validate_tag(tag: str) -> str:
    """Validate a git tag to prevent option injection.

    Args:
        tag: Git tag string to validate.

    Returns:
        The validated tag string.

    Raises:
        ValueError: If the tag contains unsafe characters or starts with ``-``.
    """
    if not _SAFE_TAG.match(tag) or tag.startswith("-"):
        raise ValueError(f"Invalid git tag: {tag!r}")
    return tag


def fetch_source(
    repo_url: str,
    tag: str,
    dest: Path,
    timeout: int = 120,
) -> Path:
    """Fetch library source at a specific version.

    Strategy:
    1. ``git clone --depth 1 --branch {tag}``
    2. Fallback: try without v-prefix or with v-prefix
    3. Fallback: download GitHub tarball
    4. Last resort: clone default branch

    Args:
        repo_url: Repository URL (e.g. ``https://github.com/org/repo``).
        tag: Git tag to checkout (e.g. ``"v1.2.3"`` or ``"1.2.3"``).
        dest: Destination directory for the cloned source.
        timeout: Clone timeout in seconds.

    Returns:
        Path to the fetched source directory.

    Raises:
        RuntimeError: If all fetch strategies fail.
    """
    dest.mkdir(parents=True, exist_ok=True)

    # Try git clone with the exact tag
    if _git_clone(repo_url, tag, dest, timeout):
        return dest

    # Try alternate tag formats
    if tag.startswith("v"):
        alt_tag = tag[1:]  # strip v
    else:
        alt_tag = f"v{tag}"  # add v

    if _git_clone(repo_url, alt_tag, dest, timeout):
        return dest

    # Fallback: GitHub tarball
    if "github.com" in repo_url:
        for t in (tag, alt_tag):
            if _download_github_tarball(repo_url, t, dest, timeout):
                return dest

    # Last resort: clone default branch (no specific version)
    logger.warning("no_tag_found", repo_url=repo_url, tag=tag, fallback="default_branch")
    if _git_clone_default(repo_url, dest, timeout):
        return dest

    raise RuntimeError(
        f"Failed to fetch source for {repo_url} at tag {tag}. "
        f"Tried git clone (tag, v-prefix, default branch) and tarball download."
    )


def _git_clone(repo_url: str, tag: str, dest: Path, timeout: int) -> bool:
    """Shallow clone a repo at a specific tag.

    Args:
        repo_url: Repository URL.
        tag: Git tag to clone.
        dest: Destination directory.
        timeout: Process timeout in seconds.

    Returns:
        ``True`` if the clone succeeded.
    """
    try:
        _validate_tag(tag)

        if any(dest.iterdir()):
            shutil.rmtree(dest)
            dest.mkdir(parents=True)

        proc = subprocess.Popen(
            [
                "git", "clone",
                "--depth", "1",
                "--branch", tag,
                "--single-branch",
                "--", repo_url,
                str(dest),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _, stderr = proc.communicate(timeout=timeout)

        if proc.returncode == 0:
            logger.info("git_cloned", repo_url=repo_url, tag=tag)
            return True

        logger.debug("clone_failed", repo_url=repo_url, tag=tag,
                     stderr=stderr.decode("utf-8", errors="replace").strip() if stderr else "")
        return False

    except subprocess.TimeoutExpired:
        logger.warning("clone_timeout", repo_url=repo_url, tag=tag, timeout_s=timeout)
        return False
    except FileNotFoundError:
        logger.warning("git_not_found")
        return False
    except Exception as e:
        logger.debug("clone_error", error=str(e))
        return False


def _git_clone_default(repo_url: str, dest: Path, timeout: int) -> bool:
    """Shallow clone the default branch (when no tag matches).

    Args:
        repo_url: Repository URL.
        dest: Destination directory.
        timeout: Process timeout in seconds.

    Returns:
        ``True`` if the clone succeeded.
    """
    try:
        if any(dest.iterdir()):
            shutil.rmtree(dest)
            dest.mkdir(parents=True)

        proc = subprocess.Popen(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        proc.communicate(timeout=timeout)
        if proc.returncode == 0:
            logger.info("git_cloned_default", repo_url=repo_url)
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return False


def _download_github_tarball(repo_url: str, tag: str, dest: Path, timeout: int) -> bool:
    """Download and extract a GitHub tarball safely.

    Args:
        repo_url: GitHub repository URL.
        tag: Git tag to download.
        dest: Destination directory for extraction.
        timeout: HTTP timeout in seconds.

    Returns:
        ``True`` if the tarball was downloaded and extracted successfully.
    """
    match = None
    for prefix in ("https://github.com/", "http://github.com/"):
        if repo_url.startswith(prefix):
            match = repo_url[len(prefix):].rstrip("/")
            break

    if match is None:
        return False

    tarball_url = f"https://github.com/{match}/archive/refs/tags/{tag}.tar.gz"
    logger.debug("trying_tarball", url=tarball_url)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with httpx.stream("GET", tarball_url, timeout=timeout, follow_redirects=True) as r:
                if r.status_code != 200:
                    return False
                for chunk in r.iter_bytes():
                    tmp.write(chunk)

        import tarfile
        with tarfile.open(tmp_path, "r:gz") as tar:
            members = tar.getmembers()
            if members:
                top_dir = members[0].name.split("/")[0]
                for member in members:
                    if "/" in member.name:
                        member.name = member.name[len(top_dir) + 1:]
                        if not member.name:
                            continue
                        if member.issym() or member.islnk():
                            continue
                        if ".." in member.name.split("/") or member.name.startswith("/"):
                            continue
                        resolved = (dest / member.name).resolve()
                        if not str(resolved).startswith(str(dest.resolve())):
                            continue
                        tar.extract(member, dest)

        logger.info("tarball_downloaded", repo_url=repo_url, tag=tag)
        return True

    except Exception as e:
        logger.debug("tarball_download_failed", error=str(e))
        return False
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def get_library_path(manager: str, name: str, version: str) -> Path:
    """Get the local storage path for a library's source code.

    Uses ``config.library_path`` (defaults to ``~/.sylvan/libraries/``).

    Args:
        manager: Package manager identifier (e.g. ``"pip"``).
        name: Package name.
        version: Package version string.

    Returns:
        Absolute path to the library's source directory.
    """
    from sylvan.config import get_config
    base = get_config().library_path
    safe_name = name.replace("/", "--")
    return base / manager / safe_name / version


def _force_rmtree(path: Path) -> None:
    """Remove a directory tree, handling read-only files on Windows.

    Args:
        path: Directory to remove.
    """

    def _on_error(func, fpath, exc_info):
        """Make the file writable and retry the removal."""
        Path(fpath).chmod(stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onexc=_on_error)


def remove_library_source(manager: str, name: str, version: str) -> bool:
    """Remove downloaded library source from disk.

    Args:
        manager: Package manager identifier.
        name: Package name.
        version: Package version string.

    Returns:
        ``True`` if the directory existed and was removed.
    """
    path = get_library_path(manager, name, version)
    if path.exists():
        _force_rmtree(path)
        return True
    return False
