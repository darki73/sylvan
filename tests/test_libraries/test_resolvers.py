"""Tests for package resolvers, package registry, and URL overrides.

Covers:
- sylvan.libraries.resolution.package_resolvers (resolve_pypi, resolve_npm, resolve_cargo, resolve_go)
- sylvan.libraries.resolution.package_registry (parse_package_spec, validate_repo_url, guess_tag, resolve)
- sylvan.libraries.resolution.url_overrides (load_overrides, save_override, remove_override)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sylvan.libraries.resolution.package_registry import (
    PackageInfo,
    guess_tag,
    parse_package_spec,
    resolve,
    validate_repo_url,
)

# ---------------------------------------------------------------------------
# parse_package_spec
# ---------------------------------------------------------------------------


class TestParsePackageSpec:
    def test_pip_with_version(self):
        manager, name, version = parse_package_spec("pip/django@4.2")
        assert manager == "pip"
        assert name == "django"
        assert version == "4.2"

    def test_npm_without_version(self):
        manager, name, version = parse_package_spec("npm/react")
        assert manager == "npm"
        assert name == "react"
        assert version == "latest"

    def test_go_module_with_version(self):
        manager, name, version = parse_package_spec("go/github.com/gin-gonic/gin@v1.9.1")
        assert manager == "go"
        assert name == "github.com/gin-gonic/gin"
        assert version == "v1.9.1"

    def test_go_module_without_version(self):
        manager, name, version = parse_package_spec("go/github.com/gin-gonic/gin")
        assert manager == "go"
        assert name == "github.com/gin-gonic/gin"
        assert version == "latest"

    def test_cargo_with_version(self):
        manager, name, version = parse_package_spec("cargo/serde@1.0.193")
        assert manager == "cargo"
        assert name == "serde"
        assert version == "1.0.193"

    def test_manager_case_normalized(self):
        manager, _name, _version = parse_package_spec("PIP/Django@4.2")
        assert manager == "pip"

    def test_no_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid package spec"):
            parse_package_spec("django")


# ---------------------------------------------------------------------------
# validate_repo_url
# ---------------------------------------------------------------------------


class TestValidateRepoUrl:
    def test_valid_https(self):
        url = "https://github.com/django/django"
        assert validate_repo_url(url) == url

    def test_valid_http(self):
        url = "http://github.com/django/django"
        assert validate_repo_url(url) == url

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_repo_url("ftp://github.com/django/django")

    def test_private_ip_raises(self):
        with pytest.raises(ValueError, match="private"):
            validate_repo_url("http://192.168.1.1/repo")

    def test_loopback_ip_raises(self):
        with pytest.raises(ValueError, match="loopback"):
            validate_repo_url("http://127.0.0.1/repo")

    def test_hostname_is_fine(self):
        url = "https://gitlab.com/org/repo"
        assert validate_repo_url(url) == url


# ---------------------------------------------------------------------------
# guess_tag
# ---------------------------------------------------------------------------


class TestGuessTag:
    def test_returns_version(self):
        assert guess_tag("1.2.3", "https://github.com/org/repo") == "1.2.3"

    def test_returns_v_prefixed(self):
        assert guess_tag("v1.2.3", "https://github.com/org/repo") == "v1.2.3"


# ---------------------------------------------------------------------------
# resolve (with overrides and dispatch)
# ---------------------------------------------------------------------------


class TestResolve:
    def test_unknown_manager_raises(self):
        with (
            patch(
                "sylvan.libraries.resolution.package_registry.load_overrides",
                return_value={},
            ),
            pytest.raises(ValueError, match="Unknown package manager"),
        ):
            resolve("maven", "junit", "5.0")

    def test_uses_override_when_present(self):
        with patch(
            "sylvan.libraries.resolution.package_registry.load_overrides",
            return_value={"pip/tiktoken": "https://github.com/openai/tiktoken"},
        ):
            info = resolve("pip", "tiktoken", "0.5.0")
            assert info.repo_url == "https://github.com/openai/tiktoken"
            assert info.version == "0.5.0"
            assert info.manager == "pip"

    def test_override_with_latest_resolves_version(self):
        with (
            patch(
                "sylvan.libraries.resolution.package_registry.load_overrides",
                return_value={"pip/tiktoken": "https://github.com/openai/tiktoken"},
            ),
            patch(
                "sylvan.libraries.resolution.package_registry._resolve_version_only",
                return_value="0.7.0",
            ),
        ):
            info = resolve("pip", "tiktoken", "latest")
            assert info.version == "0.7.0"

    def test_delegates_to_resolver(self):
        mock_info = PackageInfo(
            name="django",
            version="4.2",
            repo_url="https://github.com/django/django",
            tag="4.2",
            manager="pip",
        )
        with (
            patch(
                "sylvan.libraries.resolution.package_registry.load_overrides",
                return_value={},
            ),
            patch(
                "sylvan.libraries.resolution.package_resolvers.RESOLVERS",
                {"pip": MagicMock(return_value=mock_info)},
            ),
        ):
            info = resolve("pip", "django", "4.2")
            assert info.name == "django"


# ---------------------------------------------------------------------------
# resolve_pypi
# ---------------------------------------------------------------------------


class TestResolvePyPI:
    def test_success(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_pypi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "info": {
                "version": "4.2.7",
                "project_urls": {
                    "Source": "https://github.com/django/django",
                },
                "home_page": "",
            }
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_pypi("django", "4.2")

        assert info.name == "django"
        assert info.version == "4.2.7"
        assert info.repo_url == "https://github.com/django/django"
        assert info.manager == "pip"

    def test_latest_version_url(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_pypi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "info": {
                "version": "5.0.1",
                "project_urls": {
                    "Source": "https://github.com/django/django",
                },
                "home_page": "",
            }
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response) as mock_get:
            resolve_pypi("django", "latest")
            mock_get.assert_called_once()
            call_url = mock_get.call_args[0][0]
            assert call_url == "https://pypi.org/pypi/django/json"

    def test_no_repo_url_raises(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_pypi

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "info": {
                "version": "1.0.0",
                "project_urls": {},
                "home_page": "",
            }
        }

        with (
            patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response),
            pytest.raises(ValueError, match="Cannot find source repository"),
        ):
            resolve_pypi("obscure-pkg", "latest")

    def test_http_error_propagates(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_pypi

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with (
            patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response),
            pytest.raises(Exception, match="404"),
        ):
            resolve_pypi("nonexistent", "latest")

    def test_extracts_from_homepage(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_pypi

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "info": {
                "version": "2.0.0",
                "project_urls": None,
                "home_page": "https://github.com/org/repo",
            }
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_pypi("mypkg", "latest")
            assert info.repo_url == "https://github.com/org/repo"


# ---------------------------------------------------------------------------
# resolve_npm
# ---------------------------------------------------------------------------


class TestResolveNpm:
    def test_success(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_npm

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "version": "18.2.0",
            "repository": {"type": "git", "url": "git+https://github.com/facebook/react.git"},
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_npm("react", "latest")

        assert info.name == "react"
        assert info.version == "18.2.0"
        assert info.repo_url == "https://github.com/facebook/react"
        assert info.tag == "v18.2.0"
        assert info.manager == "npm"

    def test_repository_as_string(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_npm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "version": "1.0.0",
            "repository": "https://github.com/org/repo",
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_npm("mypkg", "1.0.0")
            assert info.repo_url == "https://github.com/org/repo"

    def test_no_repo_url_raises(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_npm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "version": "1.0.0",
            "repository": {},
        }

        with (
            patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response),
            pytest.raises(ValueError, match="Cannot find source repository"),
        ):
            resolve_npm("no-repo", "latest")

    def test_strips_git_prefix(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_npm

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "version": "1.0.0",
            "repository": {"url": "git://github.com/org/repo.git"},
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_npm("mypkg", "1.0.0")
            assert info.repo_url == "https://github.com/org/repo"


# ---------------------------------------------------------------------------
# resolve_cargo
# ---------------------------------------------------------------------------


class TestResolveCargo:
    def test_success_latest(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_cargo

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "crate": {
                "repository": "https://github.com/serde-rs/serde",
                "max_version": "1.0.193",
            }
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_cargo("serde", "latest")

        assert info.name == "serde"
        assert info.version == "1.0.193"
        assert info.repo_url == "https://github.com/serde-rs/serde"
        assert info.manager == "cargo"

    def test_specific_version(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_cargo

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "crate": {
                "repository": "https://github.com/serde-rs/serde",
                "max_version": "1.0.193",
            }
        }

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_cargo("serde", "1.0.100")
            assert info.version == "1.0.100"

    def test_no_repo_raises(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_cargo

        mock_response = MagicMock()
        mock_response.json.return_value = {"crate": {"repository": ""}}

        with (
            patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response),
            pytest.raises(ValueError, match="Cannot find source repository"),
        ):
            resolve_cargo("no-repo", "latest")


# ---------------------------------------------------------------------------
# resolve_go
# ---------------------------------------------------------------------------


class TestResolveGo:
    def test_github_module(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"Version": "v1.9.1"}

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", return_value=mock_response):
            info = resolve_go("github.com/gin-gonic/gin", "latest")

        assert info.name == "github.com/gin-gonic/gin"
        assert info.version == "v1.9.1"
        assert info.repo_url == "https://github.com/gin-gonic/gin"
        assert info.tag == "v1.9.1"
        assert info.manager == "go"

    def test_gitlab_module(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", side_effect=Exception("no proxy")):
            info = resolve_go("gitlab.com/org/repo", "v2.0.0")

        assert info.repo_url == "https://gitlab.com/org/repo"
        assert info.version == "v2.0.0"

    def test_specific_version_no_proxy_call(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        info = resolve_go("github.com/gin-gonic/gin", "v1.9.1")
        assert info.version == "v1.9.1"
        assert info.tag == "v1.9.1"

    def test_version_without_v_prefix_gets_prefixed(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        info = resolve_go("github.com/org/repo", "1.0.0")
        assert info.tag == "v1.0.0"

    def test_proxy_failure_keeps_latest(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        with patch("sylvan.libraries.resolution.package_resolvers.httpx.get", side_effect=Exception("timeout")):
            info = resolve_go("github.com/org/repo", "latest")

        assert info.version == "latest"

    def test_short_github_path(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        info = resolve_go("github.com/org", "v1.0.0")
        assert info.repo_url == "https://github.com/org"

    def test_generic_module(self):
        from sylvan.libraries.resolution.package_resolvers import resolve_go

        info = resolve_go("example.com/mymodule", "v1.0.0")
        assert info.repo_url == "https://example.com/mymodule"


# ---------------------------------------------------------------------------
# _extract_repo_url / _clean_repo_url (internal helpers via resolve_pypi)
# ---------------------------------------------------------------------------


class TestExtractRepoUrl:
    def test_source_key(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {"project_urls": {"Source": "https://github.com/org/repo"}, "home_page": ""}
        assert _extract_repo_url(info) == "https://github.com/org/repo"

    def test_source_code_key(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {"project_urls": {"Source Code": "https://github.com/org/repo"}, "home_page": ""}
        assert _extract_repo_url(info) == "https://github.com/org/repo"

    def test_homepage_fallback(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {"project_urls": {}, "home_page": "https://github.com/org/repo"}
        assert _extract_repo_url(info) == "https://github.com/org/repo"

    def test_no_urls_returns_empty(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {"project_urls": {}, "home_page": ""}
        assert _extract_repo_url(info) == ""

    def test_none_project_urls(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {"project_urls": None, "home_page": ""}
        assert _extract_repo_url(info) == ""

    def test_strips_fragment_and_deep_path(self):
        from sylvan.libraries.resolution.package_resolvers import _clean_repo_url

        url = "https://github.com/org/repo/blob/main/README.md#section"
        assert _clean_repo_url(url) == "https://github.com/org/repo"

    def test_non_github_returns_empty(self):
        from sylvan.libraries.resolution.package_resolvers import _clean_repo_url

        assert _clean_repo_url("https://example.com/repo") == ""

    def test_empty_input(self):
        from sylvan.libraries.resolution.package_resolvers import _clean_repo_url

        assert _clean_repo_url("") == ""

    def test_gitlab_url(self):
        from sylvan.libraries.resolution.package_resolvers import _clean_repo_url

        assert _clean_repo_url("https://gitlab.com/org/repo/issues") == "https://gitlab.com/org/repo"

    def test_fallback_to_any_url_value(self):
        from sylvan.libraries.resolution.package_resolvers import _extract_repo_url

        info = {
            "project_urls": {"Documentation": "https://github.com/org/repo/wiki"},
            "home_page": "",
        }
        assert _extract_repo_url(info) == "https://github.com/org/repo"


# ---------------------------------------------------------------------------
# RESOLVERS registry
# ---------------------------------------------------------------------------


class TestResolversRegistry:
    def test_all_resolvers_registered(self):
        from sylvan.libraries.resolution.package_resolvers import RESOLVERS

        assert "pip" in RESOLVERS
        assert "npm" in RESOLVERS
        assert "cargo" in RESOLVERS
        assert "go" in RESOLVERS


# ---------------------------------------------------------------------------
# url_overrides
# ---------------------------------------------------------------------------


class TestUrlOverrides:
    def test_load_overrides(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config

        reset_config()

        try:
            from sylvan.libraries.resolution.url_overrides import load_overrides

            result = load_overrides()
            assert isinstance(result, dict)
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_save_and_load_override(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config

        reset_config()

        try:
            from sylvan.libraries.resolution.url_overrides import (
                load_overrides,
                save_override,
            )

            save_override("pip/tiktoken", "https://github.com/openai/tiktoken")
            overrides = load_overrides()
            assert overrides["pip/tiktoken"] == "https://github.com/openai/tiktoken"
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_remove_override(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config

        reset_config()

        try:
            from sylvan.libraries.resolution.url_overrides import (
                load_overrides,
                remove_override,
                save_override,
            )

            save_override("pip/test", "https://github.com/org/test")
            assert remove_override("pip/test") is True
            assert "pip/test" not in load_overrides()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_remove_nonexistent_override(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config

        reset_config()

        try:
            from sylvan.libraries.resolution.url_overrides import remove_override

            assert remove_override("pip/nonexistent") is False
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_list_overrides_same_as_load(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config

        reset_config()

        try:
            from sylvan.libraries.resolution.url_overrides import (
                list_overrides,
                load_overrides,
            )

            assert list_overrides() == load_overrides()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()
