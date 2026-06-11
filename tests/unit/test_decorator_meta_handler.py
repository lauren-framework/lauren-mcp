"""Unit tests for decorator/meta/handler changes:
- title field on tools, resources, and prompts
- ResourceAnnotations on resources
- _validate_tool_name
- structured_output / auto-detection of output schema
"""

from __future__ import annotations

import dataclasses
import warnings
from typing import Any

import pytest

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import _validate_tool_name, mcp_prompt, mcp_resource, mcp_tool
from lauren_mcp.server._handlers import (
    _tool_list_entry,
    make_prompts_list_handler,
    make_resources_list_handler,
)
from lauren_mcp.server._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_TOOL_META,
    McpPromptMeta,
    McpResourceMeta,
)

# ---------------------------------------------------------------------------
# Optional dependency: ResourceAnnotations (added by types agent)
# ---------------------------------------------------------------------------

try:
    from lauren_mcp._types import ResourceAnnotations

    _RA_AVAILABLE = True
except ImportError:
    ResourceAnnotations = None  # type: ignore[assignment,misc]
    _RA_AVAILABLE = False

# ---------------------------------------------------------------------------
# Optional dependency: Pydantic
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel

    _PYDANTIC_AVAILABLE = True

    # Module-level pydantic model so get_type_hints() can resolve it in
    # test_pydantic_return_auto_detected (locally-defined classes are not
    # in the function's __globals__ and cannot be resolved by get_type_hints).
    class _PydanticOutputModel(BaseModel):  # type: ignore[misc]
        name: str
        value: int

except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]
    _PYDANTIC_AVAILABLE = False
    _PydanticOutputModel = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class HitResult:
    url: str
    score: float


# ---------------------------------------------------------------------------
# title field — @mcp_tool
# ---------------------------------------------------------------------------


def test_mcp_tool_title_stored_in_meta() -> None:
    @mcp_tool(title="My Tool")
    async def my_tool(self) -> str: ...

    meta = getattr(my_tool, MCP_TOOL_META)
    assert meta.title == "My Tool"


def test_mcp_tool_no_title_defaults_to_none() -> None:
    @mcp_tool()
    async def my_tool(self) -> str: ...

    meta = getattr(my_tool, MCP_TOOL_META)
    assert meta.title is None


def test_tool_list_entry_includes_title() -> None:
    @mcp_tool(name="find", title="Find Items", description="desc")
    async def find(self) -> str: ...

    meta = getattr(find, MCP_TOOL_META)
    entry = _tool_list_entry(meta)
    assert entry["title"] == "Find Items"
    assert entry["name"] == "find"


def test_tool_list_entry_omits_title_when_none() -> None:
    @mcp_tool(name="find", description="desc")
    async def find(self) -> str: ...

    meta = getattr(find, MCP_TOOL_META)
    entry = _tool_list_entry(meta)
    assert "title" not in entry


# ---------------------------------------------------------------------------
# title field — @mcp_resource
# ---------------------------------------------------------------------------


def test_mcp_resource_title_stored_in_meta() -> None:
    @mcp_resource("files://{path}", title="File Contents")
    async def read_file(self, path: str) -> str: ...

    meta = getattr(read_file, MCP_RESOURCE_META)
    assert meta.title == "File Contents"


async def test_resources_list_handler_includes_title() -> None:
    res = McpResourceMeta(
        uri_template="files://{path}",
        name="read_file",
        description=None,
        mime_type=None,
        method_name="read_file",
        title="File Contents",
    )
    handler = make_resources_list_handler([res])
    req = JsonRpcRequest(method="resources/list", id=1)
    result = await handler(req)
    assert result["resources"][0]["title"] == "File Contents"


async def test_resources_list_handler_omits_title_when_none() -> None:
    res = McpResourceMeta(
        uri_template="files://{path}",
        name="read_file",
        description=None,
        mime_type=None,
        method_name="read_file",
    )
    handler = make_resources_list_handler([res])
    req = JsonRpcRequest(method="resources/list", id=1)
    result = await handler(req)
    assert "title" not in result["resources"][0]


# ---------------------------------------------------------------------------
# title field — @mcp_prompt
# ---------------------------------------------------------------------------


def test_mcp_prompt_title_stored_in_meta() -> None:
    @mcp_prompt(title="Summarise")
    async def summarise(self, doc: str) -> str: ...

    meta = getattr(summarise, MCP_PROMPT_META)
    assert meta.title == "Summarise"


async def test_prompts_list_handler_includes_title() -> None:
    prompt = McpPromptMeta(
        name="summarise",
        description=None,
        arguments=[],
        method_name="summarise",
        title="Summarise Document",
    )
    handler = make_prompts_list_handler([prompt])
    req = JsonRpcRequest(method="prompts/list", id=1)
    result = await handler(req)
    assert result["prompts"][0]["title"] == "Summarise Document"


async def test_prompts_list_handler_omits_title_when_none() -> None:
    prompt = McpPromptMeta(
        name="summarise",
        description=None,
        arguments=[],
        method_name="summarise",
    )
    handler = make_prompts_list_handler([prompt])
    req = JsonRpcRequest(method="prompts/list", id=1)
    result = await handler(req)
    assert "title" not in result["prompts"][0]


# ---------------------------------------------------------------------------
# ResourceAnnotations on @mcp_resource
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RA_AVAILABLE, reason="ResourceAnnotations not yet in _types.py")
def test_mcp_resource_annotations_stored_in_meta() -> None:
    ann = ResourceAnnotations(audience=["user"])  # type: ignore[call-arg]

    @mcp_resource("items://{id}", annotations=ann)
    async def get_item(self, id: str) -> str: ...

    meta = getattr(get_item, MCP_RESOURCE_META)
    assert meta.annotations is ann
    assert meta.annotations.audience == ["user"]


