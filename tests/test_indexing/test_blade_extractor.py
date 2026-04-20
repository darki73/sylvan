"""Tests for Blade template extraction."""

from __future__ import annotations

from sylvan.indexing.source_code.blade_extractor import (
    extract_blade_imports,
    extract_blade_symbols,
)
from sylvan.indexing.source_code.language_specs import detect_language


class TestCompoundExtensionDetection:
    def test_blade_php_detected_as_blade(self):
        assert detect_language("view.blade.php") == "blade"

    def test_nested_path_blade(self):
        assert detect_language("resources/views/layouts/app.blade.php") == "blade"

    def test_plain_php_still_php(self):
        assert detect_language("app/Models/User.php") == "php"

    def test_plain_php_no_path(self):
        assert detect_language("User.php") == "php"

    def test_unknown_compound_falls_back(self):
        assert detect_language("file.test.ts") == "typescript"

    def test_no_extension(self):
        assert detect_language("Makefile") is None

    def test_single_dot(self):
        assert detect_language("main.py") == "python"


class TestBladeSymbolSections:
    def test_section_extraction(self):
        content = """
@extends('layouts.app')

@section('content')
    <h1>Hello</h1>
@endsection

@section('sidebar')
    <p>Sidebar</p>
@endsection
"""
        symbols = extract_blade_symbols(content, "resources/views/home.blade.php")
        names = [s.name for s in symbols if s.qualified_name.startswith("@section")]
        assert "content" in names
        assert "sidebar" in names
        assert all(s.kind == "function" for s in symbols if s.qualified_name.startswith("@section"))
        assert all(s.language == "blade" for s in symbols)

    def test_section_line_numbers(self):
        content = "@section('header')\n<h1>Title</h1>\n@endsection"
        symbols = extract_blade_symbols(content, "test.blade.php")
        section = next(s for s in symbols if s.name == "header")
        assert section.line_start == 1

    def test_section_symbol_ids(self):
        content = "@section('main')"
        symbols = extract_blade_symbols(content, "home.blade.php")
        section = next(s for s in symbols if s.name == "main")
        assert section.symbol_id == "home.blade.php::@section('main')#function"


class TestBladeSymbolYield:
    def test_yield_extraction(self):
        content = "@yield('content')\n@yield('sidebar')"
        symbols = extract_blade_symbols(content, "layouts/app.blade.php")
        names = [s.name for s in symbols]
        assert "content" in names
        assert "sidebar" in names

    def test_yield_kind_is_function(self):
        content = "@yield('title')"
        symbols = extract_blade_symbols(content, "layouts/app.blade.php")
        assert symbols[0].kind == "function"

    def test_yield_symbol_id(self):
        content = "@yield('scripts')"
        symbols = extract_blade_symbols(content, "layout.blade.php")
        assert symbols[0].symbol_id == "layout.blade.php::@yield('scripts')#function"


class TestBladeSymbolSlot:
    def test_slot_extraction(self):
        content = "@slot('header')\n<h1>Title</h1>\n@endslot"
        symbols = extract_blade_symbols(content, "test.blade.php")
        slot = next(s for s in symbols if s.name == "header")
        assert slot.kind == "function"
        assert slot.signature == "@slot('header')"


class TestBladeSymbolPush:
    def test_push_extraction(self):
        content = "@push('scripts')\n<script>...</script>\n@endpush"
        symbols = extract_blade_symbols(content, "test.blade.php")
        push = next(s for s in symbols if s.name == "scripts")
        assert push.kind == "function"

    def test_push_once(self):
        content = "@pushOnce('styles')\n<link />\n@endPushOnce"
        symbols = extract_blade_symbols(content, "test.blade.php")
        assert any(s.name == "styles" for s in symbols)

    def test_push_if(self):
        content = "@pushIf($condition, 'scripts')\n<script />\n@endPushIf"
        symbols = extract_blade_symbols(content, "test.blade.php")
        assert any(s.name == "scripts" for s in symbols)


class TestBladeSymbolProps:
    def test_props_extraction(self):
        content = "@props(['type' => 'info', 'message', 'dismissible' => false])"
        symbols = extract_blade_symbols(content, "components/alert.blade.php")
        names = sorted(s.name for s in symbols if s.qualified_name.startswith("@props"))
        assert names == ["dismissible", "message", "type"]
        assert all(s.kind == "constant" for s in symbols if s.qualified_name.startswith("@props"))

    def test_props_multiline(self):
        content = """@props([
    'title',
    'color' => 'blue',
])"""
        symbols = extract_blade_symbols(content, "components/card.blade.php")
        names = sorted(s.name for s in symbols if s.qualified_name.startswith("@props"))
        assert names == ["color", "title"]

    def test_props_symbol_ids(self):
        content = "@props(['title'])"
        symbols = extract_blade_symbols(content, "card.blade.php")
        prop = next(s for s in symbols if s.name == "title")
        assert prop.symbol_id == "card.blade.php::@props.title#constant"


class TestBladeSymbolAware:
    def test_aware_extraction(self):
        content = "@aware(['color'])"
        symbols = extract_blade_symbols(content, "components/nested.blade.php")
        aware = [s for s in symbols if s.qualified_name.startswith("@aware")]
        assert len(aware) == 1
        assert aware[0].name == "color"
        assert aware[0].kind == "constant"

    def test_aware_symbol_id(self):
        content = "@aware(['theme'])"
        symbols = extract_blade_symbols(content, "nested.blade.php")
        assert symbols[0].symbol_id == "nested.blade.php::@aware.theme#constant"


