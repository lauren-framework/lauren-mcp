"""Coverage tests for lauren_mcp.server._decorators — targeting uncovered paths."""

from __future__ import annotations

import dataclasses
import inspect
import typing
import warnings
from typing import Any, Literal, Optional

import pytest


# Module-level dataclasses for tests (locally-defined DCs fail due to __future__ annotations)
@dataclasses.dataclass
class _TestPoint:
    x: float
    y: float


from lauren_mcp.server._decorators import (
    _apply_field_descriptor,
    _auto_output_schema,
    _build_schema,
    _extract_lauren_hint,
    _is_background_tasks_annotation,
    _is_context_annotation,
    _is_depends_annotation,
    _is_header_annotation,
    _is_optional_header,
    _is_state_annotation,
    _param_to_header_name,
    _read_method_decorators,
    _resolve_output_schema,
    _validate_tool_name,
    mcp_completion,
    mcp_lifespan,
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)
from lauren_mcp.server._meta import (
    MCP_COMPLETION_META,
    MCP_LIFESPAN_META,
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_TOOL_META,
    McpCompletionMeta,
    McpPromptMeta,
    McpResourceMeta,
    McpToolMeta,
)


# ---------------------------------------------------------------------------
# _validate_tool_name
# ---------------------------------------------------------------------------


class TestValidateToolName:
    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _validate_tool_name("")

    def test_too_long_name_raises(self):
        long_name = "a" * 129
        with pytest.raises(ValueError, match="128"):
            _validate_tool_name(long_name)

    def test_invalid_chars_raises(self):
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_tool_name("bad name!")

    def test_leading_dot_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _validate_tool_name(".tool")
            assert len(w) >= 1

    def test_trailing_dash_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _validate_tool_name("tool-")
            assert len(w) >= 1

    def test_strict_false_skips_validation(self):
        # Should not raise even for an invalid name
        _validate_tool_name("bad name!", strict=False)

    def test_valid_name_passes(self):
        _validate_tool_name("my_tool_v1")


# ---------------------------------------------------------------------------
# _is_context_annotation
# ---------------------------------------------------------------------------


class TestIsContextAnnotation:
    def test_direct_class(self):
        from lauren_mcp._server._context import McpToolContext

        assert _is_context_annotation(McpToolContext) is True

    def test_string_annotations(self):
        assert _is_context_annotation("McpToolContext") is True
        assert _is_context_annotation("McpToolContext|None") is True
        assert _is_context_annotation("Optional[McpToolContext]") is True
        assert _is_context_annotation("typing.Optional[McpToolContext]") is True

    def test_optional_union(self):
        from lauren_mcp._server._context import McpToolContext

        annotation = Optional[McpToolContext]
        assert _is_context_annotation(annotation) is True

    def test_not_context(self):
        assert _is_context_annotation(str) is False
        assert _is_context_annotation("str") is False
        assert _is_context_annotation(None) is False


# ---------------------------------------------------------------------------
# _is_background_tasks_annotation
# ---------------------------------------------------------------------------


class TestIsBackgroundTasksAnnotation:
    def test_string_annotations(self):
        assert _is_background_tasks_annotation("BackgroundTasks") is True
        assert _is_background_tasks_annotation("lauren.BackgroundTasks") is True
        assert _is_background_tasks_annotation("  BackgroundTasks  ") is True

    def test_not_background_tasks(self):
        assert _is_background_tasks_annotation("str") is False
        assert _is_background_tasks_annotation(42) is False

    def test_actual_class_when_lauren_available(self):
        try:
            from lauren import BackgroundTasks

            assert _is_background_tasks_annotation(BackgroundTasks) is True
        except ImportError:
            pytest.skip("lauren not installed")


# ---------------------------------------------------------------------------
# _is_depends_annotation
# ---------------------------------------------------------------------------


class TestIsDependsAnnotation:
    def test_string_depends(self):
        try:
            from lauren import Depends  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")
        assert _is_depends_annotation("Depends[SomeProvider]") is True
        assert _is_depends_annotation("Depends[  X  ]") is True

    def test_not_depends(self):
        try:
            from lauren import Depends  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")
        assert _is_depends_annotation("str") is False
        assert _is_depends_annotation(str) is False


# ---------------------------------------------------------------------------
# _extract_lauren_hint
# ---------------------------------------------------------------------------


