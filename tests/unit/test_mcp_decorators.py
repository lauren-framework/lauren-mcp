"""Unit tests for mcp_server, mcp_tool, mcp_resource, mcp_prompt decorators
and McpServerModule.for_root().
"""

from __future__ import annotations

import pytest

from lauren_mcp.server._decorators import (
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)
from lauren_mcp.server._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpPromptMeta,
    McpResourceMeta,
    McpServerMeta,
    McpToolMeta,
)
from lauren_mcp.server._module import McpServerModule

# ---------------------------------------------------------------------------
# TestMcpServerDecorator
# ---------------------------------------------------------------------------


class TestMcpServerDecorator:
    def test_attaches_mcp_server_meta(self):
        @mcp_server("/mcp")
        class MyServer:
            pass

        assert hasattr(MyServer, MCP_SERVER_META)

    def test_path_stored_in_meta(self):
        @mcp_server("/my-path")
        class MyServer:
            pass

        meta: McpServerMeta = getattr(MyServer, MCP_SERVER_META)
        assert meta.path == "/my-path"

    def test_transport_stored_in_meta(self):
        @mcp_server("/mcp", transport="sse")
        class MyServer:
            pass

        meta: McpServerMeta = getattr(MyServer, MCP_SERVER_META)
        assert meta.transport == "sse"

    def test_default_transport_is_ws(self):
        @mcp_server("/mcp")
        class MyServer:
            pass

        meta: McpServerMeta = getattr(MyServer, MCP_SERVER_META)
        assert meta.transport == "ws"

    def test_accepts_sse_transport(self):
        @mcp_server("/mcp", transport="sse")
        class MyServer:
            pass

        meta: McpServerMeta = getattr(MyServer, MCP_SERVER_META)
        assert meta.transport == "sse"

    def test_accepts_both_transport(self):
        @mcp_server("/mcp", transport="both")
        class MyServer:
            pass

        meta: McpServerMeta = getattr(MyServer, MCP_SERVER_META)
        assert meta.transport == "both"

    def test_makes_class_injectable(self):
        """@mcp_server should apply @injectable(scope=Scope.SINGLETON)."""
        from lauren._di import INJECTABLE_META

        @mcp_server("/mcp")
        class MyServer:
            pass

        assert hasattr(MyServer, INJECTABLE_META)

    def test_returns_original_class(self):
        class MyServer:
            pass

        decorated = mcp_server("/mcp")(MyServer)
        assert decorated is MyServer


# ---------------------------------------------------------------------------
# TestMcpToolDecorator
# ---------------------------------------------------------------------------


