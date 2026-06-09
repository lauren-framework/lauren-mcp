"""Unit tests for lauren_mcp.server._handlers — all six handler factories."""
from __future__ import annotations

import json
import pytest

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import (
    make_prompts_get_handler,
    make_prompts_list_handler,
    make_resources_list_handler,
    make_resources_read_handler,
    make_tools_call_handler,
    make_tools_list_handler,
)
from lauren_mcp.server._meta import McpPromptMeta, McpResourceMeta, McpToolMeta


# ---------------------------------------------------------------------------
# Shared fake server
# ---------------------------------------------------------------------------


class FakeServer:
    async def greet(self, name: str) -> str:
        return f"Hello, {name}!"

    async def get_page(self, uri: str) -> str:
        return f"Content of {uri}"

    async def make_greeting(self, style: str = "formal") -> list[dict]:
        return [{"role": "user", "content": {"type": "text", "text": f"{style} hello"}}]

    async def get_item(self, item_id: str) -> str:
        return f"Item {item_id}"

    async def returns_dict(self, key: str = "default") -> dict:
        return {"key": key, "value": 42}

    async def returns_list_result(self) -> list:
        return [{"a": 1}, {"b": 2}]

    async def prompt_string(self, topic: str = "python") -> str:
        return f"Tell me about {topic}"

    async def prompt_dict(self, style: str = "formal") -> dict:
        return {
            "description": "A greeting prompt",
            "messages": [
                {"role": "user", "content": {"type": "text", "text": f"{style} hello"}}
            ],
        }


FAKE = FakeServer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_meta(
    name: str,
    method_name: str,
    description: str = "A test tool",
    input_schema: dict | None = None,
) -> McpToolMeta:
    return McpToolMeta(
        name=name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
        method_name=method_name,
    )


def _make_resource_meta(
    uri_template: str,
    name: str,
    method_name: str,
    description: str | None = None,
    mime_type: str | None = None,
) -> McpResourceMeta:
    return McpResourceMeta(
        uri_template=uri_template,
        name=name,
        description=description,
        mime_type=mime_type,
        method_name=method_name,
    )


def _make_prompt_meta(
    name: str,
    method_name: str,
    description: str | None = None,
    arguments: list[dict] | None = None,
) -> McpPromptMeta:
    return McpPromptMeta(
        name=name,
        description=description,
        arguments=arguments or [],
        method_name=method_name,
    )


def _req(method: str, params: dict | None = None) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, params=params, id=1)


# ---------------------------------------------------------------------------
# make_tools_list_handler
# ---------------------------------------------------------------------------


class TestMakeToolsListHandler:
    async def test_returns_dict_with_tools_key(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_list_handler(tools)
        result = await handler(_req("tools/list"))
        assert "tools" in result

    async def test_tools_list_has_correct_length(self):
        tools = [
            _make_tool_meta("greet", "greet"),
            _make_tool_meta("get_page", "get_page"),
        ]
        handler = make_tools_list_handler(tools)
        result = await handler(_req("tools/list"))
        assert len(result["tools"]) == 2

    async def test_each_tool_has_name_description_input_schema(self):
        tools = [_make_tool_meta("greet", "greet", description="Greets someone")]
        handler = make_tools_list_handler(tools)
        result = await handler(_req("tools/list"))
        tool = result["tools"][0]
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool

    async def test_empty_tools_list_returns_empty_list(self):
        handler = make_tools_list_handler([])
        result = await handler(_req("tools/list"))
        assert result["tools"] == []

    async def test_tool_name_matches_meta(self):
        meta = _make_tool_meta("my_tool", "greet")
        handler = make_tools_list_handler([meta])
        result = await handler(_req("tools/list"))
        assert result["tools"][0]["name"] == "my_tool"

    async def test_tool_description_matches_meta(self):
        meta = _make_tool_meta("greet", "greet", description="Greets a person")
        handler = make_tools_list_handler([meta])
        result = await handler(_req("tools/list"))
        assert result["tools"][0]["description"] == "Greets a person"

    async def test_tool_input_schema_matches_meta(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        meta = _make_tool_meta("greet", "greet", input_schema=schema)
        handler = make_tools_list_handler([meta])
        result = await handler(_req("tools/list"))
        assert result["tools"][0]["inputSchema"] == schema


# ---------------------------------------------------------------------------
# make_tools_call_handler
# ---------------------------------------------------------------------------


class TestMakeToolsCallHandler:
    async def test_calls_correct_method_with_arguments(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "greet", "arguments": {"name": "Alice"}})
        )
        # Check text content is correct
        assert result["content"][0]["text"] == "Hello, Alice!"

    async def test_returns_dict_with_content_and_is_error(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "greet", "arguments": {"name": "Bob"}})
        )
        assert "content" in result
        assert "isError" in result

    async def test_string_result_wrapped_in_text_content(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "greet", "arguments": {"name": "Eve"}})
        )
        content = result["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert isinstance(content[0]["text"], str)

    async def test_is_error_is_false_for_successful_call(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "greet", "arguments": {"name": "X"}})
        )
        assert result["isError"] is False

    async def test_dict_result_wrapped_as_json_string(self):
        tools = [_make_tool_meta("returns_dict", "returns_dict")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "returns_dict", "arguments": {"key": "hello"}})
        )
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert parsed["key"] == "hello"

    async def test_list_result_wrapped_as_json_string(self):
        tools = [_make_tool_meta("returns_list_result", "returns_list_result")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "returns_list_result", "arguments": {}})
        )
        text = result["content"][0]["text"]
        parsed = json.loads(text)
        assert isinstance(parsed, list)

    async def test_unknown_tool_name_raises_value_error(self):
        handler = make_tools_call_handler(FAKE, [])
        with pytest.raises(ValueError, match="Unknown tool"):
            await handler(_req("tools/call", {"name": "nonexistent", "arguments": {}}))

    async def test_arguments_dict_is_unpacked_as_kwargs(self):
        tools = [_make_tool_meta("greet", "greet")]
        handler = make_tools_call_handler(FAKE, tools)
        result = await handler(
            _req("tools/call", {"name": "greet", "arguments": {"name": "Charlie"}})
        )
        assert "Charlie" in result["content"][0]["text"]

    async def test_missing_arguments_uses_empty_dict(self):
        """If arguments key is missing from params, defaults to empty dict."""
        tools = [_make_tool_meta("returns_list_result", "returns_list_result")]
        handler = make_tools_call_handler(FAKE, tools)
        # returns_list_result takes no args, so empty dict is fine
        result = await handler(
            _req("tools/call", {"name": "returns_list_result"})
        )
        assert "content" in result


