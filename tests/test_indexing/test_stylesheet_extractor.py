"""Tests for SCSS, LESS, and Stylus custom extraction."""

from sylvan.indexing.source_code.extractor import parse_file
from sylvan.indexing.source_code.import_extraction import extract_imports
from sylvan.indexing.source_code.stylesheet_extractor import (
    extract_less_extras,
    extract_scss_extras,
    extract_stylus_extras,
)


class TestScssVariables:
    def test_extracts_dollar_variables(self):
        code = """
$primary-color: #333;
$font-size: 16px;
$border: 1px solid $primary-color;
"""
        symbols, _ = extract_scss_extras(code, "style.scss", [])
        names = {s.name for s in symbols}
        assert "primary-color" in names
        assert "font-size" in names
        assert "border" in names
        assert all(s.kind == "constant" for s in symbols)

    def test_variable_signature_includes_value(self):
        code = "$spacing: 8px;\n"
        symbols, _ = extract_scss_extras(code, "style.scss", [])
        assert len(symbols) == 1
        assert symbols[0].signature == "$spacing: 8px"

    def test_default_flag_stripped(self):
        code = "$color: red !default;\n"
        symbols, _ = extract_scss_extras(code, "style.scss", [])
        assert len(symbols) == 1
        assert symbols[0].name == "color"

    def test_map_variable(self):
        code = "$breakpoints: (sm: 576px, md: 768px, lg: 992px);\n"
        symbols, _ = extract_scss_extras(code, "style.scss", [])
        assert len(symbols) == 1
        assert symbols[0].name == "breakpoints"

    def test_no_duplicates_with_existing(self):
        code = "$color: red;\n"
        from sylvan.database.validation import Symbol

        existing = [Symbol(name="color", kind="constant")]
        symbols, _ = extract_scss_extras(code, "style.scss", existing)
        assert len(symbols) == 0

    def test_integration_with_parse_file(self):
        code = """
$primary: blue;
.container {
  color: $primary;
}
"""
        symbols = parse_file(code, "style.scss", "scss")
        names = {s.name for s in symbols}
        assert "primary" in names


class TestScssNestedSelectors:
    def test_expands_ampersand_child(self):
        code = """
.parent {
  &__child {
    color: red;
  }
}
"""
        symbols = parse_file(code, "style.scss", "scss")
        names = {s.name for s in symbols}
        assert ".parent__child" in names

    def test_expands_ampersand_modifier(self):
        code = """
.btn {
  &--primary {
    background: blue;
  }
  &--secondary {
    background: gray;
  }
}
"""
        symbols = parse_file(code, "style.scss", "scss")
        names = {s.name for s in symbols}
        assert ".btn--primary" in names
        assert ".btn--secondary" in names

    def test_deeply_nested_ampersand(self):
        code = """
.card {
  &__header {
    &--active {
      color: green;
    }
  }
}
"""
        symbols = parse_file(code, "style.scss", "scss")
        names = {s.name for s in symbols}
        assert ".card__header" in names
        assert ".card__header--active" in names

    def test_expanded_selectors_are_class_kind(self):
        code = """
.nav {
  &__item {
    display: block;
  }
}
"""
        symbols = parse_file(code, "style.scss", "scss")
        expanded = [s for s in symbols if s.name == ".nav__item"]
        assert len(expanded) == 1
        assert expanded[0].kind == "class"


