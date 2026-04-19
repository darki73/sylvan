"""Integration test for ``sylvan._rust.discover_files``.

Builds a small file tree in a tempdir, invokes the Rust discovery
function directly, and asserts the returned dict shape matches the
contract the Python proxy layer will consume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sylvan._rust import discover_files

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, rel: str, content: bytes) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def test_returns_expected_shape(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", b"x = 1\n")
    _write(tmp_path, "sub/b.py", b"y = 2\n")

    result = discover_files(str(tmp_path), 5000, 512_000, False)

    assert isinstance(result, dict)
    assert set(result.keys()) == {"files", "skipped", "git_head"}
    assert isinstance(result["files"], list)
    assert isinstance(result["skipped"], dict)
    assert result["git_head"] is None


def test_accepts_small_tree(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", b"x = 1\n")
    _write(tmp_path, "b.py", b"y = 2\n")
    _write(tmp_path, "sub/c.py", b"z = 3\n")

    result = discover_files(str(tmp_path), 5000, 512_000, False)

    rels = sorted(f["relative_path"] for f in result["files"])
    assert rels == ["a.py", "b.py", "sub/c.py"]
    for f in result["files"]:
        assert f["size"] > 0
        assert f["mtime"] > 0
        assert f["path"].endswith(f["relative_path"].replace("/", f["path"][-len(f["relative_path"]) - 1]))


def test_records_skip_reasons(tmp_path: Path) -> None:
    _write(tmp_path, "ok.py", b"x = 1\n")
    _write(tmp_path, "icon.png", b"\x89PNG")
    _write(tmp_path, ".env", b"SECRET=1\n")
    _write(tmp_path, "empty.py", b"")

    result = discover_files(str(tmp_path), 5000, 512_000, False)

    assert len(result["files"]) == 1
    assert len(result["skipped"].get("binary_extension", [])) == 1
    assert len(result["skipped"].get("secret_file", [])) == 1
    assert len(result["skipped"].get("empty", [])) == 1


def test_honors_default_parameters(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", b"x = 1\n")
    # The positional-only path plus keyword defaults must work.
    result = discover_files(str(tmp_path), use_git=False)
    assert len(result["files"]) == 1


def test_respects_max_files(tmp_path: Path) -> None:
    for i in range(5):
        _write(tmp_path, f"f{i}.py", b"x = 1\n")

    result = discover_files(str(tmp_path), 2, 512_000, False)

    assert len(result["files"]) == 2
    assert len(result["skipped"]["max_files_reached"]) == 3
