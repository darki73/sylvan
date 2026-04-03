"""Dependency file parsing -- requirements.txt, package.json, etc."""

import json
import os
import re
from pathlib import Path


def parse_dependencies(root: Path) -> list[dict]:
    """Detect and parse dependency files in a project root.

    Args:
        root: Project root directory to search for dependency files.

    Returns:
        List of dicts with ``manager``, ``name``, and ``version`` keys.
    """
    deps = []

    # Python: requirements.txt
    req_file = root / "requirements.txt"
    if req_file.exists():
        deps.extend(_parse_requirements_txt(req_file))

    # Python: pyproject.toml dependencies
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        deps.extend(_parse_pyproject_toml(pyproject))

    # Node: package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        deps.extend(_parse_package_json(pkg_json))

    # Go: go.mod
    go_mod = root / "go.mod"
    if go_mod.exists():
        deps.extend(_parse_go_mod(go_mod))

    # Rust: Cargo.toml
    cargo = root / "Cargo.toml"
    if cargo.exists():
        deps.extend(_parse_cargo_toml(cargo))

    return deps


def _parse_requirements_txt(path: Path) -> list[dict]:
    """Parse a ``requirements.txt`` file into dependency records.

    Args:
        path: Path to the requirements.txt file.

    Returns:
        List of dependency dicts.
    """
    deps = []
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("#", "-")):
                continue
            m = re.match(r"([\w.-]+)\s*([><=!~]+\s*[\w.*]+)?", stripped)
            if m:
                deps.append(
                    {
                        "manager": "pip",
                        "name": m.group(1),
                        "version": (m.group(2) or "").strip(),
                    }
                )
    except OSError:
        pass
    return deps


def _parse_pyproject_toml(path: Path) -> list[dict]:
    """Parse dependencies from a ``pyproject.toml`` file.

    Args:
        path: Path to the pyproject.toml file.

    Returns:
        List of dependency dicts.
    """
    deps = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        in_deps = False
        for line in content.splitlines():
            if re.match(r"^dependencies\s*=\s*\[", line):
                in_deps = True
                continue
            if in_deps:
                if line.strip() == "]":
                    in_deps = False
                    continue
                m = re.match(r'\s*"([\w.-]+)', line)
                if m:
                    deps.append({"manager": "pip", "name": m.group(1), "version": ""})
    except OSError:
        pass
    return deps


def _parse_package_json(path: Path) -> list[dict]:
    """Parse dependencies from a ``package.json`` file.

    Args:
        path: Path to the package.json file.

    Returns:
        List of dependency dicts.
    """
    deps = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        for section in ("dependencies", "devDependencies"):
            for name, version in data.get(section, {}).items():
                deps.append({"manager": "npm", "name": name, "version": version})
    except (OSError, json.JSONDecodeError):
        pass
    return deps


def _parse_go_mod(path: Path) -> list[dict]:
    """Parse dependencies from a ``go.mod`` file.

    Args:
        path: Path to the go.mod file.

    Returns:
        List of dependency dicts.
    """
    deps = []
    try:
        in_require = False
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("require ("):
                in_require = True
                continue
            if in_require and line.strip() == ")":
                in_require = False
                continue
            if in_require:
                parts = line.strip().split()
                if len(parts) >= 2:
                    deps.append({"manager": "go", "name": parts[0], "version": parts[1]})
            elif line.strip().startswith("require "):
                parts = line.strip().split()
                if len(parts) >= 3:
                    deps.append({"manager": "go", "name": parts[1], "version": parts[2]})
    except OSError:
        pass
    return deps


def _parse_cargo_toml(path: Path) -> list[dict]:
    """Parse dependencies from a ``Cargo.toml`` file.

    Args:
        path: Path to the Cargo.toml file.

    Returns:
        List of dependency dicts.
    """
    deps = []
    try:
        in_deps = False
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if re.match(r"^\[dependencies\]", line):
                in_deps = True
                continue
            if line.startswith("[") and in_deps:
                in_deps = False
                continue
            if in_deps:
                m = re.match(r'([\w-]+)\s*=\s*"([^"]+)"', line)
                if m:
                    deps.append({"manager": "cargo", "name": m.group(1), "version": m.group(2)})
    except OSError:
        pass
    return deps


