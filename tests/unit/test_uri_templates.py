"""Unit tests for RFC 6570 URI template extensions."""

from __future__ import annotations

from lauren_mcp.server._uri import (
    coerce_params,
    compile_uri_template,
    match_uri,
)


class TestBasicPlaceholder:
    def test_single_segment(self):
        compiled = compile_uri_template("/items/{id}")
        assert match_uri(compiled, "/items/42") == {"id": "42"}

    def test_single_segment_rejects_slashes(self):
        compiled = compile_uri_template("/items/{id}")
        assert match_uri(compiled, "/items/a/b") is None

    def test_no_match_returns_none(self):
        compiled = compile_uri_template("/items/{id}")
        assert match_uri(compiled, "/other/42") is None

    def test_custom_scheme(self):
        compiled = compile_uri_template("notes://{name}")
        assert match_uri(compiled, "notes://shopping") == {"name": "shopping"}


class TestMultiSegment:
    def test_plus_operator_spans_slashes(self):
        compiled = compile_uri_template("/files/{+path}")
        assert match_uri(compiled, "/files/a/b/c.txt") == {"path": "a/b/c.txt"}

    def test_star_modifier_spans_slashes(self):
        compiled = compile_uri_template("/files/{path*}")
        assert match_uri(compiled, "/files/a/b/c.txt") == {"path": "a/b/c.txt"}


class TestQueryParams:
    def test_query_params_extracted(self):
        compiled = compile_uri_template("/search/{topic}{?page,size}")
        assert compiled.query_params == ("page", "size")
        result = match_uri(compiled, "/search/python?page=2&size=10")
        assert result == {"topic": "python", "page": "2", "size": "10"}

    def test_query_params_optional(self):
        compiled = compile_uri_template("/search/{topic}{?page}")
        assert match_uri(compiled, "/search/python") == {"topic": "python"}

    def test_undeclared_query_params_ignored(self):
        compiled = compile_uri_template("/search/{topic}{?page}")
        result = match_uri(compiled, "/search/x?page=1&evil=1")
        assert result == {"topic": "x", "page": "1"}


class TestTypeCoercion:
    def test_int_coercion(self):
        assert coerce_params({"page": "3"}, {"page": int}) == {"page": 3}

    def test_float_coercion(self):
        assert coerce_params({"score": "1.5"}, {"score": float}) == {"score": 1.5}

    def test_bool_coercion(self):
        assert coerce_params({"flag": "true"}, {"flag": bool}) == {"flag": True}
        assert coerce_params({"flag": "0"}, {"flag": bool}) == {"flag": False}

    def test_optional_int_coercion(self):
        assert coerce_params({"page": "3"}, {"page": int | None}) == {"page": 3}

    def test_unannotated_stays_string(self):
        assert coerce_params({"x": "3"}, {}) == {"x": "3"}


class TestHandlerIntegration:
    async def test_resource_read_with_query_and_multiseg(self):
        from lauren_mcp import mcp_resource
        from lauren_mcp._types import JsonRpcRequest
        from lauren_mcp.server._handlers import make_resources_read_handler
        from lauren_mcp.server._meta import MCP_RESOURCE_META

        class Server:
            @mcp_resource("/files/{+path}{?version}")
            async def read_file(self, path: str, version: int = 1) -> str:
                return f"{path}@v{version}"

        meta = getattr(Server.read_file, MCP_RESOURCE_META)
        handler = make_resources_read_handler(Server(), [meta])
        req = JsonRpcRequest(
            method="resources/read",
            id=1,
            params={"uri": "/files/a/b.txt?version=7"},
        )
        result = await handler(req)
        assert result["contents"][0]["text"] == "a/b.txt@v7"
