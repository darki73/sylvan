"""Dependency file parsing -- requirements.txt, package.json, etc."""

import json
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
