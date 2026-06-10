"""Unit tests for tool annotations, timeout/tags/meta, and structured output."""

from __future__ import annotations

import asyncio
import base64

import pytest

from lauren_mcp import (
    BlobResource,
    ResourceResult,
    TextContent,
    ToolAnnotations,
    ToolOutput,
    mcp_resource,
    mcp_tool,
)
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import (
    make_resources_read_handler,
    make_tools_call_handler,
    make_tools_list_handler,
)
from lauren_mcp.server._meta import MCP_RESOURCE_META, MCP_TOOL_META


def req(method: str, **params) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=1, params=params)


class TestToolAnnotations:
    async def test_annotations_in_tools_list(self):
        @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
        async def search(self, q: str) -> list:
            """Search."""

        meta = getattr(search, MCP_TOOL_META)
        handler = make_tools_list_handler([meta])
        result = await handler(req("tools/list"))
        annotations = result["tools"][0]["annotations"]
        assert annotations == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        }

    async def test_no_annotations_key_when_absent(self):
        @mcp_tool()
        async def search(self, q: str) -> list:
            """Search."""

        meta = getattr(search, MCP_TOOL_META)
        handler = make_tools_list_handler([meta])
        result = await handler(req("tools/list"))
        assert "annotations" not in result["tools"][0]

    def test_spec_defaults(self):
        a = ToolAnnotations()
        assert a.readOnlyHint is False
        assert a.destructiveHint is True
        assert a.idempotentHint is False
        assert a.openWorldHint is True


class TestTagsAndMeta:
    async def test_tags_and_meta_in_list(self):
        @mcp_tool(tags={"admin", "beta"}, meta={"version": "2.0"})
        async def purge(self) -> str:
            """Purge."""

        meta = getattr(purge, MCP_TOOL_META)
        handler = make_tools_list_handler([meta])
        entry = (await handler(req("tools/list")))["tools"][0]
        assert entry["tags"] == ["admin", "beta"]  # sorted
        assert entry["_meta"] == {"version": "2.0"}

    async def test_empty_tags_meta_omitted(self):
        @mcp_tool()
        async def simple(self) -> str:
            """Simple."""

        meta = getattr(simple, MCP_TOOL_META)
        entry = (await make_tools_list_handler([meta])(req("tools/list")))["tools"][0]
        assert "tags" not in entry
        assert "_meta" not in entry


class TestTimeout:
    async def test_timeout_fails_slow_tool(self):
        class Server:
            @mcp_tool(timeout=0.05)
            async def slow(self) -> str:
                await asyncio.sleep(1.0)
                return "never"

        meta = getattr(Server.slow, MCP_TOOL_META)
        handler = make_tools_call_handler(Server(), [meta])
        with pytest.raises(ValueError, match="timed out"):
            await handler(req("tools/call", name="slow"))

    async def test_fast_tool_unaffected(self):
        class Server:
            @mcp_tool(timeout=5.0)
            async def fast(self) -> str:
                return "done"

        meta = getattr(Server.fast, MCP_TOOL_META)
        handler = make_tools_call_handler(Server(), [meta])
        result = await handler(req("tools/call", name="fast"))
        assert result["content"][0]["text"] == "done"


