"""Tests for JSON deep extraction."""

from __future__ import annotations

import json

from sylvan.indexing.source_code.json_extractor import (
    extract_json_imports,
    extract_json_symbols,
)


def _pretty(data: dict) -> str:
    """Dump with indent so line numbers are meaningful."""
    return json.dumps(data, indent=2)


class TestPackageJson:
    def test_name_and_version(self):
        content = _pretty({"name": "my-app", "version": "1.0.0"})
        symbols = extract_json_symbols(content, "package.json")
        names = {s.name for s in symbols}
        assert "name" in names
        assert "version" in names

    def test_name_line_number(self):
        content = _pretty({"name": "my-app", "version": "1.0.0"})
        symbols = extract_json_symbols(content, "package.json")
        name_sym = next(s for s in symbols if s.name == "name")
        version_sym = next(s for s in symbols if s.name == "version")
        assert name_sym.line_start == 2
        assert version_sym.line_start == 3

    def test_scripts_as_functions(self):
        content = _pretty(
            {
                "name": "test",
                "scripts": {
                    "build": "tsc",
                    "dev": "vite",
                    "test": "vitest",
                    "lint": "eslint .",
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        script_syms = [s for s in symbols if s.kind == "function"]
        assert len(script_syms) == 4
        script_names = {s.name for s in script_syms}
        assert script_names == {"build", "dev", "test", "lint"}

    def test_scripts_line_numbers(self):
        content = _pretty(
            {
                "name": "test",
                "scripts": {
                    "build": "tsc",
                    "dev": "vite",
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        build_sym = next(s for s in symbols if s.name == "build")
        dev_sym = next(s for s in symbols if s.name == "dev")
        assert build_sym.line_start > 1
        assert dev_sym.line_start > build_sym.line_start

    def test_dependencies_as_constants(self):
        content = _pretty(
            {
                "name": "test",
                "dependencies": {
                    "react": "^18.0.0",
                    "react-dom": "^18.0.0",
                },
                "devDependencies": {
                    "typescript": "^5.0.0",
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        dep_syms = [s for s in symbols if "ependencies." in s.qualified_name.lower()]
        assert len(dep_syms) == 3
        react_sym = next(s for s in dep_syms if s.name == "react")
        assert "^18.0.0" in react_sym.signature

    def test_optional_dependencies(self):
        content = _pretty(
            {
                "name": "test",
                "optionalDependencies": {
                    "fsevents": "^2.3.0",
                    "cpu-features": "^0.0.4",
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        opt_syms = [s for s in symbols if "optionalDependencies." in s.qualified_name]
        assert len(opt_syms) == 2
        names = {s.name for s in opt_syms}
        assert names == {"fsevents", "cpu-features"}
        fsevents = next(s for s in opt_syms if s.name == "fsevents")
        assert "^2.3.0" in fsevents.signature

    def test_optional_dependencies_imports(self):
        content = _pretty(
            {
                "name": "test",
                "optionalDependencies": {"fsevents": "^2.3.0"},
            }
        )
        imports = extract_json_imports(content, "package.json")
        specifiers = {i["specifier"] for i in imports}
        assert "fsevents" in specifiers

    def test_main_module_types(self):
        content = _pretty(
            {
                "name": "my-lib",
                "main": "./dist/index.cjs",
                "module": "./dist/index.mjs",
                "types": "./dist/index.d.ts",
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        names = {s.name for s in symbols}
        assert "main" in names
        assert "module" in names
        assert "types" in names
        main_sym = next(s for s in symbols if s.name == "main")
        assert "./dist/index.cjs" in main_sym.signature

    def test_description(self):
        content = _pretty({"name": "x", "description": "A cool library"})
        symbols = extract_json_symbols(content, "package.json")
        desc = next(s for s in symbols if s.name == "description")
        assert "A cool library" in desc.signature

    def test_exports_map(self):
        content = _pretty(
            {
                "name": "my-lib",
                "exports": {
                    ".": "./dist/index.js",
                    "./utils": "./dist/utils.js",
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        export_syms = [s for s in symbols if "exports." in s.qualified_name]
        assert len(export_syms) == 2
        names = {s.name for s in export_syms}
        assert "." in names
        assert "./utils" in names

    def test_exports_nested_conditions(self):
        content = _pretty(
            {
                "name": "my-lib",
                "exports": {
                    ".": {
                        "import": "./dist/index.mjs",
                        "require": "./dist/index.cjs",
                    },
                },
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        dot_sym = next(s for s in symbols if s.name == ".")
        assert dot_sym.qualified_name == "exports.."
        assert "{2 keys}" in dot_sym.signature

    def test_engines_as_type(self):
        content = _pretty(
            {
                "name": "test",
                "engines": {"node": ">=18", "npm": ">=9"},
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        engine_syms = [s for s in symbols if s.kind == "type"]
        assert len(engine_syms) == 2

    def test_dependencies_import_extraction(self):
        content = _pretty(
            {
                "name": "test",
                "dependencies": {"express": "^4.0.0", "lodash": "^4.17.0"},
                "devDependencies": {"jest": "^29.0.0"},
            }
        )
        imports = extract_json_imports(content, "package.json")
        specifiers = {i["specifier"] for i in imports}
        assert "express" in specifiers
        assert "lodash" in specifiers
        assert "jest" in specifiers


class TestTsconfig:
    def test_compiler_options(self):
        content = _pretty(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "strict": True,
                    "outDir": "./dist",
                },
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        names = {s.name for s in symbols}
        assert "target" in names
        assert "module" in names
        assert "strict" in names

    def test_compiler_options_line_numbers(self):
        content = _pretty(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "strict": True,
                },
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        target_sym = next(s for s in symbols if s.name == "target")
        strict_sym = next(s for s in symbols if s.name == "strict")
        assert target_sym.line_start > 1
        assert strict_sym.line_start > target_sym.line_start

    def test_paths_extraction(self):
        content = _pretty(
            {
                "compilerOptions": {
                    "paths": {
                        "@/*": ["./src/*"],
                        "@components/*": ["./src/components/*"],
                    },
                },
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        path_syms = [s for s in symbols if "paths." in s.qualified_name]
        assert len(path_syms) == 2

    def test_paths_import_extraction(self):
        content = _pretty(
            {
                "compilerOptions": {
                    "paths": {
                        "@/*": ["./src/*"],
                    },
                },
            }
        )
        imports = extract_json_imports(content, "tsconfig.json")
        assert len(imports) == 1
        assert imports[0]["specifier"] == "./src/*"
        assert imports[0]["names"] == ["@/*"]

    def test_extends_symbol(self):
        content = _pretty(
            {
                "extends": "./base.tsconfig.json",
                "compilerOptions": {"strict": True},
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        extends_sym = next(s for s in symbols if s.name == "extends")
        assert extends_sym.kind == "constant"
        assert "./base.tsconfig.json" in extends_sym.signature

    def test_extends_import(self):
        content = _pretty(
            {
                "extends": "./base.tsconfig.json",
                "compilerOptions": {"strict": True},
            }
        )
        imports = extract_json_imports(content, "tsconfig.json")
        extends_imports = [i for i in imports if i["specifier"] == "./base.tsconfig.json"]
        assert len(extends_imports) == 1
        assert extends_imports[0]["names"] == ["extends"]

    def test_extends_line_number(self):
        content = _pretty(
            {
                "extends": "./base.tsconfig.json",
                "compilerOptions": {"strict": True},
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        extends_sym = next(s for s in symbols if s.name == "extends")
        assert extends_sym.line_start == 2

    def test_include_exclude(self):
        content = _pretty(
            {
                "compilerOptions": {"target": "ES2022"},
                "include": ["src/**/*"],
                "exclude": ["node_modules"],
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        names = {s.name for s in symbols}
        assert "include" in names
        assert "exclude" in names

    def test_files_extraction(self):
        content = _pretty(
            {
                "compilerOptions": {"target": "ES2022"},
                "files": ["src/index.ts", "src/globals.d.ts"],
            }
        )
        symbols = extract_json_symbols(content, "tsconfig.json")
        files_sym = next(s for s in symbols if s.name == "files")
        assert files_sym.kind == "constant"
        assert "src/index.ts" in files_sym.signature

    def test_jsconfig_same_as_tsconfig(self):
        content = _pretty(
            {
                "compilerOptions": {"target": "ES2022"},
            }
        )
        ts_symbols = extract_json_symbols(content, "tsconfig.json")
        js_symbols = extract_json_symbols(content, "jsconfig.json")
        assert len(ts_symbols) == len(js_symbols)


class TestGenericJson:
    def test_top_level_keys(self):
        content = _pretty({"name": "test", "debug": True, "port": 8080})
        symbols = extract_json_symbols(content, "config.json")
        names = {s.name for s in symbols}
        assert "name" in names
        assert "debug" in names
        assert "port" in names

    def test_top_level_line_numbers(self):
        content = _pretty({"name": "test", "debug": True, "port": 8080})
        symbols = extract_json_symbols(content, "config.json")
        name_sym = next(s for s in symbols if s.name == "name")
        port_sym = next(s for s in symbols if s.name == "port")
        assert name_sym.line_start == 2
        assert port_sym.line_start == 4

    def test_nested_keys(self):
        content = _pretty(
            {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                },
            }
        )
        symbols = extract_json_symbols(content, "settings.json")
        assert any(s.qualified_name == "database.host" for s in symbols)
        assert any(s.qualified_name == "database.port" for s in symbols)

    def test_nested_line_numbers(self):
        content = _pretty(
            {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                },
            }
        )
        symbols = extract_json_symbols(content, "settings.json")
        host_sym = next(s for s in symbols if s.name == "host")
        port_sym = next(s for s in symbols if s.name == "port")
        assert host_sym.line_start > 1
        assert port_sym.line_start > host_sym.line_start

    def test_invalid_json(self):
        symbols = extract_json_symbols("not valid json{", "bad.json")
        assert symbols == []

    def test_non_object_json(self):
        symbols = extract_json_symbols("[1, 2, 3]", "array.json")
        assert symbols == []

    def test_empty_object(self):
        symbols = extract_json_symbols("{}", "empty.json")
        assert symbols == []


class TestNestedLineScoping:
    """Verify nested key lookup picks the right line, not a false match."""

    def test_same_key_in_different_sections(self):
        content = _pretty(
            {
                "name": "test",
                "scripts": {"build": "tsc"},
                "devDependencies": {"build": "^1.0.0"},
            }
        )
        symbols = extract_json_symbols(content, "package.json")
        script_build = next(s for s in symbols if s.qualified_name == "scripts.build")
        dep_build = next(s for s in symbols if s.qualified_name == "devDependencies.build")
        assert script_build.line_start != dep_build.line_start
        assert script_build.line_start < dep_build.line_start


class TestJsonImports:
    def test_no_imports_for_generic_json(self):
        content = _pretty({"key": "value"})
        imports = extract_json_imports(content, "config.json")
        assert imports == []

    def test_invalid_json_returns_empty(self):
        imports = extract_json_imports("not json", "bad.json")
        assert imports == []

    def test_non_object_returns_empty(self):
        imports = extract_json_imports("[1,2,3]", "array.json")
        assert imports == []


class TestIntegration:
    def test_parse_file_dispatches_to_json(self):
        from sylvan.indexing.source_code.extractor import parse_file

        content = _pretty(
            {
                "name": "my-app",
                "version": "1.0.0",
                "scripts": {"build": "tsc"},
                "dependencies": {"express": "^4.0.0"},
            }
        )
        symbols = parse_file(content, "package.json", "json")
        assert len(symbols) > 0
        names = {s.name for s in symbols}
        assert "name" in names
        assert "build" in names

    def test_extract_imports_dispatches_to_json(self):
        from sylvan.indexing.source_code.import_extraction import extract_imports

        content = _pretty(
            {
                "name": "test",
                "dependencies": {"react": "^18.0.0"},
            }
        )
        imports = extract_imports(content, "package.json", "json")
        assert len(imports) == 1
        assert imports[0]["specifier"] == "react"