class TestScssImports:
    def test_use_import(self):
        code = '@use "variables" as vars;\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["specifier"] == "variables"
        assert imports[0]["names"] == ["vars"]

    def test_use_without_alias(self):
        code = '@use "mixins";\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["specifier"] == "mixins"
        assert imports[0]["names"] == []

    def test_use_with_star_alias(self):
        code = '@use "utils" as *;\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["names"] == []

    def test_forward_import(self):
        code = '@forward "colors";\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["specifier"] == "colors"

    def test_forward_with_hide(self):
        code = '@forward "utils" hide $internal;\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["specifier"] == "utils"

    def test_legacy_import(self):
        code = '@import "legacy/mixins";\n'
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 1
        assert imports[0]["specifier"] == "legacy/mixins"

    def test_import_extraction_integration(self):
        code = '@use "vars";\n@forward "base";\n'
        imports = extract_imports(code, "style.scss", "scss")
        specifiers = [i["specifier"] for i in imports]
        assert "vars" in specifiers
        assert "base" in specifiers

    def test_multiple_imports(self):
        code = """
@use "variables" as vars;
@use "mixins";
@forward "colors";
@import "legacy";
"""
        _, imports = extract_scss_extras(code, "style.scss", [])
        assert len(imports) == 4


class TestLessVariables:
    def test_extracts_at_variables(self):
        code = """
@primary: #333;
@font-size: 16px;
@border-width: 1px;
"""
        symbols, _ = extract_less_extras(code, "style.less", [])
        names = {s.name for s in symbols}
        assert "primary" in names
        assert "font-size" in names
        assert "border-width" in names
        assert all(s.kind == "constant" for s in symbols)

    def test_variable_signature(self):
        code = "@spacing: 8px;\n"
        symbols, _ = extract_less_extras(code, "style.less", [])
        assert len(symbols) == 1
        assert symbols[0].signature == "@spacing: 8px"

    def test_integration_with_parse_file(self):
        code = """
@primary: blue;
.container {
  color: @primary;
}
"""
        symbols = parse_file(code, "style.less", "less")
        names = {s.name for s in symbols}
        assert "primary" in names

    def test_import_extraction(self):
        code = '@import "variables.less";\n@import (reference) "mixins";\n'
        imports = extract_imports(code, "style.less", "less")
        specifiers = [i["specifier"] for i in imports]
        assert "variables.less" in specifiers
        assert "mixins" in specifiers


class TestLessMixins:
    def test_detects_mixin_with_params(self):
        code = """
.border-radius(@radius) {
  border-radius: @radius;
}
"""
        symbols = parse_file(code, "style.less", "less")
        funcs = [s for s in symbols if s.kind == "function"]
        names = {s.name for s in funcs}
        assert "border-radius" in names

    def test_mixin_without_params_stays_as_type(self):
        code = """
.clearfix {
  &::after {
    content: "";
  }
}
"""
        symbols = parse_file(code, "style.less", "less")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 0


class TestStylusVariables:
    def test_extracts_assignment_variables(self):
        code = """
primary = #333
font-size = 16px
spacing = 8px
"""
        symbols, _ = extract_stylus_extras(code, "style.styl", [])
        names = {s.name for s in symbols}
        assert "primary" in names
        assert "font-size" in names
        assert "spacing" in names
        assert all(s.kind == "constant" for s in symbols)

    def test_variable_signature(self):
        code = "color = red\n"
        symbols, _ = extract_stylus_extras(code, "style.styl", [])
        assert len(symbols) == 1
        assert symbols[0].signature == "color = red"

    def test_skips_css_keywords(self):
        code = "none = something\nauto = other\n"
        symbols, _ = extract_stylus_extras(code, "style.styl", [])
        assert len(symbols) == 0

    def test_extracts_functions(self):
        code = """
border-radius(n)
  -webkit-border-radius n
  border-radius n
"""
        symbols, _ = extract_stylus_extras(code, "style.styl", [])
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "border-radius"
        assert funcs[0].signature == "border-radius(n)"

    def test_import_extraction(self):
        code = '@import "variables"\n@require "mixins"\n'
        imports = extract_imports(code, "style.styl", "stylus")
        specifiers = [i["specifier"] for i in imports]
        assert "variables" in specifiers
        assert "mixins" in specifiers

    def test_skips_selectors_starting_with_special_chars(self):
        code = ".something = value\n#id = other\n"
        symbols, _ = extract_stylus_extras(code, "style.styl", [])
        assert len(symbols) == 0