def parse_composer_autoload(root: Path) -> dict[str, list[str]]:
    """Parse PSR-4 and PSR-0 autoload mappings from ``composer.json``.

    Reads both ``autoload`` and ``autoload-dev`` sections. PSR-4 allows a
    namespace prefix to map to either a single directory string or a list
    of directories.

    Args:
        root: Project root directory containing composer.json.

    Returns:
        Dict mapping namespace prefixes (with trailing backslash) to
        lists of directory base paths (with trailing forward slash).
        Empty dict if no composer.json or no autoload config.
    """
    composer_path = root / "composer.json"
    if not composer_path.exists():
        return {}

    try:
        data = json.loads(composer_path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return {}

    mappings: dict[str, list[str]] = {}

    for section_key in ("autoload", "autoload-dev"):
        section = data.get(section_key, {})
        for standard in ("psr-4", "psr-0"):
            for prefix, dirs in section.get(standard, {}).items():
                # Normalize prefix: ensure trailing backslash.
                if prefix and not prefix.endswith("\\"):
                    prefix = prefix + "\\"

                # Normalize dirs: always a list, always trailing slash.
                if isinstance(dirs, str):
                    dirs = [dirs]
                normalized = []
                for d in dirs:
                    d = d.replace("\\", "/")
                    if d and not d.endswith("/"):
                        d = d + "/"
                    normalized.append(d)

                if prefix in mappings:
                    # Merge without duplicates.
                    existing = set(mappings[prefix])
                    mappings[prefix].extend(d for d in normalized if d not in existing)
                else:
                    mappings[prefix] = normalized

    return mappings


def parse_tsconfig_aliases(root: Path) -> dict[str, list[str]]:
    """Parse path aliases from all tsconfig files in a project.

    Discovers ``tsconfig.json`` and ``tsconfig.*.json`` files, follows
    ``extends`` chains, and merges ``compilerOptions.paths`` entries
    with their ``baseUrl`` resolved to repo-relative paths.

    Handles wildcard patterns (``@/*`` -> ``./resources/js/*``) by
    stripping the trailing ``/*`` from both the alias and the target
    so the resolver can do prefix matching.

    Args:
        root: Project root directory.

    Returns:
        Dict mapping alias prefixes (e.g. ``@``) to lists of resolved
        directory paths (e.g. ``["resources/js"]``). Empty dict if no
        tsconfig or no paths configured.
    """
    aliases: dict[str, list[str]] = {}

    # Find all tsconfig files (skip node_modules, .nuxt, .next, dist, etc.)
    skip_dirs = {"node_modules", ".nuxt", ".next", ".output", "dist", "vendor", ".git"}
    tsconfig_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if f == "tsconfig.json" or (f.startswith("tsconfig.") and f.endswith(".json")):
                tsconfig_files.append(Path(dirpath) / f)

    # Collect which files are extends targets so we skip processing them standalone.
    extends_targets: set[str] = set()
    for tsconfig_path in tsconfig_files:
        try:
            raw = tsconfig_path.read_text(encoding="utf-8", errors="ignore")
            raw = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
            raw = re.sub(r",\s*([}\]])", r"\1", raw)
            data = json.loads(raw)
            extends = data.get("extends")
            if isinstance(extends, str):
                extends = [extends]
            for ext in extends or []:
                ext_path = (tsconfig_path.parent / ext).resolve()
                if ext_path.is_dir():
                    ext_path = ext_path / "tsconfig.json"
                elif not ext_path.suffix:
                    ext_path = ext_path.with_suffix(".json")
                extends_targets.add(str(ext_path))
        except (OSError, json.JSONDecodeError):
            pass

    for tsconfig_path in tsconfig_files:
        if str(tsconfig_path.resolve()) in extends_targets:
            continue
        paths_config, base_url = _resolve_tsconfig_paths(tsconfig_path, root)
        for pattern, targets in paths_config.items():
            alias = pattern.removesuffix("/*")
            resolved_targets: list[str] = []
            for target in targets:
                target = target.removesuffix("/*")
                # Resolve target relative to baseUrl, then make repo-relative.
                abs_target = (base_url / target).resolve()
                try:
                    rel_target = abs_target.relative_to(root.resolve()).as_posix()
                except ValueError:
                    continue
                if rel_target not in resolved_targets:
                    resolved_targets.append(rel_target)

            if not resolved_targets:
                continue
            if alias in aliases:
                existing = set(aliases[alias])
                aliases[alias].extend(t for t in resolved_targets if t not in existing)
            else:
                aliases[alias] = resolved_targets

    return aliases


def _resolve_tsconfig_paths(
    tsconfig_path: Path,
    project_root: Path,
    _seen: set[str] | None = None,
) -> tuple[dict[str, list[str]], Path]:
    """Resolve compilerOptions.paths from a tsconfig, following extends chains.

    Args:
        tsconfig_path: Absolute path to the tsconfig file.
        project_root: Project root for resolving relative paths.
        _seen: Guard against circular extends.

    Returns:
        Tuple of (paths dict, resolved baseUrl directory).
    """
    if _seen is None:
        _seen = set()

    canonical = str(tsconfig_path.resolve())
    if canonical in _seen:
        return {}, tsconfig_path.parent

    _seen.add(canonical)

    try:
        raw = tsconfig_path.read_text(encoding="utf-8", errors="ignore")
        # Strip single-line comments (tsconfig allows them).
        raw = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
        # Strip trailing commas before } or ].
        raw = re.sub(r",\s*([}\]])", r"\1", raw)
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}, tsconfig_path.parent

    # Follow extends chain first to get base paths.
    parent_paths: dict[str, list[str]] = {}
    parent_base_url = tsconfig_path.parent
    extends = data.get("extends")
    if extends:
        if isinstance(extends, str):
            extends = [extends]
        for ext in extends:
            ext_path = (tsconfig_path.parent / ext).resolve()
            # If extends points to a directory, try tsconfig.json inside it.
            if ext_path.is_dir():
                ext_path = ext_path / "tsconfig.json"
            elif not ext_path.suffix:
                ext_path = ext_path.with_suffix(".json")
            if ext_path.exists():
                parent_paths, parent_base_url = _resolve_tsconfig_paths(ext_path, project_root, _seen)

    # This config's compilerOptions override parent.
    compiler_options = data.get("compilerOptions", {})

    base_url_str = compiler_options.get("baseUrl")
    if base_url_str:
        base_url = (tsconfig_path.parent / base_url_str).resolve()
    else:
        base_url = parent_base_url

    paths = compiler_options.get("paths")
    if paths is not None:
        # This config's paths completely override parent paths.
        return paths, base_url

    if parent_paths:
        return parent_paths, base_url

    return {}, base_url