@pytest.mark.skipif(not _RA_AVAILABLE, reason="ResourceAnnotations not yet in _types.py")
async def test_resources_list_handler_includes_annotations() -> None:
    ann = ResourceAnnotations(audience=["user"], priority=0.8)  # type: ignore[call-arg]
    res = McpResourceMeta(
        uri_template="items://{id}",
        name="get_item",
        description=None,
        mime_type=None,
        method_name="get_item",
        annotations=ann,
    )
    handler = make_resources_list_handler([res])
    req = JsonRpcRequest(method="resources/list", id=1)
    result = await handler(req)
    assert result["resources"][0]["annotations"] == {"audience": ["user"], "priority": 0.8}


@pytest.mark.skipif(not _RA_AVAILABLE, reason="ResourceAnnotations not yet in _types.py")
async def test_resources_list_handler_omits_annotations_when_none() -> None:
    res = McpResourceMeta(
        uri_template="items://{id}",
        name="get_item",
        description=None,
        mime_type=None,
        method_name="get_item",
    )
    handler = make_resources_list_handler([res])
    req = JsonRpcRequest(method="resources/list", id=1)
    result = await handler(req)
    assert "annotations" not in result["resources"][0]


# ---------------------------------------------------------------------------
# _validate_tool_name
# ---------------------------------------------------------------------------


def test_validate_tool_name_valid_simple() -> None:
    _validate_tool_name("search")  # no error


def test_validate_tool_name_valid_complex() -> None:
    _validate_tool_name("search-files_v2.3")  # no error


def test_validate_tool_name_valid_single_char() -> None:
    _validate_tool_name("x")  # no error


def test_validate_tool_name_valid_128_chars() -> None:
    _validate_tool_name("a" * 128)  # no error


def test_validate_tool_name_empty_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _validate_tool_name("")


def test_validate_tool_name_too_long_raises() -> None:
    with pytest.raises(ValueError, match="128"):
        _validate_tool_name("a" * 129)


def test_validate_tool_name_space_raises() -> None:
    with pytest.raises(ValueError, match="invalid characters"):
        _validate_tool_name("my tool")


def test_validate_tool_name_comma_raises() -> None:
    with pytest.raises(ValueError, match="invalid characters"):
        _validate_tool_name("tool,one")


def test_validate_tool_name_leading_dot_warns() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _validate_tool_name(".hidden")
    assert len(w) == 1
    assert "discouraged" in str(w[0].message)


def test_validate_tool_name_trailing_dash_warns() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _validate_tool_name("tool-")
    assert len(w) == 1


def test_validate_tool_name_strict_false_skips_error() -> None:
    _validate_tool_name("my tool name with spaces", strict=False)  # no error


# ---------------------------------------------------------------------------
# @mcp_tool with invalid name raises ValueError at decoration time
# ---------------------------------------------------------------------------


def test_mcp_tool_invalid_name_raises() -> None:
    with pytest.raises(ValueError, match="invalid characters"):

        @mcp_tool(name="bad name with spaces")
        async def bad(self) -> str: ...


def test_mcp_tool_too_long_name_raises() -> None:
    with pytest.raises(ValueError, match="128"):

        @mcp_tool(name="a" * 129)
        async def long_name(self) -> str: ...


def test_mcp_tool_strict_false_allows_bad_name() -> None:
    @mcp_tool(name="bad name", strict=False)
    async def tool(self) -> str: ...

    # No error raised


# ---------------------------------------------------------------------------
# structured_output / auto-detection of output schema
# ---------------------------------------------------------------------------


def test_structured_output_true_on_str_generates_schema() -> None:
    @mcp_tool(structured_output=True)
    async def ping(self) -> str: ...

    meta = getattr(ping, MCP_TOOL_META)
    assert meta.output_schema == {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }


def test_structured_output_none_on_str_no_schema() -> None:
    """str return with default structured_output=None does NOT auto-generate schema."""

    @mcp_tool()
    async def greet(self) -> str: ...

    meta = getattr(greet, MCP_TOOL_META)
    assert meta.output_schema is None


def test_dataclass_return_auto_detected() -> None:
    @mcp_tool()
    async def search(self, query: str) -> HitResult: ...

    meta = getattr(search, MCP_TOOL_META)
    assert meta.output_schema is not None
    assert meta.output_schema["type"] == "object"
    assert "url" in meta.output_schema["properties"]
    assert "score" in meta.output_schema["properties"]


def test_structured_output_false_disables_auto_detect() -> None:
    @mcp_tool(structured_output=False)
    async def search(self, query: str) -> HitResult: ...

    meta = getattr(search, MCP_TOOL_META)
    assert meta.output_schema is None


def test_explicit_output_schema_overrides_auto() -> None:
    explicit: dict[str, Any] = {"type": "object", "properties": {"x": {"type": "number"}}}

    @mcp_tool(output_schema=explicit)
    async def tool(self) -> HitResult: ...

    meta = getattr(tool, MCP_TOOL_META)
    assert meta.output_schema == explicit


@pytest.mark.skipif(not _PYDANTIC_AVAILABLE, reason="pydantic not installed")
def test_pydantic_return_auto_detected() -> None:
    # Uses _PydanticOutputModel defined at module scope so get_type_hints()
    # can resolve the return annotation via the function's __globals__.
    @mcp_tool()
    async def get_model(self) -> _PydanticOutputModel: ...  # type: ignore[name-defined]

    meta = getattr(get_model, MCP_TOOL_META)
    assert meta.output_schema is not None
    assert "properties" in meta.output_schema
    assert "name" in meta.output_schema["properties"]