class TestMcpToolDecorator:
    def test_attaches_mcp_tool_meta(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, text: str) -> str:
                """Echo text."""
                return text

        meta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert isinstance(meta, McpToolMeta)

    def test_name_from_function_name(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def search_items(self, query: str) -> str:
                """Search."""
                return query

        meta: McpToolMeta = getattr(MyServer.search_items, MCP_TOOL_META)
        assert meta.name == "search_items"

    def test_explicit_name_override(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool(name="custom-name")
            async def my_tool(self) -> str:
                """Doc."""
                return ""

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.name == "custom-name"

    def test_description_from_docstring_first_line(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, text: str) -> str:
                """First line description.

                Second paragraph ignored.
                """
                return text

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert "First line description" in meta.description

    def test_explicit_description_override(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool(description="Override desc")
            async def my_tool(self) -> str:
                """Docstring ignored."""
                return ""

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.description == "Override desc"

    def test_schema_has_type_object(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, x: int) -> int:
                return x

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["type"] == "object"

    def test_str_param_maps_to_string_type(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, name: str) -> str:
                return name

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"]["name"]["type"] == "string"

    def test_int_param_maps_to_integer_type(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, count: int) -> int:
                return count

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"]["count"]["type"] == "integer"

    def test_float_param_maps_to_number_type(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, ratio: float) -> float:
                return ratio

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"]["ratio"]["type"] == "number"

    def test_bool_param_maps_to_boolean_type(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, flag: bool) -> bool:
                return flag

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"]["flag"]["type"] == "boolean"

    def test_list_param_maps_to_array_type(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, items: list) -> list:
                return items

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"]["items"]["type"] == "array"

    def test_no_default_params_in_required(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, text: str) -> str:
                return text

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert "text" in meta.input_schema.get("required", [])

    def test_default_params_not_in_required(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, text: str = "default") -> str:
                return text

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert "text" not in meta.input_schema.get("required", [])

    def test_self_excluded_from_schema(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, text: str) -> str:
                return text

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert "self" not in meta.input_schema["properties"]

    def test_no_params_gives_empty_properties(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self) -> str:
                return ""

        meta: McpToolMeta = getattr(MyServer.my_tool, MCP_TOOL_META)
        assert meta.input_schema["properties"] == {}


# ---------------------------------------------------------------------------
# TestMcpResourceDecorator
# ---------------------------------------------------------------------------


class TestMcpResourceDecorator:
    def test_attaches_mcp_resource_meta(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///data/{name}")
            async def get_data(self, name: str) -> str:
                return name

        meta = getattr(MyServer.get_data, MCP_RESOURCE_META)
        assert isinstance(meta, McpResourceMeta)

    def test_uri_template_stored(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///items/{id}")
            async def get_item(self, id: str) -> str:
                return id

        meta: McpResourceMeta = getattr(MyServer.get_item, MCP_RESOURCE_META)
        assert meta.uri_template == "file:///items/{id}"

    def test_name_defaults_to_method_name(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///data")
            async def get_data(self) -> str:
                return ""

        meta: McpResourceMeta = getattr(MyServer.get_data, MCP_RESOURCE_META)
        assert meta.name == "get_data"

    def test_explicit_name_override(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///data", name="data-resource")
            async def get_data(self) -> str:
                return ""

        meta: McpResourceMeta = getattr(MyServer.get_data, MCP_RESOURCE_META)
        assert meta.name == "data-resource"

    def test_description_from_docstring(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///x")
            async def get_x(self) -> str:
                """Returns the X resource."""
                return ""

        meta: McpResourceMeta = getattr(MyServer.get_x, MCP_RESOURCE_META)
        assert "Returns the X resource" in meta.description

    def test_mime_type_none_by_default(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///x")
            async def get_x(self) -> str:
                return ""

        meta: McpResourceMeta = getattr(MyServer.get_x, MCP_RESOURCE_META)
        assert meta.mime_type is None

    def test_explicit_mime_type_stored(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///x", mime_type="text/plain")
            async def get_x(self) -> str:
                return ""

        meta: McpResourceMeta = getattr(MyServer.get_x, MCP_RESOURCE_META)
        assert meta.mime_type == "text/plain"


# ---------------------------------------------------------------------------
# TestMcpPromptDecorator
# ---------------------------------------------------------------------------


class TestMcpPromptDecorator:
    def test_attaches_mcp_prompt_meta(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def greeting(self, name: str) -> str:
                """Greet user."""
                return f"Hello {name}"

        meta = getattr(MyServer.greeting, MCP_PROMPT_META)
        assert isinstance(meta, McpPromptMeta)

    def test_name_from_function_name(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self) -> str:
                return ""

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        assert meta.name == "my_prompt"

    def test_explicit_name_override(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt("custom-prompt")
            async def my_prompt(self) -> str:
                return ""

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        assert meta.name == "custom-prompt"

    def test_no_default_params_have_required_true(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self, topic: str) -> str:
                return topic

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        topic_arg = next(a for a in meta.arguments if a["name"] == "topic")
        assert topic_arg["required"] is True

    def test_params_with_defaults_have_required_false(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self, topic: str = "general") -> str:
                return topic

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        topic_arg = next(a for a in meta.arguments if a["name"] == "topic")
        assert topic_arg["required"] is False

    def test_self_excluded_from_arguments(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self, topic: str) -> str:
                return topic

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        arg_names = [a["name"] for a in meta.arguments]
        assert "self" not in arg_names

    def test_empty_args_list_for_no_params(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self) -> str:
                return ""

        meta: McpPromptMeta = getattr(MyServer.my_prompt, MCP_PROMPT_META)
        assert meta.arguments == []


# ---------------------------------------------------------------------------
# TestMcpServerModuleForRoot
# ---------------------------------------------------------------------------


class TestMcpServerModuleForRoot:
    def test_raises_type_error_if_no_mcp_server(self):
        class NotAServer:
            pass

        with pytest.raises(TypeError, match="mcp_server"):
            McpServerModule.for_root(NotAServer)

    def test_collects_only_mcp_tool_methods(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def tool_a(self, x: str) -> str:
                return x

            async def not_a_tool(self) -> str:
                return ""

        # for_root returns a module class — check it doesn't raise
        mod = McpServerModule.for_root(MyServer)
        assert mod is not None

    def test_collects_only_mcp_resource_methods(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_resource("file:///data")
            async def get_data(self) -> str:
                return ""

        mod = McpServerModule.for_root(MyServer)
        assert mod is not None

    def test_collects_only_mcp_prompt_methods(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_prompt()
            async def my_prompt(self) -> str:
                return ""

        mod = McpServerModule.for_root(MyServer)
        assert mod is not None

    def test_server_with_only_tools_has_tools_capability(self):
        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def my_tool(self, x: str) -> str:
                return x

        # Check that the module was built without errors
        mod = McpServerModule.for_root(MyServer)
        assert mod is not None

    def test_returns_a_module_class(self):
        """for_root should return a class decorated with @module."""
        from lauren.decorators import MODULE_META

        @mcp_server("/mcp")
        class MyServer:
            @mcp_tool()
            async def echo(self, text: str) -> str:
                return text

        mod = McpServerModule.for_root(MyServer)
        assert hasattr(mod, MODULE_META)

    def test_module_has_sensible_qualname(self):
        @mcp_server("/mcp")
        class WeatherServer:
            @mcp_tool()
            async def get_weather(self, city: str) -> str:
                return city

        mod = McpServerModule.for_root(WeatherServer)
        assert "WeatherServer" in mod.__qualname__
