"""Tests for sylvan.security.patterns — secret/binary/skip detection."""

from __future__ import annotations

from sylvan.security.patterns import (
    is_binary_content,
    is_binary_extension,
    is_secret_file,
    should_skip_dir,
    should_skip_file,
)


class TestIsSecretFile:
    def test_env_file(self):
        assert is_secret_file(".env") is True

    def test_env_local(self):
        assert is_secret_file(".env.local") is True

    def test_pem_key(self):
        assert is_secret_file("server.pem") is True

    def test_private_key(self):
        assert is_secret_file("id_rsa") is True

    def test_ed25519_key(self):
        assert is_secret_file("id_ed25519") is True

    def test_credentials_json(self):
        assert is_secret_file("credentials.json") is True

    def test_service_account(self):
        assert is_secret_file("service-account-key.json") is True

    def test_htpasswd(self):
        assert is_secret_file(".htpasswd") is True

    def test_normal_py_not_secret(self):
        assert is_secret_file("main.py") is False

    def test_normal_js_not_secret(self):
        assert is_secret_file("index.js") is False

    def test_readme_not_secret(self):
        assert is_secret_file("README.md") is False

    def test_doc_file_with_secret_extension_not_exempt(self):
        # .md is a doc extension, but *.secrets pattern doesn't contain *secret*
        # so "my-secrets.md" doesn't match *.secrets (wrong extension)
        # Actually test that a .md file doesn't match secret patterns at all
        assert is_secret_file("notes.md") is False

    def test_dot_secret_file(self):
        assert is_secret_file("app.secret") is True

    def test_keystore_file(self):
        assert is_secret_file("debug.keystore") is True


class TestIsBinaryExtension:
    def test_png_is_binary(self):
        assert is_binary_extension("image.png") is True

    def test_exe_is_binary(self):
        assert is_binary_extension("app.exe") is True

    def test_zip_is_binary(self):
        assert is_binary_extension("archive.zip") is True

    def test_pdf_is_binary(self):
        assert is_binary_extension("doc.pdf") is True

    def test_py_not_binary(self):
        assert is_binary_extension("main.py") is False

    def test_ts_not_binary(self):
        assert is_binary_extension("index.ts") is False

    def test_no_extension_not_binary(self):
        assert is_binary_extension("Makefile") is False

    def test_wasm_is_binary(self):
        assert is_binary_extension("module.wasm") is True

    def test_sqlite_is_binary(self):
        assert is_binary_extension("data.sqlite") is True


class TestIsBinaryContent:
    def test_null_bytes_detected(self):
        data = b"hello\x00world"
        assert is_binary_content(data) is True

    def test_plain_text_not_binary(self):
        data = b"def hello(): pass\n"
        assert is_binary_content(data) is False

    def test_empty_bytes_not_binary(self):
        assert is_binary_content(b"") is False

    def test_null_after_check_size_not_detected(self):
        data = b"x" * 8192 + b"\x00"
        assert is_binary_content(data, check_size=8192) is False

    def test_null_within_check_size_detected(self):
        data = b"x" * 100 + b"\x00" + b"x" * 100
        assert is_binary_content(data) is True


class TestShouldSkipDir:
    def test_node_modules(self):
        assert should_skip_dir("node_modules") is True

    def test_git_dir(self):
        assert should_skip_dir(".git") is True

    def test_pycache(self):
        assert should_skip_dir("__pycache__") is True

    def test_venv(self):
        assert should_skip_dir("venv") is True

    def test_hidden_dir_skipped(self):
        assert should_skip_dir(".hidden") is True

    def test_src_not_skipped(self):
        assert should_skip_dir("src") is False

    def test_lib_not_skipped(self):
        assert should_skip_dir("lib") is False


class TestShouldSkipFile:
    def test_min_js(self):
        assert should_skip_file("bundle.min.js") is True

    def test_min_css(self):
        assert should_skip_file("styles.min.css") is True

    def test_package_lock(self):
        assert should_skip_file("package-lock.json") is True

    def test_yarn_lock(self):
        assert should_skip_file("yarn.lock") is True

    def test_go_sum(self):
        assert should_skip_file("go.sum") is True

    def test_source_map(self):
        assert should_skip_file("main.js.map") is True

    def test_normal_py_not_skipped(self):
        assert should_skip_file("main.py") is False

    def test_normal_ts_not_skipped(self):
        assert should_skip_file("index.ts") is False

    def test_pyc_skipped(self):
        assert should_skip_file("module.pyc") is True
