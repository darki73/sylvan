"""Tests for dependency file parsers — no git needed, just temp files."""

from __future__ import annotations

import json

from sylvan.git.dependency_files import (
    _parse_cargo_toml,
    _parse_go_mod,
    _parse_package_json,
    _parse_requirements_txt,
    parse_dependencies,
)


class TestParseRequirementsTxt:
    def test_simple_requirements(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.28\nflask==2.3.0\nnumpy\n", encoding="utf-8")
        deps = _parse_requirements_txt(req)
        names = [d["name"] for d in deps]
        assert "requests" in names
        assert "flask" in names
        assert "numpy" in names
        assert all(d["manager"] == "pip" for d in deps)

    def test_version_specifiers(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.28\nflask==2.3.0\nnumpy\n", encoding="utf-8")
        deps = _parse_requirements_txt(req)
        versions = {d["name"]: d["version"] for d in deps}
        assert ">=2.28" in versions["requests"]
        assert "==2.3.0" in versions["flask"]
        assert versions["numpy"] == ""

    def test_comments_ignored(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("# This is a comment\nrequests\n", encoding="utf-8")
        deps = _parse_requirements_txt(req)
        assert len(deps) == 1
        assert deps[0]["name"] == "requests"

    def test_flags_ignored(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("-r other.txt\n--index-url https://x\nrequests\n", encoding="utf-8")
        deps = _parse_requirements_txt(req)
        assert len(deps) == 1
        assert deps[0]["name"] == "requests"

    def test_empty_file(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("", encoding="utf-8")
        deps = _parse_requirements_txt(req)
        assert deps == []

    def test_missing_file(self, tmp_path):
        req = tmp_path / "nonexistent.txt"
        deps = _parse_requirements_txt(req)
        assert deps == []


class TestParsePackageJson:
    def test_dependencies(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(
            json.dumps(
                {
                    "dependencies": {"react": "^18.0.0", "lodash": "4.17.21"},
                }
            ),
            encoding="utf-8",
        )
        deps = _parse_package_json(pkg)
        assert len(deps) == 2
        names = {d["name"] for d in deps}
        assert "react" in names
        assert "lodash" in names
        assert all(d["manager"] == "npm" for d in deps)

    def test_dev_dependencies(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(
            json.dumps(
                {
                    "devDependencies": {"jest": "^29.0"},
                }
            ),
            encoding="utf-8",
        )
        deps = _parse_package_json(pkg)
        assert len(deps) == 1
        assert deps[0]["name"] == "jest"

    def test_both_dep_types(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(
            json.dumps(
                {
                    "dependencies": {"express": "^4.18"},
                    "devDependencies": {"nodemon": "^3.0"},
                }
            ),
            encoding="utf-8",
        )
        deps = _parse_package_json(pkg)
        assert len(deps) == 2

    def test_no_dependencies(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"name": "test"}), encoding="utf-8")
        deps = _parse_package_json(pkg)
        assert deps == []

    def test_invalid_json(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text("not json", encoding="utf-8")
        deps = _parse_package_json(pkg)
        assert deps == []

    def test_missing_file(self, tmp_path):
        pkg = tmp_path / "nonexistent.json"
        deps = _parse_package_json(pkg)
        assert deps == []


class TestParseGoMod:
    def test_require_block(self, tmp_path):
        gomod = tmp_path / "go.mod"
        gomod.write_text(
            "module example.com/myapp\n\n"
            "go 1.21\n\n"
            "require (\n"
            "\tgithub.com/gin-gonic/gin v1.9.1\n"
            "\tgithub.com/lib/pq v1.10.9\n"
            ")\n",
            encoding="utf-8",
        )
        deps = _parse_go_mod(gomod)
        assert len(deps) == 2
        names = [d["name"] for d in deps]
        assert "github.com/gin-gonic/gin" in names
        assert "github.com/lib/pq" in names
        assert all(d["manager"] == "go" for d in deps)

    def test_single_line_require(self, tmp_path):
        gomod = tmp_path / "go.mod"
        gomod.write_text(
            "module example.com/app\n\nrequire github.com/pkg/errors v0.9.1\n",
            encoding="utf-8",
        )
        deps = _parse_go_mod(gomod)
        assert len(deps) == 1
        assert deps[0]["name"] == "github.com/pkg/errors"
        assert deps[0]["version"] == "v0.9.1"

    def test_empty_go_mod(self, tmp_path):
        gomod = tmp_path / "go.mod"
        gomod.write_text("module example.com/app\n", encoding="utf-8")
        deps = _parse_go_mod(gomod)
        assert deps == []

    def test_missing_file(self, tmp_path):
        gomod = tmp_path / "go.mod"
        deps = _parse_go_mod(gomod)
        assert deps == []

    def test_versions_captured(self, tmp_path):
        gomod = tmp_path / "go.mod"
        gomod.write_text(
            "module test\n\nrequire (\n\texample.com/foo v1.2.3\n)\n",
            encoding="utf-8",
        )
        deps = _parse_go_mod(gomod)
        assert deps[0]["version"] == "v1.2.3"


class TestParseCargoToml:
    def test_dependencies(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1.0"\ntokio = "1.28"\n',
            encoding="utf-8",
        )
        deps = _parse_cargo_toml(cargo)
        assert len(deps) == 2
        names = {d["name"] for d in deps}
        assert "serde" in names
        assert "tokio" in names
        assert all(d["manager"] == "cargo" for d in deps)

    def test_versions_captured(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[dependencies]\nserde = "1.0"\n',
            encoding="utf-8",
        )
        deps = _parse_cargo_toml(cargo)
        assert deps[0]["version"] == "1.0"

    def test_no_dependencies_section(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[package]\nname = "myapp"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        deps = _parse_cargo_toml(cargo)
        assert deps == []

    def test_stops_at_next_section(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[dependencies]\nserde = "1.0"\n\n[dev-dependencies]\ncriterion = "0.5"\n',
            encoding="utf-8",
        )
        deps = _parse_cargo_toml(cargo)
        assert len(deps) == 1
        assert deps[0]["name"] == "serde"

    def test_missing_file(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        deps = _parse_cargo_toml(cargo)
        assert deps == []

    def test_empty_file(self, tmp_path):
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("", encoding="utf-8")
        deps = _parse_cargo_toml(cargo)
        assert deps == []


class TestParseDependencies:
    def test_detects_requirements_txt(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests\n", encoding="utf-8")
        deps = parse_dependencies(tmp_path)
        assert any(d["name"] == "requests" for d in deps)

    def test_detects_package_json(self, tmp_path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"dependencies": {"express": "^4"}}), encoding="utf-8")
        deps = parse_dependencies(tmp_path)
        assert any(d["name"] == "express" for d in deps)

    def test_empty_directory(self, tmp_path):
        deps = parse_dependencies(tmp_path)
        assert deps == []

    def test_multiple_manifests(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask\n", encoding="utf-8")
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"dependencies": {"react": "^18"}}), encoding="utf-8")
        deps = parse_dependencies(tmp_path)
        managers = {d["manager"] for d in deps}
        assert "pip" in managers
        assert "npm" in managers