# ---------------------------------------------------------------------------
# make_resources_list_handler
# ---------------------------------------------------------------------------


class TestMakeResourcesListHandler:
    async def test_returns_dict_with_resources_key(self):
        resources = [_make_resource_meta("/pages/{uri}", "pages", "get_page")]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        assert "resources" in result

    async def test_each_resource_has_uri_and_name(self):
        resources = [_make_resource_meta("/items/{id}", "items", "get_item")]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        r = result["resources"][0]
        assert "uri" in r
        assert "name" in r

    async def test_empty_list_returns_empty_resources(self):
        handler = make_resources_list_handler([])
        result = await handler(_req("resources/list"))
        assert result["resources"] == []

    async def test_description_included_when_present(self):
        resources = [
            _make_resource_meta(
                "/items/{id}", "items", "get_item", description="Item resource"
            )
        ]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        assert result["resources"][0]["description"] == "Item resource"

    async def test_mime_type_included_when_present(self):
        resources = [
            _make_resource_meta(
                "/pages/{uri}", "pages", "get_page", mime_type="text/html"
            )
        ]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        assert result["resources"][0]["mimeType"] == "text/html"

    async def test_description_absent_when_none(self):
        resources = [_make_resource_meta("/items/{id}", "items", "get_item")]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        assert "description" not in result["resources"][0]

    async def test_multiple_resources_all_listed(self):
        resources = [
            _make_resource_meta("/a/{x}", "a", "get_item"),
            _make_resource_meta("/b/{y}", "b", "get_page"),
        ]
        handler = make_resources_list_handler(resources)
        result = await handler(_req("resources/list"))
        assert len(result["resources"]) == 2


# ---------------------------------------------------------------------------
# make_resources_read_handler
# ---------------------------------------------------------------------------