class TestBladeSymbolPhpBlocks:
    def test_php_function_extracted(self):
        content = """
@php
    function formatDate($date) {
        return $date->format('Y-m-d');
    }
@endphp
"""
        symbols = extract_blade_symbols(content, "helpers.blade.php")
        funcs = [s for s in symbols if s.kind == "function" and s.name == "formatDate"]
        assert len(funcs) == 1

    def test_empty_php_block_no_symbols(self):
        content = "@php\n@endphp"
        symbols = extract_blade_symbols(content, "test.blade.php")
        # Should not crash, may produce no PHP symbols
        assert isinstance(symbols, list)

    def test_use_only_block_no_symbols(self):
        content = "@php\n    use App\\Models\\User;\n@endphp"
        symbols = extract_blade_symbols(content, "test.blade.php")
        # use-only blocks are skipped for symbol extraction (handled as imports)
        php_syms = [s for s in symbols if s.qualified_name.startswith("@") is False]
        assert php_syms == []


class TestBladeSymbolPlainHtml:
    def test_no_symbols_from_plain_html(self):
        content = "<div><h1>Hello World</h1></div>"
        symbols = extract_blade_symbols(content, "test.blade.php")
        assert symbols == []


class TestBladeImports:
    def test_extends(self):
        content = "@extends('layouts.app')"
        imports = extract_blade_imports(content)
        assert len(imports) == 1
        assert imports[0]["specifier"] == "layouts.app"

    def test_include(self):
        content = "@include('partials.header')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "partials.header"

    def test_include_if(self):
        content = "@includeIf('partials.optional')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "partials.optional"

    def test_include_when(self):
        content = "@includeWhen($condition, 'partials.conditional')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "partials.conditional"

    def test_include_unless(self):
        content = "@includeUnless($admin, 'partials.notice')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "partials.notice"

    def test_include_first(self):
        content = "@includeFirst(['custom.header', 'default.header'])"
        imports = extract_blade_imports(content)
        specs = sorted(i["specifier"] for i in imports)
        assert specs == ["custom.header", "default.header"]

    def test_component_directive(self):
        content = "@component('components.alert')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "components.alert"

    def test_livewire_directive(self):
        content = "@livewire('search-users')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "livewire.search-users"

    def test_x_component_tag(self):
        content = '<x-alert type="error" />'
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "components.alert"

    def test_x_component_nested(self):
        content = "<x-layouts.app>"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "components.layouts.app"

    def test_livewire_tag(self):
        content = "<livewire:user-table />"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "livewire.user-table"

    def test_each(self):
        content = "@each('partials.item', $items, 'item')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "partials.item"

    def test_blade_use_directive(self):
        content = "@use('App\\Models\\User')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "App\\Models\\User"

    def test_blade_use_with_alias(self):
        content = "@use('App\\Enums\\Status', 'UserStatus')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "App\\Enums\\Status"

    def test_php_block_use_statements(self):
        content = """
@php
    use App\\Models\\User;
    use App\\Services\\Auth;
@endphp
"""
        imports = extract_blade_imports(content)
        specs = [i["specifier"] for i in imports]
        assert "App\\Models\\User" in specs
        assert "App\\Services\\Auth" in specs

    def test_namespaced_view(self):
        content = "@include('mail::message')"
        imports = extract_blade_imports(content)
        assert imports[0]["specifier"] == "mail::message"

    def test_deduplication(self):
        content = "@include('partials.header')\n@include('partials.header')"
        imports = extract_blade_imports(content)
        assert len(imports) == 1

    def test_multiple_imports(self):
        content = """
@extends('layouts.app')

@section('content')
    @include('partials.header')
    <x-alert type="info" />
    <livewire:search-bar />
    @livewire('data-table')
@endsection
"""
        imports = extract_blade_imports(content)
        specs = sorted(i["specifier"] for i in imports)
        assert specs == [
            "components.alert",
            "layouts.app",
            "livewire.data-table",
            "livewire.search-bar",
            "partials.header",
        ]

    def test_empty_content(self):
        assert extract_blade_imports("") == []

    def test_plain_html_no_imports(self):
        content = "<div><h1>Hello</h1></div>"
        assert extract_blade_imports(content) == []

    def test_all_names_empty(self):
        content = "@extends('layouts.app')"
        imports = extract_blade_imports(content)
        assert imports[0]["names"] == []


class TestBladeResolution:
    def test_dot_notation_candidates(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("layouts.app", "resources/views/home.blade.php", None)
        assert "resources/views/layouts/app.blade.php" in candidates
        assert "resources/views/layouts/app/index.blade.php" in candidates

    def test_component_candidates(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("components.alert", "resources/views/home.blade.php", None)
        assert "resources/views/components/alert.blade.php" in candidates

    def test_livewire_candidates(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("livewire.search-users", "resources/views/home.blade.php", None)
        assert "resources/views/livewire/search-users.blade.php" in candidates
        assert "app/Livewire/SearchUsers.php" in candidates

    def test_namespaced_view_candidates(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("mail::message", "resources/views/emails/welcome.blade.php", None)
        assert "resources/views/vendor/mail/message.blade.php" in candidates
        assert "vendor/mail/resources/views/message.blade.php" in candidates

    def test_namespaced_nested_view(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("notifications::email", "test.blade.php", None)
        assert "resources/views/vendor/notifications/email.blade.php" in candidates

    def test_php_namespace_delegates(self):
        from sylvan.indexing.languages import get_import_resolver

        lang = get_import_resolver("blade")
        candidates = lang.generate_candidates("App\\Models\\User", "test.blade.php", None)
        assert not any("resources/views" in c for c in candidates)
