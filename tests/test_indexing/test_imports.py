"""Tests for sylvan.indexing.source_code.import_extraction — per-language import extraction."""

from __future__ import annotations

from sylvan.indexing.source_code.import_extraction import extract_imports


class TestPythonImports:
    def test_from_import(self):
        code = "from os.path import join, exists\n"
        result = extract_imports(code, "main.py", "python")
        assert len(result) >= 1
        spec = next(r for r in result if r["specifier"] == "os.path")
        assert "join" in spec["names"]
        assert "exists" in spec["names"]

    def test_bare_import(self):
        code = "import os\nimport sys\n"
        result = extract_imports(code, "main.py", "python")
        specifiers = [r["specifier"] for r in result]
        assert "os" in specifiers
        assert "sys" in specifiers

    def test_from_import_with_alias(self):
        code = "from pathlib import Path as P\n"
        result = extract_imports(code, "main.py", "python")
        assert len(result) >= 1
        assert "Path" in result[0]["names"]

    def test_multi_import_on_one_line(self):
        code = "import json, hashlib\n"
        result = extract_imports(code, "main.py", "python")
        specifiers = [r["specifier"] for r in result]
        assert "json" in specifiers
        assert "hashlib" in specifiers


class TestJavaScriptImports:
    def test_named_import(self):
        code = "import { useState, useEffect } from 'react';\n"
        result = extract_imports(code, "app.js", "javascript")
        assert len(result) >= 1
        r = result[0]
        assert r["specifier"] == "react"
        assert "useState" in r["names"]
        assert "useEffect" in r["names"]

    def test_default_import(self):
        code = "import React from 'react';\n"
        result = extract_imports(code, "app.js", "javascript")
        assert len(result) >= 1
        assert result[0]["specifier"] == "react"
        assert "React" in result[0]["names"]

    def test_require(self):
        code = "const fs = require('fs');\n"
        result = extract_imports(code, "app.js", "javascript")
        assert len(result) >= 1
        assert result[0]["specifier"] == "fs"

    def test_typescript_uses_js_extractor(self):
        code = "import { Component } from '@angular/core';\n"
        result = extract_imports(code, "app.ts", "typescript")
        assert len(result) >= 1
        assert result[0]["specifier"] == "@angular/core"


class TestGoImports:
    def test_single_import(self):
        code = 'import "fmt"\n'
        result = extract_imports(code, "main.go", "go")
        assert len(result) == 1
        assert result[0]["specifier"] == "fmt"

    def test_block_import(self):
        code = """import (
    "fmt"
    "net/http"
)
"""
        result = extract_imports(code, "main.go", "go")
        specifiers = [r["specifier"] for r in result]
        assert "fmt" in specifiers
        assert "net/http" in specifiers

    def test_aliased_block_import(self):
        code = """import (
    myfmt "fmt"
)
"""
        result = extract_imports(code, "main.go", "go")
        assert len(result) >= 1
        assert result[0]["specifier"] == "fmt"


class TestRustImports:
    def test_use_single(self):
        code = "use std::collections::HashMap;\n"
        result = extract_imports(code, "main.rs", "rust")
        assert len(result) == 1
        assert result[0]["specifier"] == "std::collections::HashMap"

    def test_use_braces(self):
        code = "use std::io::{Read, Write};\n"
        result = extract_imports(code, "main.rs", "rust")
        assert len(result) == 1
        assert result[0]["specifier"] == "std::io"
        assert "Read" in result[0]["names"]
        assert "Write" in result[0]["names"]


class TestJavaImports:
    def test_basic_import(self):
        code = "import java.util.List;\n"
        result = extract_imports(code, "Main.java", "java")
        assert len(result) == 1
        assert result[0]["specifier"] == "java.util"
        assert "List" in result[0]["names"]

    def test_wildcard_import(self):
        code = "import java.util.*;\n"
        result = extract_imports(code, "Main.java", "java")
        assert len(result) == 1
        assert result[0]["specifier"] == "java.util"


class TestCImports:
    def test_angle_bracket_include(self):
        code = '#include <stdio.h>\n'
        result = extract_imports(code, "main.c", "c")
        assert len(result) == 1
        assert result[0]["specifier"] == "stdio.h"

    def test_quote_include(self):
        code = '#include "myheader.h"\n'
        result = extract_imports(code, "main.c", "c")
        assert len(result) == 1
        assert result[0]["specifier"] == "myheader.h"

    def test_cpp_same_as_c(self):
        code = '#include <iostream>\n#include "utils.h"\n'
        result = extract_imports(code, "main.cpp", "cpp")
        specifiers = [r["specifier"] for r in result]
        assert "iostream" in specifiers
        assert "utils.h" in specifiers


class TestJavaScriptDynamicImports:
    def test_dynamic_import_detected(self):
        code = "const Foo = () => import('./Foo.vue')\n"
        result = extract_imports(code, "router.js", "javascript")
        specifiers = [r["specifier"] for r in result]
        assert "./Foo.vue" in specifiers

    def test_dynamic_import_deduped_with_static(self):
        code = (
            "import Foo from './Foo'\n"
            "const lazy = () => import('./Foo')\n"
        )
        result = extract_imports(code, "app.js", "javascript")
        foo_entries = [r for r in result if r["specifier"] == "./Foo"]
        assert len(foo_entries) == 1  # deduped

    def test_vue_lazy_route_import(self):
        code = "component: () => import('../../views/Lists.vue')\n"
        result = extract_imports(code, "router.ts", "typescript")
        specifiers = [r["specifier"] for r in result]
        assert "../../views/Lists.vue" in specifiers

    def test_await_dynamic_import(self):
        code = "const mod = await import('./dynamic.js')\n"
        result = extract_imports(code, "loader.js", "javascript")
        specifiers = [r["specifier"] for r in result]
        assert "./dynamic.js" in specifiers


class TestUnknownLanguage:
    def test_returns_empty_for_unknown(self):
        result = extract_imports("some code", "file.xyz", "unknown_lang")
        assert result == []