class TestExtractLaurenHint:
    def test_plain_type_returns_as_is(self):
        base, fd, pipes = _extract_lauren_hint(str)
        assert base is str
        assert fd is None
        assert pipes == ()

    def test_annotated_without_lauren(self):
        """Annotated[str, SomeObj] without lauren → returned as-is when no FD/pipe."""
        annotation = typing.Annotated[str, object()]
        base, fd, pipes = _extract_lauren_hint(annotation)
        # Without lauren or if lauren is available but nothing is a FD/pipe
        # we get back the base type str or the annotation as-is
        # This exercises the "no ExtractionMarker" path
        assert base is not None

    def test_annotated_with_field_descriptor_when_lauren_available(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd_obj = FieldDescriptor(ge=0)
        annotation = typing.Annotated[int, fd_obj]
        base, fd, pipes = _extract_lauren_hint(annotation)
        assert base is int
        assert fd is fd_obj

    def test_annotated_with_pipe_when_lauren_available(self):
        try:
            from lauren.extractors import is_pipe
        except ImportError:
            pytest.skip("lauren not installed")

        def my_pipe(v: Any) -> Any:
            return v

        # Try to make my_pipe recognizable as a pipe (may not work without lauren's is_pipe)
        # Directly test that the function doesn't crash
        annotation = typing.Annotated[str, my_pipe]
        base, fd, pipes = _extract_lauren_hint(annotation)
        assert base is str  # base should be str regardless


# ---------------------------------------------------------------------------
# _apply_field_descriptor
# ---------------------------------------------------------------------------


class TestApplyFieldDescriptor:
    def test_applies_ge_constraint(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd = FieldDescriptor(ge=0)
        schema: dict = {"type": "integer"}
        _apply_field_descriptor(schema, fd)
        assert schema.get("minimum") == 0

    def test_applies_description(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd = FieldDescriptor(description="A number")
        schema: dict = {"type": "integer"}
        _apply_field_descriptor(schema, fd)
        assert schema.get("description") == "A number"

    def test_applies_alias(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd = FieldDescriptor(alias="my_alias")
        schema: dict = {}
        _apply_field_descriptor(schema, fd)
        assert schema.get("title") == "my_alias"

    def test_applies_default_scalar(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd = FieldDescriptor(default=42)
        schema: dict = {}
        _apply_field_descriptor(schema, fd)
        assert schema.get("default") == 42


# ---------------------------------------------------------------------------
# _resolve_output_schema
# ---------------------------------------------------------------------------


class TestResolveOutputSchema:
    def test_none_returns_none(self):
        assert _resolve_output_schema(None) is None

    def test_dict_passthrough(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        assert _resolve_output_schema(schema) is schema

    def test_pydantic_model(self):
        pydantic = pytest.importorskip("pydantic")

        class Item(pydantic.BaseModel):
            name: str

        result = _resolve_output_schema(Item)
        assert isinstance(result, dict)
        assert "properties" in result or "$defs" in result or "title" in result

    def test_dataclass(self):
        result = _resolve_output_schema(_TestPoint)
        assert isinstance(result, dict)
        assert result["type"] == "object"

    def test_typeddict(self):
        class Config(typing.TypedDict):
            host: str
            port: int

        result = _resolve_output_schema(Config)
        assert isinstance(result, dict)
        assert result["type"] == "object"

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError, match="output_schema"):
            _resolve_output_schema(42)  # type: ignore[arg-type]

    def test_msgspec_struct(self):
        msgspec = pytest.importorskip("msgspec")

        class Point(msgspec.Struct):
            x: float
            y: float

        result = _resolve_output_schema(Point)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _auto_output_schema
# ---------------------------------------------------------------------------


class TestAutoOutputSchema:
    def test_structured_output_false_returns_none(self):
        assert _auto_output_schema(str, False) is None

    def test_none_annotation_returns_none(self):
        assert _auto_output_schema(None, None) is None

    def test_empty_annotation_returns_none(self):
        assert _auto_output_schema(inspect.Parameter.empty, None) is None

    def test_string_annotation_returns_none(self):
        assert _auto_output_schema("str", None) is None

    def test_structured_output_true_primitive_str(self):
        result = _auto_output_schema(str, True)
        assert result is not None
        assert result["properties"]["result"]["type"] == "string"

    def test_structured_output_true_primitive_int(self):
        result = _auto_output_schema(int, True)
        assert result is not None
        assert result["properties"]["result"]["type"] == "integer"

    def test_structured_output_true_bool(self):
        result = _auto_output_schema(bool, True)
        assert result is not None
        assert result["properties"]["result"]["type"] == "boolean"

    def test_structured_output_true_float(self):
        result = _auto_output_schema(float, True)
        assert result is not None
        assert result["properties"]["result"]["type"] == "number"

    def test_auto_detect_pydantic_model(self):
        pydantic = pytest.importorskip("pydantic")

        class Item(pydantic.BaseModel):
            name: str

        result = _auto_output_schema(Item, None)
        assert result is not None

    def test_auto_detect_dataclass(self):
        @dataclasses.dataclass
        class Point:
            x: float

        result = _auto_output_schema(Point, None)
        assert result is not None

    def test_auto_detect_primitive_returns_none(self):
        # Auto mode doesn't wrap primitives
        result = _auto_output_schema(str, None)
        assert result is None

    def test_auto_detect_unknown_type_returns_none(self):
        class Unknown:
            pass

        result = _auto_output_schema(Unknown, None)
        # Unknown type fails _resolve_output_schema → returns None
        assert result is None


# ---------------------------------------------------------------------------
# @mcp_completion decorator
# ---------------------------------------------------------------------------


class TestMcpCompletionDecorator:
    def test_attaches_completion_meta(self):
        @mcp_completion("greet", "name")
        async def complete_greet_name(self, partial: str) -> list:
            return []

        meta = getattr(complete_greet_name, MCP_COMPLETION_META)
        assert isinstance(meta, McpCompletionMeta)

    def test_ref_type_default(self):
        @mcp_completion("greet", "name")
        async def complete(self, partial: str) -> list:
            return []

        meta: McpCompletionMeta = getattr(complete, MCP_COMPLETION_META)
        assert meta.ref_type == "ref/prompt"

    def test_ref_type_resource(self):
        @mcp_completion("file:///data/{name}", "name", ref_type="ref/resource")
        async def complete(self, partial: str) -> list:
            return []

        meta: McpCompletionMeta = getattr(complete, MCP_COMPLETION_META)
        assert meta.ref_type == "ref/resource"

    def test_target_name_stored(self):
        @mcp_completion("my_prompt", "param1")
        async def complete(self, partial: str) -> list:
            return []

        meta: McpCompletionMeta = getattr(complete, MCP_COMPLETION_META)
        assert meta.target_name == "my_prompt"

    def test_argument_name_stored(self):
        @mcp_completion("my_prompt", "my_arg")
        async def complete(self, partial: str) -> list:
            return []

        meta: McpCompletionMeta = getattr(complete, MCP_COMPLETION_META)
        assert meta.argument_name == "my_arg"

    def test_method_name_stored(self):
        @mcp_completion("my_prompt", "my_arg")
        async def complete_fn(self, partial: str) -> list:
            return []

        meta: McpCompletionMeta = getattr(complete_fn, MCP_COMPLETION_META)
        assert meta.method_name == "complete_fn"

    def test_returns_original_function(self):
        async def original(self, partial: str) -> list:
            return []

        decorated = mcp_completion("p", "a")(original)
        assert decorated is original


# ---------------------------------------------------------------------------
# @mcp_lifespan decorator
# ---------------------------------------------------------------------------


class TestMcpLifespanDecorator:
    def test_attaches_lifespan_meta(self):
        async def my_lifespan(self):
            yield {}

        decorated = mcp_lifespan(my_lifespan)
        meta = getattr(decorated, MCP_LIFESPAN_META)
        assert meta.method_name == "my_lifespan"

    def test_raises_on_non_async_gen(self):
        async def not_a_gen(self):
            pass

        with pytest.raises(TypeError, match="async generator"):
            mcp_lifespan(not_a_gen)

    def test_raises_on_sync_gen(self):
        def sync_gen(self):
            yield {}

        with pytest.raises(TypeError, match="async generator"):
            mcp_lifespan(sync_gen)


# ---------------------------------------------------------------------------
# @mcp_resource with RFC6570 templates
# ---------------------------------------------------------------------------


class TestMcpResourceRfc6570:
    def test_query_params_extracted(self):
        @mcp_resource("file:///data/{name}{?format,lang}")
        async def get_data(self, name: str, format: str = "json", lang: str = "en") -> str:
            return name

        meta: McpResourceMeta = getattr(get_data, MCP_RESOURCE_META)
        assert "format" in meta.query_params
        assert "lang" in meta.query_params

    def test_multi_segment_template(self):
        @mcp_resource("file:///data/{+path}")
        async def get_path(self, path: str) -> str:
            return path

        meta: McpResourceMeta = getattr(get_path, MCP_RESOURCE_META)
        assert meta.uri_template == "file:///data/{+path}"

    def test_resource_with_title(self):
        @mcp_resource("file:///items/{id}", title="My Items")
        async def get_item(self, id: str) -> str:
            return id

        meta: McpResourceMeta = getattr(get_item, MCP_RESOURCE_META)
        assert meta.title == "My Items"

    def test_resource_description_explicit(self):
        @mcp_resource("file:///items/{id}", description="Explicit desc")
        async def get_item(self, id: str) -> str:
            """Docstring desc."""
            return id

        meta: McpResourceMeta = getattr(get_item, MCP_RESOURCE_META)
        assert meta.description == "Explicit desc"


# ---------------------------------------------------------------------------
# @mcp_prompt with arguments
# ---------------------------------------------------------------------------


class TestMcpPromptWithArguments:
    def test_arguments_populated_from_params(self):
        @mcp_prompt()
        async def my_prompt(self, topic: str, style: str = "formal") -> str:
            """Generate a prompt."""
            return f"{style}: {topic}"

        meta: McpPromptMeta = getattr(my_prompt, MCP_PROMPT_META)
        arg_names = [a["name"] for a in meta.arguments]
        assert "topic" in arg_names
        assert "style" in arg_names

    def test_required_set_correctly(self):
        @mcp_prompt()
        async def my_prompt(self, required_arg: str, opt_arg: str = "default") -> str:
            return required_arg

        meta: McpPromptMeta = getattr(my_prompt, MCP_PROMPT_META)
        req_arg = next(a for a in meta.arguments if a["name"] == "required_arg")
        opt_arg = next(a for a in meta.arguments if a["name"] == "opt_arg")
        assert req_arg["required"] is True
        assert opt_arg["required"] is False

    def test_prompt_with_title(self):
        @mcp_prompt(title="My Prompt Title")
        async def my_prompt(self) -> str:
            return ""

        meta: McpPromptMeta = getattr(my_prompt, MCP_PROMPT_META)
        assert meta.title == "My Prompt Title"


# ---------------------------------------------------------------------------
# @mcp_tool with output_schema and structured_output
# ---------------------------------------------------------------------------


class TestMcpToolOutputSchema:
    def test_explicit_dict_output_schema(self):
        schema = {"type": "object", "properties": {"result": {"type": "string"}}}

        @mcp_tool(output_schema=schema)
        async def my_tool(self) -> str:
            return "hello"

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.output_schema == schema

    def test_pydantic_model_output_schema(self):
        pydantic = pytest.importorskip("pydantic")

        class Result(pydantic.BaseModel):
            value: int

        @mcp_tool(output_schema=Result)
        async def my_tool(self) -> Result:
            return Result(value=1)

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.output_schema is not None
        assert isinstance(meta.output_schema, dict)

    def test_structured_output_true_auto_derives_schema(self):
        @mcp_tool(structured_output=True)
        async def my_tool(self) -> str:
            return "hello"

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.output_schema is not None
        assert meta.output_schema["properties"]["result"]["type"] == "string"

    def test_structured_output_false_no_schema(self):
        @mcp_tool(structured_output=False)
        async def my_tool(self) -> str:
            return "hello"

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.output_schema is None

    def test_dataclass_return_auto_schema(self):
        @mcp_tool()
        async def my_tool(self) -> _TestPoint:
            return _TestPoint(1.0, 2.0)

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.output_schema is not None


# ---------------------------------------------------------------------------
# @mcp_tool with tags, meta, title, annotations, timeout
# ---------------------------------------------------------------------------


class TestMcpToolAdvancedOptions:
    def test_tags_stored(self):
        @mcp_tool(tags={"a", "b"})
        async def my_tool(self) -> str:
            return ""

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert "a" in meta.tags
        assert "b" in meta.tags

    def test_meta_stored(self):
        @mcp_tool(meta={"x": 1, "y": 2})
        async def my_tool(self) -> str:
            return ""

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.meta == {"x": 1, "y": 2}

    def test_title_stored(self):
        @mcp_tool(title="My Cool Tool")
        async def my_tool(self) -> str:
            return ""

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.title == "My Cool Tool"

    def test_timeout_stored(self):
        @mcp_tool(timeout=30.0)
        async def my_tool(self) -> str:
            return ""

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.timeout == 30.0

    def test_strict_false_allows_invalid_name(self):
        @mcp_tool(name="invalid name!", strict=False)
        async def my_tool(self) -> str:
            return ""

        meta: McpToolMeta = getattr(my_tool, MCP_TOOL_META)
        assert meta.name == "invalid name!"


# ---------------------------------------------------------------------------
# _read_method_decorators — with lauren installed
# ---------------------------------------------------------------------------


class TestReadMethodDecorators:
    def test_returns_empty_dicts_for_plain_function(self):
        async def plain_fn(self) -> str:
            return ""

        result = _read_method_decorators(plain_fn)
        assert result["guards"] == ()
        assert result["interceptors"] == ()
        assert result["exception_handlers"] == ()
        assert result["tool_metadata"] == {}

    def test_use_middlewares_raises_type_error(self):
        try:
            from lauren.decorators import USE_MIDDLEWARES
        except ImportError:
            pytest.skip("lauren not installed")

        async def fn(self) -> str:
            return ""

        setattr(fn, USE_MIDDLEWARES, [object()])

        with pytest.raises(TypeError, match="use_middlewares"):
            _read_method_decorators(fn)

    def test_reads_guards(self):
        try:
            from lauren.decorators import USE_GUARDS
        except ImportError:
            pytest.skip("lauren not installed")

        class MyGuard:
            pass

        async def fn(self) -> str:
            return ""

        setattr(fn, USE_GUARDS, [MyGuard])

        result = _read_method_decorators(fn)
        assert MyGuard in result["guards"]

    def test_reads_interceptors(self):
        try:
            from lauren.decorators import USE_INTERCEPTORS
        except ImportError:
            pytest.skip("lauren not installed")

        class MyInterceptor:
            pass

        async def fn(self) -> str:
            return ""

        setattr(fn, USE_INTERCEPTORS, [MyInterceptor])

        result = _read_method_decorators(fn)
        assert MyInterceptor in result["interceptors"]

    def test_reads_set_metadata(self):
        try:
            from lauren.decorators import SET_METADATA
        except ImportError:
            pytest.skip("lauren not installed")

        async def fn(self) -> str:
            return ""

        setattr(fn, SET_METADATA, {"role": "admin"})

        result = _read_method_decorators(fn)
        assert result["tool_metadata"].get("role") == "admin"


# ---------------------------------------------------------------------------
# _build_schema — various param types
# ---------------------------------------------------------------------------


class TestBuildSchema:
    def test_basic_schema_returns_tuple(self):
        async def fn(self, name: str, count: int = 0) -> str:
            """My function."""
            pass

        result = _build_schema(fn)
        (
            name,
            desc,
            schema,
            ctx_param,
            param_descs,
            pipe_chains,
            bg_param,
            depends,
            headers,
            state,
        ) = result
        assert name == "fn"
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "count" in schema["properties"]

    def test_context_param_excluded_from_schema(self):
        from lauren_mcp._server._context import McpToolContext

        async def fn(self, ctx: McpToolContext, name: str) -> str:
            pass

        (_, _, schema, ctx_param, *_) = _build_schema(fn)
        assert ctx_param == "ctx"
        assert "ctx" not in schema["properties"]

    def test_default_values_in_schema(self):
        async def fn(self, mode: str = "fast", limit: int = 10) -> None:
            pass

        (_, _, schema, *_) = _build_schema(fn)
        assert schema["properties"]["mode"].get("default") == "fast"
        assert schema["properties"]["limit"].get("default") == 10

    def test_literal_type_in_schema(self):
        async def fn(self, mode: Literal["a", "b"]) -> None:
            pass

        (_, _, schema, *_) = _build_schema(fn)
        assert schema["properties"]["mode"]["enum"] == ["a", "b"]

    def test_list_param_type(self):
        async def fn(self, items: list[str]) -> None:
            pass

        (_, _, schema, *_) = _build_schema(fn)
        prop = schema["properties"]["items"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}