class TestMakeResourcesReadHandler:
    async def test_matches_exact_uri(self):
        # Use a static URI that maps to a method taking no extra kwargs.
        # We create a resource whose method takes no path vars.
        resources = [_make_resource_meta("/status", "status", "returns_list_result")]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/status"}))
        assert "contents" in result

    async def test_extracts_path_variables_from_template(self):
        resources = [_make_resource_meta("/items/{item_id}", "items", "get_item")]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/items/42"}))
        assert result["contents"][0]["text"] == "Item 42"

    async def test_unknown_uri_raises_value_error(self):
        handler = make_resources_read_handler(FAKE, [])
        with pytest.raises(ValueError, match="No resource matches URI"):
            await handler(_req("resources/read", {"uri": "/unknown/path"}))

    async def test_multiple_resources_picks_correct_one_by_uri(self):
        resources = [
            _make_resource_meta("/items/{item_id}", "items", "get_item"),
            _make_resource_meta("/pages/{uri}", "pages", "get_page"),
        ]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/pages/about"}))
        assert "about" in result["contents"][0]["text"]

    async def test_string_result_returns_uri_and_text(self):
        resources = [_make_resource_meta("/items/{item_id}", "items", "get_item")]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/items/99"}))
        content = result["contents"][0]
        assert content["uri"] == "/items/99"
        assert "text" in content

    async def test_mime_type_included_in_content_when_set(self):
        resources = [
            _make_resource_meta(
                "/items/{item_id}", "items", "get_item", mime_type="application/json"
            )
        ]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/items/5"}))
        assert result["contents"][0]["mimeType"] == "application/json"

    async def test_dict_result_returned_as_list_with_dict(self):
        """If method returns a dict, it's wrapped in a list."""
        resources = [_make_resource_meta("/dict/{key}", "dict", "returns_dict")]
        handler = make_resources_read_handler(FAKE, resources)
        result = await handler(_req("resources/read", {"uri": "/dict/hello"}))
        assert isinstance(result["contents"], list)
        assert isinstance(result["contents"][0], dict)


# ---------------------------------------------------------------------------
# make_prompts_list_handler
# ---------------------------------------------------------------------------


class TestMakePromptsListHandler:
    async def test_returns_dict_with_prompts_key(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert "prompts" in result

    async def test_each_prompt_has_name_field(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert "name" in result["prompts"][0]

    async def test_empty_list_returns_empty_prompts(self):
        handler = make_prompts_list_handler([])
        result = await handler(_req("prompts/list"))
        assert result["prompts"] == []

    async def test_arguments_list_included_when_set(self):
        args = [{"name": "topic", "description": "The topic", "required": True}]
        prompts = [_make_prompt_meta("greeting", "prompt_string", arguments=args)]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert result["prompts"][0]["arguments"] == args

    async def test_description_included_when_set(self):
        prompts = [
            _make_prompt_meta("greeting", "prompt_string", description="A greeting prompt")
        ]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert result["prompts"][0]["description"] == "A greeting prompt"

    async def test_multiple_prompts_all_listed(self):
        prompts = [
            _make_prompt_meta("p1", "prompt_string"),
            _make_prompt_meta("p2", "prompt_dict"),
        ]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert len(result["prompts"]) == 2

    async def test_prompt_name_matches_meta(self):
        prompts = [_make_prompt_meta("my-prompt", "prompt_string")]
        handler = make_prompts_list_handler(prompts)
        result = await handler(_req("prompts/list"))
        assert result["prompts"][0]["name"] == "my-prompt"


# ---------------------------------------------------------------------------
# make_prompts_get_handler
# ---------------------------------------------------------------------------


class TestMakePromptsGetHandler:
    async def test_calls_correct_method(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {"topic": "AI"}}))
        # prompt_string returns "Tell me about AI"
        assert "AI" in result["messages"][0]["content"]["text"]

    async def test_passes_arguments_dict_to_method(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {"topic": "rockets"}}))
        assert "rockets" in result["messages"][0]["content"]["text"]

    async def test_returns_dict_with_messages_key_for_string_result(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {}}))
        assert "messages" in result

    async def test_unknown_prompt_name_raises_value_error(self):
        handler = make_prompts_get_handler(FAKE, [])
        with pytest.raises(ValueError, match="Unknown prompt"):
            await handler(_req("prompts/get", {"name": "no-such-prompt", "arguments": {}}))

    async def test_dict_result_returned_directly(self):
        """If method returns a dict, it's returned as-is (GetPromptResult shape)."""
        prompts = [_make_prompt_meta("greeting_dict", "prompt_dict")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(
            _req("prompts/get", {"name": "greeting_dict", "arguments": {"style": "casual"}})
        )
        # prompt_dict returns a full dict with description + messages
        assert "messages" in result
        assert result["description"] == "A greeting prompt"

    async def test_string_result_wrapped_in_user_message(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {"topic": "test"}}))
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"]["type"] == "text"

    async def test_empty_arguments_uses_method_defaults(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string")]
        handler = make_prompts_get_handler(FAKE, prompts)
        # prompt_string has default topic="python"
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {}}))
        assert "python" in result["messages"][0]["content"]["text"]

    async def test_returns_description_for_string_result(self):
        prompts = [_make_prompt_meta("greeting", "prompt_string", description="My prompt")]
        handler = make_prompts_get_handler(FAKE, prompts)
        result = await handler(_req("prompts/get", {"name": "greeting", "arguments": {}}))
        assert result.get("description") == "My prompt"
