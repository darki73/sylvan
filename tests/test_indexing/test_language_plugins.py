"""Tests for the language plugin registry and capability lookups."""

from __future__ import annotations

from sylvan.indexing.languages import (
    get_complexity_provider,
    get_import_extractor,
    get_import_resolver,
)
from sylvan.indexing.languages.protocols import ResolverContext
from sylvan.indexing.source_code.language_specs import detect_language, get_spec


class TestPluginRegistration:
    def test_python_spec_registered(self):
        spec = get_spec("python")
        assert spec is not None
        assert spec.ts_language == "python"

    def test_typescript_spec_registered(self):
        spec = get_spec("typescript")
        assert spec is not None
        assert spec.ts_language == "typescript"

    def test_tsx_spec_registered(self):
        spec = get_spec("tsx")
        assert spec is not None
        assert spec.ts_language == "tsx"

    def test_php_spec_registered(self):
        spec = get_spec("php")
        assert spec is not None
        assert spec.ts_language == "php"

    def test_kotlin_alias_registered(self):
        spec = get_spec("kotlin")
        assert spec is not None
        assert spec.ts_language == "kotlin"

    def test_cpp_alias_registered(self):
        spec = get_spec("cpp")
        assert spec is not None
        assert spec.ts_language == "cpp"

    def test_tree_sitter_only_registered(self):
        for lang in ("bash", "lua", "haskell", "julia", "sql", "graphql"):
            spec = get_spec(lang)
            assert spec is not None, f"{lang} not registered"

    def test_unknown_returns_none(self):
        assert get_spec("brainfuck") is None


class TestExtensionDetection:
    def test_py_detected(self):
        assert detect_language("main.py") == "python"

    def test_tsx_detected(self):
        assert detect_language("App.tsx") == "tsx"

    def test_php_detected(self):
        assert detect_language("User.php") == "php"

    def test_kt_detected(self):
        assert detect_language("Main.kt") == "kotlin"

    def test_hpp_detected(self):
        assert detect_language("util.hpp") == "cpp"

    def test_unknown_returns_none(self):
        assert detect_language("file.brainfuck") is None


class TestImportExtractorLookup:
    def test_python_has_extractor(self):
        assert get_import_extractor("python") is not None

    def test_javascript_has_extractor(self):
        assert get_import_extractor("javascript") is not None

    def test_typescript_shares_js_extractor(self):
        js = get_import_extractor("javascript")
        ts = get_import_extractor("typescript")
        assert js is ts

    def test_php_has_extractor(self):
        assert get_import_extractor("php") is not None

    def test_bash_has_no_extractor(self):
        assert get_import_extractor("bash") is None

    def test_lua_has_no_extractor(self):
        assert get_import_extractor("lua") is None


class TestImportResolverLookup:
    def test_python_has_resolver(self):
        assert get_import_resolver("python") is not None

    def test_javascript_has_resolver(self):
        assert get_import_resolver("javascript") is not None

    def test_tsx_shares_js_resolver(self):
        js = get_import_resolver("javascript")
        tsx = get_import_resolver("tsx")
        assert js is tsx

    def test_php_has_resolver(self):
        assert get_import_resolver("php") is not None

    def test_swift_has_no_resolver(self):
        assert get_import_resolver("swift") is None

    def test_scss_has_no_resolver(self):
        assert get_import_resolver("scss") is None


class TestComplexityProviderLookup:
    def test_python_has_provider(self):
        provider = get_complexity_provider("python")
        assert provider is not None
        assert provider.uses_braces is False

    def test_javascript_has_provider(self):
        provider = get_complexity_provider("javascript")
        assert provider is not None
        assert provider.uses_braces is True

    def test_typescript_shares_js_provider(self):
        js = get_complexity_provider("javascript")
        ts = get_complexity_provider("typescript")
        assert js is ts

    def test_rust_strips_self_receiver(self):
        provider = get_complexity_provider("rust")
        assert provider is not None
        assert provider.strip_receiver("&self, x: i32") == "x: i32"
        assert provider.strip_receiver("&self") == ""

    def test_python_strips_self_receiver(self):
        provider = get_complexity_provider("python")
        assert provider is not None
        assert provider.strip_receiver("self, x") == "x"
        assert provider.strip_receiver("cls") == ""

    def test_bash_has_no_provider(self):
        assert get_complexity_provider("bash") is None


class TestResolverContext:
    def test_empty_context(self):
        ctx = ResolverContext()
        assert ctx.psr4_mappings == {}
        assert ctx.tsconfig_aliases == {}

    def test_psr4_context(self):
        ctx = ResolverContext(psr4_mappings={"App\\": ["app/"]})
        assert "App\\" in ctx.psr4_mappings

    def test_tsconfig_context(self):
        ctx = ResolverContext(tsconfig_aliases={"@": ["src"]})
        assert "@" in ctx.tsconfig_aliases
