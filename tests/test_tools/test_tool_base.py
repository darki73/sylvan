"""Tests for the tool base framework - params, traits, schema generation, and Tool class."""

import pytest

from sylvan.tools.base.params import (
    REQUIRED,
    HasContextLines,
    HasDepth,
    HasDirection,
    HasDocPath,
    HasFileFilter,
    HasFilePath,
    HasFilePaths,
    HasKindFilter,
    HasLanguageFilter,
    HasMaxDepth,
    HasOptionalFilePath,
    HasOptionalRepo,
    HasOptionalSymbol,
    HasPagination,
    HasProjectPath,
    HasQuery,
    HasRepo,
    HasSectionId,
    HasSectionIds,
    HasSymbol,
    HasSymbolIds,
    HasVerify,
    HasWorkspace,
    ToolParams,
    _FieldSpec,
    schema_field,
)
from sylvan.tools.base.tool import MeasureMethod, Tool, _registry, get_all_tools, get_registry, get_tool


class TestSchemaField:
    def test_required_field(self):
        spec = schema_field(description="test")
        assert isinstance(spec, _FieldSpec)
        assert spec.is_required
        assert spec.description == "test"
        assert spec.default is REQUIRED

    def test_optional_field(self):
        spec = schema_field(description="test", default=42)
        assert not spec.is_required
        assert spec.default == 42

    def test_none_default(self):
        spec = schema_field(description="test", default=None)
        assert not spec.is_required
        assert spec.default is None

    def test_validation_metadata(self):
        spec = schema_field(description="x", ge=1, le=100, enum=["a", "b"])
        assert spec.ge == 1
        assert spec.le == 100
        assert spec.enum == ["a", "b"]


