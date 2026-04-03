"""Tests for dependency file parsers — no git needed, just temp files."""

from __future__ import annotations

import json

from sylvan.git.dependency_files import (
    _parse_cargo_toml,
    _parse_go_mod,
    _parse_package_json,
    _parse_requirements_txt,
    parse_composer_autoload,
    parse_dependencies,
    parse_tsconfig_aliases,
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


class TestParseComposerAutoload:
    def test_psr4_mappings(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps(
                {
                    "autoload": {"psr-4": {"App\\": "app/"}},
                    "autoload-dev": {"psr-4": {"Tests\\": "tests/"}},
                }
            ),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert result == {"App\\": ["app/"], "Tests\\": ["tests/"]}

    def test_multiple_prefixes(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps(
                {
                    "autoload": {
                        "psr-4": {
                            "App\\": "app/",
                            "Database\\Factories\\": "database/factories/",
                            "Database\\Seeders\\": "database/seeders/",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert "App\\" in result
        assert "Database\\Factories\\" in result
        assert "Database\\Seeders\\" in result

    def test_array_directories(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps(
                {
                    "autoload": {"psr-4": {"App\\": ["app/", "src/"]}},
                }
            ),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert result == {"App\\": ["app/", "src/"]}

    def test_missing_composer_json(self, tmp_path):
        assert parse_composer_autoload(tmp_path) == {}

    def test_no_autoload_section(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"name": "test/pkg", "require": {"php": ">=8.1"}}),
            encoding="utf-8",
        )
        assert parse_composer_autoload(tmp_path) == {}

    def test_invalid_json(self, tmp_path):
        (tmp_path / "composer.json").write_text("not json {{{", encoding="utf-8")
        assert parse_composer_autoload(tmp_path) == {}

    def test_normalizes_trailing_slash(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"autoload": {"psr-4": {"App\\": "app"}}}),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert result["App\\"] == ["app/"]

    def test_normalizes_trailing_backslash(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"autoload": {"psr-4": {"App": "app/"}}}),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert "App\\" in result

    def test_merges_autoload_and_dev(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps(
                {
                    "autoload": {"psr-4": {"App\\": "app/"}},
                    "autoload-dev": {"psr-4": {"App\\": "tests/app/"}},
                }
            ),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert "app/" in result["App\\"]
        assert "tests/app/" in result["App\\"]

    def test_psr0_mappings(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"autoload": {"psr-0": {"Legacy\\": "lib/"}}}),
            encoding="utf-8",
        )
        result = parse_composer_autoload(tmp_path)
        assert result == {"Legacy\\": ["lib/"]}


class TestParseTsconfigAliases:
    def test_simple_at_alias(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {"@/*": ["./src/*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"@": ["src"]}

    def test_multiple_aliases(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {
                            "@/*": ["./resources/js/*"],
                            "ziggy-js": ["./vendor/tightenco/ziggy"],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result["@"] == ["resources/js"]
        assert result["ziggy-js"] == ["vendor/tightenco/ziggy"]

    def test_baseurl_respected(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "baseUrl": "./src",
                        "paths": {"@/*": ["./*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"@": ["src"]}

    def test_extends_chain(self, tmp_path):
        (tmp_path / "tsconfig.base.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {"@/*": ["./src/*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"extends": "./tsconfig.base.json"}),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"@": ["src"]}

    def test_child_overrides_parent_paths(self, tmp_path):
        (tmp_path / "tsconfig.base.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {"@/*": ["./old/*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "extends": "./tsconfig.base.json",
                    "compilerOptions": {
                        "paths": {"@/*": ["./new/*"]},
                    },
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"@": ["new"]}

    def test_nested_tsconfig_with_baseurl(self, tmp_path):
        """Simulates a packages/ subdir tsconfig like the gaes project."""
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {"@/*": ["./resources/js/*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        pkg_dir = tmp_path / "app" / "Packages"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "tsconfig.json").write_text(
            json.dumps(
                {
                    "extends": "../../tsconfig.json",
                    "compilerOptions": {
                        "baseUrl": "../../",
                        "paths": {"@/*": ["./resources/js/*"]},
                    },
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        # Both tsconfigs resolve @ to the same path.
        assert result == {"@": ["resources/js"]}

    def test_missing_tsconfig(self, tmp_path):
        assert parse_tsconfig_aliases(tmp_path) == {}

    def test_no_paths_section(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"strict": True}}),
            encoding="utf-8",
        )
        assert parse_tsconfig_aliases(tmp_path) == {}

    def test_sveltekit_lib_alias(self, tmp_path):
        (tmp_path / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "paths": {"$lib/*": ["./src/lib/*"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"$lib": ["src/lib"]}

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "some-pkg"
        nm.mkdir(parents=True)
        (nm / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {"paths": {"bad/*": ["./bad/*"]}},
                }
            ),
            encoding="utf-8",
        )
        assert parse_tsconfig_aliases(tmp_path) == {}

    def test_comments_in_tsconfig(self, tmp_path):
        """tsconfig allows JS-style comments and trailing commas."""
        (tmp_path / "tsconfig.json").write_text(
            "{\n"
            "  // This is a comment\n"
            '  "compilerOptions": {\n'
            '    "paths": {\n'
            '      "@/*": ["./src/*"],  // inline comment\n'
            "    },\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        result = parse_tsconfig_aliases(tmp_path)
        assert result == {"@": ["src"]}
