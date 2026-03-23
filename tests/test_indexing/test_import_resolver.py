"""Tests for sylvan.indexing.pipeline.import_resolver — import-to-file resolution."""

from __future__ import annotations

from sylvan.indexing.pipeline.import_resolver import (
    _generate_candidates,
    resolve_imports,
)


class TestPythonCandidates:
    def test_dotted_specifier_resolves_to_py_file(self):
        candidates = _generate_candidates("sylvan.search.embeddings", "python", "src/main.py")
        assert "src/sylvan/search/embeddings.py" in candidates

    def test_dotted_specifier_resolves_to_init(self):
        candidates = _generate_candidates("sylvan.database.orm", "python", "src/main.py")
        assert "src/sylvan/database/orm/__init__.py" in candidates

    def test_bare_import_generates_namespace_candidates(self):
        candidates = _generate_candidates("json", "python", "src/main.py")
        assert "json/__init__.py" in candidates
        assert "json.py" in candidates
        assert "src/json/__init__.py" in candidates

    def test_bare_import_os_generates_namespace_candidates(self):
        candidates = _generate_candidates("os", "python", "src/main.py")
        assert "os/__init__.py" in candidates
        assert "os.py" in candidates

    def test_relative_single_dot(self):
        candidates = _generate_candidates(".utils", "python", "src/sylvan/search/main.py")
        assert "src/sylvan/search/utils.py" in candidates

    def test_relative_double_dot(self):
        candidates = _generate_candidates("..config", "python", "src/sylvan/search/main.py")
        assert "src/sylvan/config.py" in candidates

    def test_relative_dot_only(self):
        candidates = _generate_candidates(".", "python", "src/sylvan/search/main.py")
        assert "src/sylvan/search/__init__.py" in candidates

    def test_also_tries_without_src_prefix(self):
        candidates = _generate_candidates("sylvan.search.embeddings", "python", "src/main.py")
        assert "sylvan/search/embeddings.py" in candidates


class TestJsCandidates:
    def test_relative_import_without_extension(self):
        candidates = _generate_candidates("./utils", "javascript", "src/app.js")
        assert "src/utils.js" in candidates
        assert "src/utils.ts" in candidates

    def test_relative_import_with_extension(self):
        candidates = _generate_candidates("./utils.js", "javascript", "src/app.js")
        assert "src/utils.js" in candidates

    def test_index_file_candidates(self):
        candidates = _generate_candidates("./components", "typescript", "src/app.ts")
        assert "src/components/index.ts" in candidates
        assert "src/components/index.js" in candidates

    def test_bare_specifier_not_resolved(self):
        candidates = _generate_candidates("react", "javascript", "src/app.js")
        assert candidates == []

    def test_scoped_package_not_resolved(self):
        candidates = _generate_candidates("@angular/core", "typescript", "src/app.ts")
        assert candidates == []

    def test_parent_directory(self):
        candidates = _generate_candidates("../config", "javascript", "src/components/app.js")
        assert "src/config.js" in candidates

    def test_vue_file_import(self):
        candidates = _generate_candidates("./App.vue", "typescript", "src/main.ts")
        assert "src/App.vue" in candidates

    def test_tsx_extension(self):
        candidates = _generate_candidates("./Button", "tsx", "src/components/Form.tsx")
        assert "src/components/Button.tsx" in candidates


class TestGoCandidates:
    def test_stdlib_not_resolved(self):
        candidates = _generate_candidates("fmt", "go", "main.go")
        assert candidates == []

    def test_stdlib_nested_not_resolved(self):
        # Single-segment stdlib like "fmt" is skipped; multi-segment like
        # "net/http" has first segment in stdlib set.
        candidates = _generate_candidates("net/http", "go", "main.go")
        assert candidates == []

    def test_third_party_generates_suffix_candidates(self):
        candidates = _generate_candidates(
            "github.com/org/repo/pkg/util", "go", "main.go",
        )
        assert "pkg/util" in candidates
        assert "util" in candidates