class TestToolParamsSchema:
    def test_empty_params(self):
        class Params(ToolParams):
            pass

        schema = Params.to_schema()
        assert schema == {"type": "object", "properties": {}}

    def test_required_field_in_schema(self):
        class Params(HasSymbol, ToolParams):
            pass

        schema = Params.to_schema()
        assert "symbol_id" in schema["properties"]
        assert "symbol_id" in schema["required"]
        assert schema["properties"]["symbol_id"]["type"] == "string"

    def test_optional_field_has_default(self):
        class Params(HasDepth, ToolParams):
            pass

        schema = Params.to_schema()
        assert schema["properties"]["depth"]["default"] == 2
        assert "required" not in schema or "depth" not in schema.get("required", [])

    def test_mixed_required_and_optional(self):
        class Params(HasSymbol, HasDepth, ToolParams):
            pass

        schema = Params.to_schema()
        assert schema["required"] == ["symbol_id"]
        assert "depth" not in schema["required"]
        assert schema["properties"]["depth"]["default"] == 2

    def test_multiple_required(self):
        class Params(HasRepo, HasFilePath, ToolParams):
            pass

        schema = Params.to_schema()
        assert "repo" in schema["required"]
        assert "file_path" in schema["required"]

    def test_many_traits(self):
        class Params(
            HasQuery, HasOptionalRepo, HasKindFilter, HasLanguageFilter, HasFileFilter, HasPagination, ToolParams
        ):
            pass

        schema = Params.to_schema()
        assert schema["required"] == ["query"]
        assert len(schema["properties"]) == 6

    def test_custom_field_alongside_traits(self):
        class Params(HasSymbol, ToolParams):
            custom: str = schema_field(description="A custom param")

        schema = Params.to_schema()
        assert "symbol_id" in schema["properties"]
        assert "custom" in schema["properties"]
        assert "symbol_id" in schema["required"]
        assert "custom" in schema["required"]

    def test_custom_optional_field(self):
        class Params(HasRepo, ToolParams):
            flag: bool = schema_field(default=False, description="A flag")

        schema = Params.to_schema()
        assert schema["properties"]["flag"]["type"] == "boolean"
        assert schema["properties"]["flag"]["default"] is False
        assert "flag" not in schema["required"]

    def test_integer_type(self):
        class Params(HasPagination, ToolParams):
            pass

        schema = Params.to_schema()
        assert schema["properties"]["max_results"]["type"] == "integer"

    def test_minimum_maximum(self):
        class Params(HasDepth, ToolParams):
            pass

        schema = Params.to_schema()
        prop = schema["properties"]["depth"]
        assert prop["minimum"] == 1
        assert prop["maximum"] == 3

    def test_enum(self):
        class Params(HasKindFilter, ToolParams):
            pass

        schema = Params.to_schema()
        assert schema["properties"]["kind"]["enum"] == [
            "function",
            "class",
            "method",
            "constant",
            "type",
        ]

    def test_list_type(self):
        class Params(HasSymbolIds, ToolParams):
            pass

        schema = Params.to_schema()
        prop = schema["properties"]["symbol_ids"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "string"


class TestToolParamsFromDict:
    def test_basic(self):
        class Params(HasSymbol, HasDepth, ToolParams):
            pass

        p = Params.from_dict({"symbol_id": "foo::bar#function", "depth": 3})
        assert p.symbol_id == "foo::bar#function"
        assert p.depth == 3

    def test_defaults_applied(self):
        class Params(HasSymbol, HasDepth, ToolParams):
            pass

        p = Params.from_dict({"symbol_id": "test"})
        assert p.depth == 2

    def test_unknown_keys_filtered(self):
        class Params(HasSymbol, ToolParams):
            pass

        p = Params.from_dict({"symbol_id": "test", "junk": "ignored", "also_junk": 42})
        assert p.symbol_id == "test"
        assert not hasattr(p, "junk")

    def test_missing_required_raises(self):
        class Params(HasSymbol, HasDepth, ToolParams):
            pass

        with pytest.raises(TypeError, match="Missing required parameter: symbol_id"):
            Params.from_dict({"depth": 2})

    def test_none_default_preserved(self):
        class Params(HasOptionalRepo, ToolParams):
            pass

        p = Params.from_dict({})
        assert p.repo is None

    def test_none_overridden(self):
        class Params(HasOptionalRepo, ToolParams):
            pass

        p = Params.from_dict({"repo": "my-repo"})
        assert p.repo == "my-repo"


class TestTraitDescriptions:
    """Every trait must have a non-empty description."""

    @pytest.mark.parametrize(
        "trait_cls",
        [
            HasRepo,
            HasOptionalRepo,
            HasSymbol,
            HasOptionalSymbol,
            HasQuery,
            HasFilePath,
            HasOptionalFilePath,
            HasPagination,
            HasDepth,
            HasKindFilter,
            HasLanguageFilter,
            HasFileFilter,
            HasWorkspace,
            HasProjectPath,
            HasContextLines,
            HasVerify,
            HasDirection,
            HasMaxDepth,
            HasDocPath,
            HasSymbolIds,
            HasFilePaths,
            HasSectionId,
            HasSectionIds,
        ],
    )
    def test_trait_has_description(self, trait_cls):
        # Build a Params class using just this trait
        params_cls = type("P", (trait_cls, ToolParams), {})
        schema = params_cls.to_schema()
        for name, prop in schema["properties"].items():
            assert "description" in prop, f"{trait_cls.__name__}.{name} missing description"
            assert len(prop["description"]) > 5, f"{trait_cls.__name__}.{name} description too short"


class TestTraitFieldNames:
    """HasRepo and HasOptionalRepo must use the same field name."""

    def test_repo_field_name_consistent(self):
        class P1(HasRepo, ToolParams):
            pass

        class P2(HasOptionalRepo, ToolParams):
            pass

        assert "repo" in P1.to_schema()["properties"]
        assert "repo" in P2.to_schema()["properties"]

    def test_symbol_field_name_consistent(self):
        class P1(HasSymbol, ToolParams):
            pass

        class P2(HasOptionalSymbol, ToolParams):
            pass

        assert "symbol_id" in P1.to_schema()["properties"]
        assert "symbol_id" in P2.to_schema()["properties"]

    def test_file_path_field_name_consistent(self):
        class P1(HasFilePath, ToolParams):
            pass

        class P2(HasOptionalFilePath, ToolParams):
            pass

        assert "file_path" in P1.to_schema()["properties"]
        assert "file_path" in P2.to_schema()["properties"]


class TestToolClass:
    def test_auto_registration(self):
        class _TestAutoReg(Tool):
            name = "test_auto_reg_xyz"
            category = "meta"
            description = "test"

            async def handle(self, p):
                return {}

        assert "test_auto_reg_xyz" in _registry
        # Cleanup
        _registry.pop("test_auto_reg_xyz", None)

    def test_no_name_not_registered(self):
        before = len(_registry)

        class _NoName(Tool):
            pass

        assert len(_registry) == before

    def test_to_mcp_tool(self):
        class _TestMCP(Tool):
            name = "test_mcp_gen"
            category = "analysis"
            description = "A test tool"

            class Params(HasSymbol, HasDepth, ToolParams):
                pass

            async def handle(self, p):
                return {}

        mcp_tool = _TestMCP().to_mcp_tool()
        assert mcp_tool.name == "test_mcp_gen"
        assert mcp_tool.description == "A test tool"
        assert mcp_tool.inputSchema["required"] == ["symbol_id"]
        assert "depth" in mcp_tool.inputSchema["properties"]

        _registry.pop("test_mcp_gen", None)

    def test_get_tool(self):
        class _TestGet(Tool):
            name = "test_get_instance"
            description = "test"

            async def handle(self, p):
                return {}

        tool = get_tool("test_get_instance")
        assert tool is not None
        assert tool.name == "test_get_instance"
        assert get_tool("nonexistent") is None

        _registry.pop("test_get_instance", None)

    def test_get_all_tools(self):
        class _TestAll(Tool):
            name = "test_get_all"
            description = "test"

            async def handle(self, p):
                return {}

        tools = get_all_tools()
        names = [t.name for t in tools]
        assert "test_get_all" in names

        _registry.pop("test_get_all", None)

    def test_get_registry(self):
        reg = get_registry()
        assert isinstance(reg, dict)


class TestToolExecute:
    @pytest.mark.asyncio
    async def test_execute_wraps_meta(self):
        class _TestExec(Tool):
            name = "test_exec"
            description = "test"

            class Params(HasSymbol, ToolParams):
                pass

            async def handle(self, p):
                return {"result": p.symbol_id}

        tool = _TestExec()
        result = await tool.execute({"symbol_id": "foo"})
        assert result["result"] == "foo"
        assert "_meta" in result
        assert "timing_ms" in result["_meta"]
        assert result["_version"] == "1.0"

        _registry.pop("test_exec", None)

    @pytest.mark.asyncio
    async def test_execute_preserves_existing_meta(self):
        class _TestMeta(Tool):
            name = "test_meta_preserve"
            description = "test"

            class Params(HasRepo, ToolParams):
                pass

            async def handle(self, p):
                return {"data": 1, "_meta": {"custom": "value"}}

        tool = _TestMeta()
        result = await tool.execute({"repo": "my-repo"})
        assert result["_meta"]["custom"] == "value"
        assert result["_meta"]["repo"] == "my-repo"
        assert "timing_ms" in result["_meta"]

        _registry.pop("test_meta_preserve", None)

    @pytest.mark.asyncio
    async def test_execute_validates_required(self):
        class _TestReq(Tool):
            name = "test_req"
            description = "test"

            class Params(HasSymbol, ToolParams):
                pass

            async def handle(self, p):
                return {}

        tool = _TestReq()
        with pytest.raises(TypeError, match="Missing required parameter"):
            await tool.execute({})

        _registry.pop("test_req", None)


class TestRequireAnyOf:
    def test_one_provided(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]

        p = Params.from_dict({"symbol_id": "foo"})
        assert p.symbol_id == "foo"
        assert p.file_path is None

    def test_other_provided(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]

        p = Params.from_dict({"file_path": "src/main.py"})
        assert p.symbol_id is None
        assert p.file_path == "src/main.py"

    def test_both_provided(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]

        p = Params.from_dict({"symbol_id": "foo", "file_path": "bar.py"})
        assert p.symbol_id == "foo"
        assert p.file_path == "bar.py"

    def test_neither_provided_raises(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]

        with pytest.raises(TypeError, match="Provide at least one of: symbol_id, file_path"):
            Params.from_dict({})

    def test_multiple_groups(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, HasOptionalRepo, ToolParams):
            require_any_of = [
                ("symbol_id", "file_path"),
                ("repo",),
            ]

        # Both groups satisfied
        p = Params.from_dict({"symbol_id": "foo", "repo": "bar"})
        assert p.symbol_id == "foo"

        # First group fails
        with pytest.raises(TypeError, match="symbol_id, file_path"):
            Params.from_dict({"repo": "bar"})

    def test_no_constraints_by_default(self):
        class Params(HasOptionalSymbol, ToolParams):
            pass

        p = Params.from_dict({})
        assert p.symbol_id is None


class TestMutuallyExclusive:
    def test_one_provided(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            mutually_exclusive = [("symbol_id", "file_path")]

        p = Params.from_dict({"symbol_id": "foo"})
        assert p.symbol_id == "foo"
        assert p.file_path is None

    def test_neither_provided_ok(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            mutually_exclusive = [("symbol_id", "file_path")]

        p = Params.from_dict({})
        assert p.symbol_id is None
        assert p.file_path is None

    def test_both_provided_raises(self):
        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            mutually_exclusive = [("symbol_id", "file_path")]

        with pytest.raises(TypeError, match="Provide only one of: symbol_id, file_path"):
            Params.from_dict({"symbol_id": "foo", "file_path": "bar.py"})

    def test_combined_with_require_any_of(self):
        """mutually_exclusive + require_any_of = exactly one required."""

        class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
            require_any_of = [("symbol_id", "file_path")]
            mutually_exclusive = [("symbol_id", "file_path")]

        p = Params.from_dict({"symbol_id": "foo"})
        assert p.symbol_id == "foo"

        with pytest.raises(TypeError, match="at least one of"):
            Params.from_dict({})

        with pytest.raises(TypeError, match="only one of"):
            Params.from_dict({"symbol_id": "foo", "file_path": "bar.py"})


class TestTypeCoercion:
    def test_string_to_int(self):
        class Params(HasPagination, ToolParams):
            pass

        p = Params.from_dict({"max_results": "50"})
        assert p.max_results == 50
        assert isinstance(p.max_results, int)

    def test_string_to_bool_true(self):
        class Params(HasVerify, ToolParams):
            pass

        p = Params.from_dict({"verify": "true"})
        assert p.verify is True

    def test_string_to_bool_false(self):
        class Params(HasVerify, ToolParams):
            pass

        p = Params.from_dict({"verify": "false"})
        assert p.verify is False

    def test_numeric_to_string(self):
        class Params(HasQuery, ToolParams):
            pass

        p = Params.from_dict({"query": 42})
        assert p.query == "42"
        assert isinstance(p.query, str)

    def test_already_correct_type_unchanged(self):
        class Params(HasPagination, ToolParams):
            pass

        p = Params.from_dict({"max_results": 10})
        assert p.max_results == 10

    def test_none_not_coerced(self):
        class Params(HasOptionalRepo, ToolParams):
            pass

        p = Params.from_dict({"repo": None})
        assert p.repo is None

    def test_string_to_int_for_depth(self):
        class Params(HasDepth, ToolParams):
            pass

        p = Params.from_dict({"depth": "3"})
        assert p.depth == 3

    def test_invalid_string_to_int_passes_through(self):
        class Params(HasPagination, ToolParams):
            pass

        p = Params.from_dict({"max_results": "not_a_number"})
        assert p.max_results == "not_a_number"


class TestMeasure:
    @pytest.mark.asyncio
    async def test_no_measure_no_efficiency(self):
        class _NoMeasure(Tool):
            name = "test_no_measure"
            description = "test"

            class Params(HasRepo, ToolParams):
                pass

            async def handle(self, p):
                return {"data": "hello"}

        result = await _NoMeasure().execute({"repo": "test"})
        assert "token_efficiency" not in result["_meta"]
        _registry.pop("test_no_measure", None)

    @pytest.mark.asyncio
    async def test_measure_attaches_efficiency(self):
        class _WithMeasure(Tool):
            name = "test_with_measure"
            description = "test"

            class Params(HasSymbol, ToolParams):
                pass

            async def handle(self, p):
                return {"source": "def foo(): pass"}

            def measure(self, result):
                returned = len(result.get("source", "")) // 4
                equivalent = 500
                return returned, equivalent

        result = await _WithMeasure().execute({"symbol_id": "foo"})
        eff = result["_meta"]["token_efficiency"]
        assert eff["returned"] == 3  # len("def foo(): pass") // 4
        assert eff["equivalent_file_read"] == 500
        assert eff["reduction_percent"] == 99.4
        assert eff["method"] == MeasureMethod.BYTE_ESTIMATE
        _registry.pop("test_with_measure", None)

    @pytest.mark.asyncio
    async def test_custom_measure_method(self):
        class _TikToken(Tool):
            name = "test_tiktoken"
            description = "test"

            async def handle(self, p):
                return {"data": "x"}

            def measure(self, result):
                return 100, 1000

            def measure_method(self):
                return MeasureMethod.TIKTOKEN_CL100K

        result = await _TikToken().execute({})
        assert result["_meta"]["token_efficiency"]["method"] == MeasureMethod.TIKTOKEN_CL100K
        _registry.pop("test_tiktoken", None)

    @pytest.mark.asyncio
    async def test_measure_zero_equivalent_no_division_error(self):
        class _ZeroEquiv(Tool):
            name = "test_zero_equiv"
            description = "test"

            async def handle(self, p):
                return {"data": "x"}

            def measure(self, result):
                return 10, 0

        result = await _ZeroEquiv().execute({})
        eff = result["_meta"]["token_efficiency"]
        assert eff["reduction_percent"] == 0.0
        _registry.pop("test_zero_equiv", None)

    @pytest.mark.asyncio
    async def test_measure_does_not_overwrite_existing_meta(self):
        class _ExistingMeta(Tool):
            name = "test_existing_meta"
            description = "test"

            class Params(HasRepo, ToolParams):
                pass

            async def handle(self, p):
                return {"data": 1, "_meta": {"custom": "kept"}}

            def measure(self, result):
                return 50, 200

        result = await _ExistingMeta().execute({"repo": "r"})
        assert result["_meta"]["custom"] == "kept"
        assert result["_meta"]["token_efficiency"]["returned"] == 50
        _registry.pop("test_existing_meta", None)


class TestHintBuilder:
    def test_empty_returns_none(self):
        from sylvan.tools.base.hints import HintBuilder

        assert HintBuilder().build() is None

    def test_read_hint(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().read("src/main.py", 10, 20)
        built = h.build()
        assert len(built["read"]) == 1
        assert built["read"][0]["file_path"] == "src/main.py"
        assert built["read"][0]["offset"] == 5
        assert built["read"][0]["limit"] == 20

    def test_read_multiple(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().read("a.py", 1, 10).read("b.py", 20, 30)
        built = h.build()
        assert len(built["read"]) == 2
        assert built["read"][0]["file_path"] == "a.py"
        assert built["read"][1]["file_path"] == "b.py"

    def test_read_custom_context(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().read("f.py", 1, 5, context=0)
        assert h.build()["read"][0]["offset"] == 1
        assert h.build()["read"][0]["limit"] == 4

    def test_edit_hint(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().edit("src/main.py", "def foo():")
        built = h.build()
        assert len(built["edit"]) == 1
        assert built["edit"][0]["file_path"] == "src/main.py"
        assert built["edit"][0]["old_string_starts_with"] == "def foo():"

    def test_edit_multiple(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().edit("a.py", "def foo():").edit("b.py", "def bar():")
        built = h.build()
        assert len(built["edit"]) == 2

    def test_reindex_hint(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().reindex("my-repo", "src/main.py")
        built = h.build()
        assert len(built["reindex"]) == 1
        assert "index_file" in built["reindex"][0]

    def test_reindex_multiple(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().reindex("r", "a.py").reindex("r", "b.py")
        built = h.build()
        assert len(built["reindex"]) == 2

    def test_test_files_hint(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().test_files(["tests/test_a.py", "tests/test_b.py"])
        built = h.build()
        assert built["test_files"] == ["tests/test_a.py", "tests/test_b.py"]

    def test_test_files_limit(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().test_files([f"t{i}.py" for i in range(10)])
        assert len(h.build()["test_files"]) == 5

    def test_next_tool(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().next_tool("check", "some_tool('arg')")
        assert h.build()["next"]["check"] == "some_tool('arg')"

    def test_next_blast_radius(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().next_blast_radius("foo::bar#function")
        assert "get_blast_radius" in h.build()["next"]["blast_radius"]
        assert "symbol_id=" in h.build()["next"]["blast_radius"]

    def test_next_importers(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().next_importers("repo", "src/main.py")
        built = h.build()["next"]["find_callers"]
        assert "find_importers" in built
        assert "repo=" in built
        assert "file_path=" in built

    def test_next_search(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().next_search("dispatch", repo="sylvan", kind="function")
        built = h.build()["next"]["search_deeper"]
        assert "search_symbols" in built
        assert "dispatch" in built
        assert "sylvan" in built
        assert "function" in built

    def test_working_files(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().working_files(["a.py", "b.py", "c.py", "d.py"], limit=2)
        assert h.build()["working_files"] == ["a.py", "b.py"]

    def test_for_symbol_full(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().for_symbol(
            "foo::bar#function",
            "src/bar.py",
            10,
            30,
            first_line="def bar():",
            repo="my-repo",
        )
        built = h.build()
        assert "read" in built
        assert "edit" in built
        assert "reindex" in built
        assert "next" in built
        assert "blast_radius" in built["next"]
        assert "find_callers" in built["next"]
        assert "dependency_graph" in built["next"]

    def test_for_symbol_no_lines(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().for_symbol("foo::bar#function", "src/bar.py", repo="r")
        built = h.build()
        assert "read" not in built
        assert "edit" not in built
        assert "next" in built

    def test_for_symbol_no_repo(self):
        from sylvan.tools.base.hints import HintBuilder

        h = HintBuilder().for_symbol("foo::bar#function", "src/bar.py", 1, 10)
        built = h.build()
        assert "read" in built
        assert "reindex" not in built
        assert "find_callers" not in built

    def test_apply_attaches_to_result(self):
        from sylvan.tools.base.hints import HintBuilder

        result = {"data": 1}
        HintBuilder().next_blast_radius("sym").apply(result)
        assert "_hints" in result

    def test_apply_skips_when_empty(self):
        from sylvan.tools.base.hints import HintBuilder

        result = {"data": 1}
        HintBuilder().apply(result)
        assert "_hints" not in result

    def test_chaining(self):
        from sylvan.tools.base.hints import HintBuilder

        built = (
            HintBuilder()
            .read("f.py", 1, 10)
            .edit("f.py", "def foo():")
            .reindex("r", "f.py")
            .test_files(["tests/t.py"])
            .next_blast_radius("sym")
            .next_importers("r", "f.py")
            .working_files(["a.py"])
            .build()
        )
        assert "read" in built
        assert "edit" in built
        assert "reindex" in built
        assert "test_files" in built
        assert "next" in built
        assert "working_files" in built

    def test_tool_hints_method(self):
        class _TestHints(Tool):
            name = "test_hints_method"
            description = "test"

            async def handle(self, p):
                result = {"data": 1}
                self.hints().for_symbol("s", "f.py", 1, 10, repo="r").apply(result)
                return result

        tool = _TestHints()
        h = tool.hints()
        assert h is not None
        _registry.pop("test_hints_method", None)


class TestToolMeta:
    def test_build_basic(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.repo("sylvan").repo_id(42).results_count(10)
        built = m.build()
        assert built["repo"] == "sylvan"
        assert built["repo_id"] == 42
        assert built["results_count"] == 10
        assert "timing_ms" in built

    def test_omits_none_fields(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.repo("test")
        built = m.build()
        assert "results_count" not in built
        assert "query" not in built
        assert "found" not in built

    def test_token_efficiency(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.token_efficiency(100, 1000, "tiktoken_cl100k")
        built = m.build()
        eff = built["token_efficiency"]
        assert eff["returned"] == 100
        assert eff["equivalent_file_read"] == 1000
        assert eff["reduction_percent"] == 90.0
        assert eff["method"] == "tiktoken_cl100k"

    def test_token_efficiency_accumulates(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.token_efficiency(50, 200)
        m.token_efficiency(50, 300)
        built = m.build()
        assert built["token_efficiency"]["returned"] == 100
        assert built["token_efficiency"]["equivalent_file_read"] == 500

    def test_no_efficiency_when_zero(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.repo("test")
        built = m.build()
        assert "token_efficiency" not in built

    def test_query_and_already_seen(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.query("dispatch").already_seen(3)
        built = m.build()
        assert built["query"] == "dispatch"
        assert built["already_seen_deprioritized"] == 3

    def test_found_not_found(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.found(5).not_found_count(2)
        built = m.build()
        assert built["found"] == 5
        assert built["not_found_count"] == 2

    def test_indexing_fields(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.files_indexed(100).symbols_extracted(500)
        built = m.build()
        assert built["files_indexed"] == 100
        assert built["symbols_extracted"] == 500

    def test_extra_for_one_offs(self):
        from sylvan.tools.base.meta import ToolMeta

        m = ToolMeta()
        m.extra("custom_key", "custom_value")
        built = m.build()
        assert built["custom_key"] == "custom_value"

    def test_chaining(self):
        from sylvan.tools.base.meta import ToolMeta

        built = ToolMeta().repo("r").repo_id(1).results_count(5).query("test").token_efficiency(50, 200).build()
        assert built["repo"] == "r"
        assert built["repo_id"] == 1
        assert built["results_count"] == 5
        assert built["query"] == "test"
        assert built["token_efficiency"]["returned"] == 50

    def test_contextvar_roundtrip(self):
        from sylvan.tools.base.meta import ToolMeta, get_meta, reset_meta, set_meta

        m = ToolMeta()
        m.repo("from_context")
        token = set_meta(m)
        try:
            retrieved = get_meta()
            assert retrieved._repo == "from_context"
        finally:
            reset_meta(token)

    def test_get_meta_without_set_returns_fresh(self):
        from sylvan.tools.base.meta import get_meta

        m = get_meta()
        assert m._repo is None


class TestToolExecuteContinued:
    @pytest.mark.asyncio
    async def test_handle_not_implemented(self):
        class _TestNotImpl(Tool):
            name = "test_not_impl"
            description = "test"

        tool = _TestNotImpl()
        with pytest.raises(NotImplementedError):
            await tool.execute({})

        _registry.pop("test_not_impl", None)
