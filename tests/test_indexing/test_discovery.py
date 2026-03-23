"""Tests for sylvan.indexing.discovery.file_discovery — file discovery with filtering."""

from __future__ import annotations

from sylvan.indexing.discovery.file_discovery import discover_files


class TestDiscoverFiles:
    def test_discovers_python_file(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')\n")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "main.py" in paths

    def test_skips_binary_extension(self, tmp_path):
        (tmp_path / "code.py").write_text("pass\n")
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n" + b"x" * 100)
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "code.py" in paths
        assert "image.png" not in paths

    def test_skips_secret_file(self, tmp_path):
        (tmp_path / "app.py").write_text("pass\n")
        (tmp_path / ".env").write_text("SECRET=123\n")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "app.py" in paths
        assert ".env" not in paths

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "index.js").write_text("module.exports = {}\n")
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("exports.foo = 1;\n")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "index.js" in paths
        assert not any("node_modules" in p for p in paths)

    def test_skips_pycache(self, tmp_path):
        (tmp_path / "app.py").write_text("pass\n")
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "app.cpython-311.pyc").write_bytes(b"\x00\x00\x00\x00")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert not any("__pycache__" in p for p in paths)

    def test_respects_gitignore(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        (tmp_path / "app.py").write_text("pass\n")
        (tmp_path / "debug.log").write_text("log stuff\n")
        build = tmp_path / "build"
        build.mkdir()
        (build / "output.js").write_text("compiled\n")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "app.py" in paths
        assert "debug.log" not in paths
        assert not any("build" in p for p in paths)

    def test_max_files_limit(self, tmp_path):
        for i in range(10):
            (tmp_path / f"file{i}.py").write_text(f"x = {i}\n")
        result = discover_files(tmp_path, max_files=3, use_git=False)
        assert result.total_found == 3
        assert result.total_skipped > 0

    def test_total_found_and_skipped_counts(self, tmp_path):
        (tmp_path / "good.py").write_text("pass\n")
        (tmp_path / "bad.png").write_bytes(b"\x89PNG" + b"x" * 50)
        result = discover_files(tmp_path, use_git=False)
        assert result.total_found >= 1
        assert result.total_skipped >= 1

    def test_skips_empty_files(self, tmp_path):
        (tmp_path / "empty.py").write_text("")
        (tmp_path / "notempty.py").write_text("x = 1\n")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "notempty.py" in paths
        assert "empty.py" not in paths

    def test_skips_minified_files(self, tmp_path):
        (tmp_path / "app.js").write_text("var x = 1;\n")
        (tmp_path / "app.min.js").write_text("var x=1;")
        result = discover_files(tmp_path, use_git=False)
        paths = [f.relative_path for f in result.files]
        assert "app.js" in paths
        assert "app.min.js" not in paths

    def test_discovered_file_has_attributes(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\n")
        result = discover_files(tmp_path, use_git=False)
        assert len(result.files) == 1
        df = result.files[0]
        assert df.relative_path == "test.py"
        assert df.size > 0
        assert df.mtime > 0
        assert df.path.exists()

    def test_skipped_reasons_tracked(self, tmp_path):
        (tmp_path / "ok.py").write_text("pass\n")
        (tmp_path / ".env").write_text("SECRET=abc\n")
        result = discover_files(tmp_path, use_git=False)
        assert "secret_file" in result.skipped