class TestRustCandidates:
    def test_std_not_resolved(self):
        candidates = _generate_candidates("std::collections::HashMap", "rust", "src/main.rs")
        assert candidates == []

    def test_crate_specifier(self):
        candidates = _generate_candidates("crate::module::item", "rust", "src/main.rs")
        assert "src/module.rs" in candidates
        assert "src/module/mod.rs" in candidates

    def test_crate_single_segment(self):
        candidates = _generate_candidates("crate::config", "rust", "src/main.rs")
        assert "src/config.rs" in candidates


class TestJavaCandidates:
    def test_java_import(self):
        candidates = _generate_candidates("com.example.util", "java", "Main.java")
        assert "com/example/util.java" in candidates

    def test_kotlin_import(self):
        candidates = _generate_candidates("com.example.util", "kotlin", "Main.kt")
        assert "com/example/util.kt" in candidates

    def test_java_with_src_prefix(self):
        candidates = _generate_candidates("com.example.util", "java", "Main.java")
        assert "src/main/java/com/example/util.java" in candidates


class TestCCandidates:
    def test_system_header_not_resolved(self):
        candidates = _generate_candidates("stdio.h", "c", "src/main.c")
        assert candidates == []

    def test_quoted_include_relative(self):
        candidates = _generate_candidates("myheader.h", "c", "src/main.c")
        assert "src/myheader.h" in candidates

    def test_project_relative(self):
        candidates = _generate_candidates("utils/helpers.h", "cpp", "src/main.cpp")
        assert "utils/helpers.h" in candidates
        assert "include/utils/helpers.h" in candidates


class TestRubyCandidates:
    def test_relative_require(self):
        candidates = _generate_candidates("./lib/foo", "ruby", "app/main.rb")
        assert "app/lib/foo.rb" in candidates

    def test_absolute_style_require(self):
        candidates = _generate_candidates("models/user", "ruby", "app/main.rb")
        assert "models/user.rb" in candidates
        assert "lib/models/user.rb" in candidates


class TestPhpCandidates:
    def test_namespace_import(self):
        candidates = _generate_candidates("App\\Models\\User", "php", "index.php")
        assert "App/Models/User.php" in candidates


class TestCSharpCandidates:
    def test_namespace_import(self):
        candidates = _generate_candidates("MyApp.Models", "c_sharp", "Program.cs")
        assert "MyApp/Models.cs" in candidates


class TestUnknownLanguage:
    def test_returns_empty(self):
        candidates = _generate_candidates("something", "brainfuck", "main.bf")
        assert candidates == []


class TestMultipleCandidatesPicksFirst:
    def test_first_match_wins(self):
        """When multiple candidates could match, the first one is returned."""
        candidates = _generate_candidates("sylvan.search.embeddings", "python", "main.py")
        # Should have both .py and __init__.py, .py should come first.
        py_idx = next(i for i, c in enumerate(candidates) if c.endswith("embeddings.py"))
        init_idx = next(i for i, c in enumerate(candidates) if c.endswith("__init__.py"))
        assert py_idx < init_idx