class TestStructuredOutput:
    async def test_dict_returns_structured_content(self):
        class Server:
            @mcp_tool()
            async def stats(self) -> dict:
                return {"count": 3}

        meta = getattr(Server.stats, MCP_TOOL_META)
        handler = make_tools_call_handler(Server(), [meta])
        result = await handler(req("tools/call", name="stats"))
        assert result["structuredContent"] == {"count": 3}
        assert result["content"][0]["type"] == "text"

    async def test_str_has_no_structured_content(self):
        class Server:
            @mcp_tool()
            async def greet(self) -> str:
                return "hi"

        meta = getattr(Server.greet, MCP_TOOL_META)
        result = await make_tools_call_handler(Server(), [meta])(req("tools/call", name="greet"))
        assert "structuredContent" not in result

    async def test_list_wrapped_under_result_key(self):
        class Server:
            @mcp_tool()
            async def items(self) -> list:
                return [1, 2]

        meta = getattr(Server.items, MCP_TOOL_META)
        result = await make_tools_call_handler(Server(), [meta])(req("tools/call", name="items"))
        assert result["structuredContent"] == {"result": [1, 2]}

    async def test_tool_output_full_control(self):
        class Server:
            @mcp_tool()
            async def rich(self) -> ToolOutput:
                return ToolOutput(
                    content=[TextContent(text="shown to user")],
                    structured_content={"parsed": True},
                )

        meta = getattr(Server.rich, MCP_TOOL_META)
        result = await make_tools_call_handler(Server(), [meta])(req("tools/call", name="rich"))
        assert result["content"] == [{"type": "text", "text": "shown to user"}]
        assert result["structuredContent"] == {"parsed": True}
        assert result["isError"] is False

    async def test_output_schema_in_list_and_validated(self):
        schema = {"type": "object", "required": ["count"], "properties": {"count": {}}}

        class Server:
            @mcp_tool(output_schema=schema)
            async def stats(self) -> dict:
                return {"wrong_key": 1}

        meta = getattr(Server.stats, MCP_TOOL_META)
        entry = (await make_tools_list_handler([meta])(req("tools/list")))["tools"][0]
        assert entry["outputSchema"] == schema

        with pytest.raises(ValueError, match="missing required"):
            await make_tools_call_handler(Server(), [meta])(req("tools/call", name="stats"))


class TestBinaryResources:
    async def test_bytes_become_base64_blob(self):
        payload = b"\x89PNG fake image"

        class Server:
            @mcp_resource("/img/{name}", mime_type="image/png")
            async def image(self, name: str) -> bytes:
                return payload

        meta = getattr(Server.image, MCP_RESOURCE_META)
        handler = make_resources_read_handler(Server(), [meta])
        result = await handler(req("resources/read", uri="/img/logo"))
        content = result["contents"][0]
        assert content["mimeType"] == "image/png"
        assert base64.b64decode(content["blob"]) == payload
        assert "text" not in content

    async def test_bytes_default_mime(self):
        class Server:
            @mcp_resource("/raw/{name}")
            async def raw(self, name: str) -> bytes:
                return b"data"

        meta = getattr(Server.raw, MCP_RESOURCE_META)
        result = await make_resources_read_handler(Server(), [meta])(
            req("resources/read", uri="/raw/x")
        )
        assert result["contents"][0]["mimeType"] == "application/octet-stream"

    async def test_blob_resource_type(self):
        class Server:
            @mcp_resource("/doc/{name}")
            async def doc(self, name: str) -> BlobResource:
                return BlobResource(data=b"pdf-bytes", mime_type="application/pdf")

        meta = getattr(Server.doc, MCP_RESOURCE_META)
        result = await make_resources_read_handler(Server(), [meta])(
            req("resources/read", uri="/doc/a")
        )
        content = result["contents"][0]
        assert content["mimeType"] == "application/pdf"
        assert base64.b64decode(content["blob"]) == b"pdf-bytes"

    async def test_str_still_text(self):
        class Server:
            @mcp_resource("/t/{name}", mime_type="text/plain")
            async def t(self, name: str) -> str:
                return "hello"

        meta = getattr(Server.t, MCP_RESOURCE_META)
        result = await make_resources_read_handler(Server(), [meta])(
            req("resources/read", uri="/t/x")
        )
        assert result["contents"][0]["text"] == "hello"
        assert "blob" not in result["contents"][0]

    async def test_resource_result_multi_item(self):
        class Server:
            @mcp_resource("/multi/{name}")
            async def multi(self, name: str) -> ResourceResult:
                return ResourceResult(contents=["text part", b"binary part"])

        meta = getattr(Server.multi, MCP_RESOURCE_META)
        result = await make_resources_read_handler(Server(), [meta])(
            req("resources/read", uri="/multi/x")
        )
        assert result["contents"][0]["text"] == "text part"
        assert base64.b64decode(result["contents"][1]["blob"]) == b"binary part"