class TestResolveImportsIntegration:
    async def test_resolves_python_imports(self, ctx):
        """Full integration: create files + imports, resolve, verify."""
        backend = ctx.backend

        # Create a repo.
        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
            ["test-repo", "/home/user/test-repo", "2025-01-01T00:00:00"],
        )
        repo_row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", ["test-repo"])
        repo_id = repo_row["id"]

        # Create files.
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/sylvan/search/embeddings.py", "python", "hash1", 100],
        )
        target_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/sylvan/search/embeddings.py"],
        )
        target_id = target_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/sylvan/cli.py", "python", "hash2", 200],
        )
        source_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/sylvan/cli.py"],
        )
        source_id = source_row["id"]

        # Create an unresolved import.
        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names, resolved_file_id) VALUES (?, ?, ?, ?)",
            [source_id, "sylvan.search.embeddings", '["embeddings"]', None],
        )
        await backend.commit()

        # Run resolution.
        resolved = await resolve_imports(repo_id)
        assert resolved == 1

        # Verify the resolved_file_id is set correctly.
        row = await backend.fetch_one(
            "SELECT resolved_file_id FROM file_imports WHERE file_id = ?", [source_id],
        )
        assert row["resolved_file_id"] == target_id

    async def test_does_not_resolve_stdlib(self, ctx):
        """Bare Python imports like 'json' should not resolve."""
        backend = ctx.backend

        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
            ["test-repo2", "/home/user/test-repo2", "2025-01-01T00:00:00"],
        )
        repo_row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", ["test-repo2"])
        repo_id = repo_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/main.py", "python", "hash3", 100],
        )
        source_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/main.py"],
        )
        source_id = source_row["id"]

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names, resolved_file_id) VALUES (?, ?, ?, ?)",
            [source_id, "json", '["loads"]', None],
        )
        await backend.commit()

        resolved = await resolve_imports(repo_id)
        assert resolved == 0

        row = await backend.fetch_one(
            "SELECT resolved_file_id FROM file_imports WHERE file_id = ?", [source_id],
        )
        assert row["resolved_file_id"] is None

    async def test_resolves_js_relative_import(self, ctx):
        """JS relative import ./utils resolves to the correct file."""
        backend = ctx.backend

        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
            ["js-repo", "/home/user/js-repo", "2025-01-01T00:00:00"],
        )
        repo_row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", ["js-repo"])
        repo_id = repo_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/utils.ts", "typescript", "hash4", 100],
        )
        target_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/utils.ts"],
        )
        target_id = target_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/app.ts", "typescript", "hash5", 200],
        )
        source_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/app.ts"],
        )
        source_id = source_row["id"]

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names, resolved_file_id) VALUES (?, ?, ?, ?)",
            [source_id, "./utils", '["doStuff"]', None],
        )
        await backend.commit()

        resolved = await resolve_imports(repo_id)
        assert resolved == 1

        row = await backend.fetch_one(
            "SELECT resolved_file_id FROM file_imports WHERE file_id = ?", [source_id],
        )
        assert row["resolved_file_id"] == target_id

    async def test_does_not_resolve_npm_package(self, ctx):
        """Bare JS specifiers like 'react' should not resolve."""
        backend = ctx.backend

        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
            ["js-repo2", "/home/user/js-repo2", "2025-01-01T00:00:00"],
        )
        repo_row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", ["js-repo2"])
        repo_id = repo_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/app.js", "javascript", "hash6", 100],
        )
        source_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/app.js"],
        )
        source_id = source_row["id"]

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names, resolved_file_id) VALUES (?, ?, ?, ?)",
            [source_id, "react", '["useState"]', None],
        )
        await backend.commit()

        resolved = await resolve_imports(repo_id)
        assert resolved == 0

    async def test_resolves_init_py(self, ctx):
        """Python dotted import resolves to __init__.py when .py doesn't exist."""
        backend = ctx.backend

        await backend.execute(
            "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
            ["init-repo", "/home/user/init-repo", "2025-01-01T00:00:00"],
        )
        repo_row = await backend.fetch_one("SELECT id FROM repos WHERE name = ?", ["init-repo"])
        repo_id = repo_row["id"]

        # Only __init__.py exists, not orm.py.
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/sylvan/database/orm/__init__.py", "python", "hash7", 100],
        )
        target_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?",
            ["src/sylvan/database/orm/__init__.py"],
        )
        target_id = target_row["id"]

        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) VALUES (?, ?, ?, ?, ?)",
            [repo_id, "src/sylvan/cli.py", "python", "hash8", 200],
        )
        source_row = await backend.fetch_one(
            "SELECT id FROM files WHERE path = ?", ["src/sylvan/cli.py"],
        )
        source_id = source_row["id"]

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names, resolved_file_id) VALUES (?, ?, ?, ?)",
            [source_id, "sylvan.database.orm", '["FileRecord"]', None],
        )
        await backend.commit()

        resolved = await resolve_imports(repo_id)
        assert resolved == 1

        row = await backend.fetch_one(
            "SELECT resolved_file_id FROM file_imports WHERE file_id = ?", [source_id],
        )
        assert row["resolved_file_id"] == target_id
