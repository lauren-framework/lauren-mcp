"""Unit tests for lauren_mcp._types and _version."""

from __future__ import annotations

import json

import pytest

from lauren_mcp._mcp_version import LATEST, STABLE, SUPPORTED
from lauren_mcp._types import (
    ImageContent,
    JsonRpcError,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    McpErrorCode,
    McpParseError,
    PromptArgument,
    PromptSchema,
    ResourceSchema,
    TextContent,
    ToolResult,
    ToolSchema,
    build_error_response,
    parse_message,
)

# ---------------------------------------------------------------------------
# TestJsonRpcRequest
# ---------------------------------------------------------------------------


class TestJsonRpcRequest:
    def test_to_json_includes_method(self):
        req = JsonRpcRequest(method="ping", id=1)
        obj = json.loads(req.to_json())
        assert obj["method"] == "ping"

    def test_to_json_includes_id(self):
        req = JsonRpcRequest(method="ping", id=42)
        obj = json.loads(req.to_json())
        assert obj["id"] == 42

    def test_to_json_includes_jsonrpc(self):
        req = JsonRpcRequest(method="ping", id=1)
        obj = json.loads(req.to_json())
        assert obj["jsonrpc"] == "2.0"

    def test_to_json_omits_none_params(self):
        req = JsonRpcRequest(method="ping", id=1, params=None)
        obj = json.loads(req.to_json())
        assert "params" not in obj

    def test_to_json_includes_params_when_set(self):
        req = JsonRpcRequest(method="tools/call", id=3, params={"name": "echo"})
        obj = json.loads(req.to_json())
        assert obj["params"] == {"name": "echo"}

    def test_to_json_includes_list_params(self):
        req = JsonRpcRequest(method="foo", id=5, params=["a", "b"])
        obj = json.loads(req.to_json())
        assert obj["params"] == ["a", "b"]

    def test_to_json_handles_string_id(self):
        req = JsonRpcRequest(method="ping", id="abc-123")
        obj = json.loads(req.to_json())
        assert obj["id"] == "abc-123"

    def test_to_json_handles_int_id(self):
        req = JsonRpcRequest(method="ping", id=99)
        obj = json.loads(req.to_json())
        assert obj["id"] == 99

    def test_to_json_includes_none_id(self):
        req = JsonRpcRequest(method="ping", id=None)
        obj = json.loads(req.to_json())
        assert obj["id"] is None

    def test_default_jsonrpc_is_20(self):
        req = JsonRpcRequest(method="ping")
        assert req.jsonrpc == "2.0"

    def test_default_id_is_none(self):
        req = JsonRpcRequest(method="ping")
        assert req.id is None


# ---------------------------------------------------------------------------
# TestJsonRpcNotification
# ---------------------------------------------------------------------------


class TestJsonRpcNotification:
    def test_to_json_has_no_id_field(self):
        notif = JsonRpcNotification(method="notifications/initialized")
        obj = json.loads(notif.to_json())
        assert "id" not in obj

    def test_to_json_method_present(self):
        notif = JsonRpcNotification(method="notifications/initialized")
        obj = json.loads(notif.to_json())
        assert obj["method"] == "notifications/initialized"

    def test_to_json_params_optional_omitted(self):
        notif = JsonRpcNotification(method="ping")
        obj = json.loads(notif.to_json())
        assert "params" not in obj

    def test_to_json_params_present_when_set(self):
        notif = JsonRpcNotification(method="ping", params={"reason": "idle"})
        obj = json.loads(notif.to_json())
        assert obj["params"] == {"reason": "idle"}

    def test_jsonrpc_field_is_20(self):
        notif = JsonRpcNotification(method="foo")
        obj = json.loads(notif.to_json())
        assert obj["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# TestJsonRpcResponse
# ---------------------------------------------------------------------------


class TestJsonRpcResponse:
    def test_to_json_has_id_and_result(self):
        resp = JsonRpcResponse(id=1, result={"ok": True})
        obj = json.loads(resp.to_json())
        assert obj["id"] == 1
        assert obj["result"] == {"ok": True}

    def test_result_can_be_dict(self):
        resp = JsonRpcResponse(id=2, result={"tools": []})
        obj = json.loads(resp.to_json())
        assert isinstance(obj["result"], dict)

    def test_result_can_be_list(self):
        resp = JsonRpcResponse(id=3, result=[1, 2, 3])
        obj = json.loads(resp.to_json())
        assert obj["result"] == [1, 2, 3]

    def test_result_can_be_string(self):
        resp = JsonRpcResponse(id=4, result="hello")
        obj = json.loads(resp.to_json())
        assert obj["result"] == "hello"

    def test_result_can_be_none(self):
        resp = JsonRpcResponse(id=5, result=None)
        obj = json.loads(resp.to_json())
        assert obj["result"] is None

    def test_jsonrpc_field_present(self):
        resp = JsonRpcResponse(id=1, result={})
        obj = json.loads(resp.to_json())
        assert obj["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# TestJsonRpcErrorResponse
# ---------------------------------------------------------------------------


class TestJsonRpcErrorResponse:
    def test_to_json_has_error_code_and_message(self):
        err = JsonRpcError(code=-32601, message="Method not found")
        resp = JsonRpcErrorResponse(id=1, error=err)
        obj = json.loads(resp.to_json())
        assert obj["error"]["code"] == -32601
        assert obj["error"]["message"] == "Method not found"

    def test_data_omitted_when_none(self):
        err = JsonRpcError(code=-32601, message="oops", data=None)
        resp = JsonRpcErrorResponse(id=1, error=err)
        obj = json.loads(resp.to_json())
        assert "data" not in obj["error"]

    def test_data_included_when_present(self):
        err = JsonRpcError(code=-32603, message="err", data={"type": "ValueError"})
        resp = JsonRpcErrorResponse(id=2, error=err)
        obj = json.loads(resp.to_json())
        assert obj["error"]["data"] == {"type": "ValueError"}

    def test_correct_jsonrpc_field(self):
        err = JsonRpcError(code=-32700, message="parse error")
        resp = JsonRpcErrorResponse(id=None, error=err)
        obj = json.loads(resp.to_json())
        assert obj["jsonrpc"] == "2.0"

    def test_id_propagated(self):
        err = JsonRpcError(code=-32600, message="bad req")
        resp = JsonRpcErrorResponse(id="req-abc", error=err)
        obj = json.loads(resp.to_json())
        assert obj["id"] == "req-abc"


# ---------------------------------------------------------------------------
# TestMcpErrorCode
# ---------------------------------------------------------------------------


class TestMcpErrorCode:
    def test_parse_error_value(self):
        assert McpErrorCode.PARSE_ERROR == -32700

    def test_invalid_request_value(self):
        assert McpErrorCode.INVALID_REQUEST == -32600

    def test_method_not_found_value(self):
        assert McpErrorCode.METHOD_NOT_FOUND == -32601

    def test_invalid_params_value(self):
        assert McpErrorCode.INVALID_PARAMS == -32602

    def test_internal_error_value(self):
        assert McpErrorCode.INTERNAL_ERROR == -32603

    def test_request_cancelled_value(self):
        assert McpErrorCode.REQUEST_CANCELLED == -32800

    def test_content_too_large_value(self):
        assert McpErrorCode.CONTENT_TOO_LARGE == -32801

    def test_all_seven_codes_defined(self):
        codes = list(McpErrorCode)
        assert len(codes) == 7


# ---------------------------------------------------------------------------
# TestParseMessage
# ---------------------------------------------------------------------------


class TestParseMessage:
    def _make(self, **kw) -> str:
        base = {"jsonrpc": "2.0"}
        base.update(kw)
        return json.dumps(base)

    def test_parses_request_with_int_id(self):
        raw = self._make(method="ping", id=1)
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.id == 1
        assert msg.method == "ping"

    def test_parses_request_with_string_id(self):
        raw = self._make(method="tools/list", id="req-abc")
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.id == "req-abc"

    def test_parses_request_with_null_id(self):
        raw = self._make(method="ping", id=None)
        msg = parse_message(raw)
        # Has "id" key => request
        assert isinstance(msg, JsonRpcRequest)
        assert msg.id is None

    def test_parses_notification_no_id(self):
        raw = self._make(method="notifications/initialized")
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)
        assert msg.method == "notifications/initialized"

    def test_parses_success_response(self):
        raw = self._make(id=5, result={"tools": []})
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.id == 5
        assert msg.result == {"tools": []}

    def test_parses_error_response(self):
        raw = self._make(id=3, error={"code": -32601, "message": "Not found"})
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcErrorResponse)
        assert msg.error.code == -32601
        assert msg.error.message == "Not found"

    def test_raises_mcp_parse_error_on_malformed_json(self):
        with pytest.raises(McpParseError, match="Invalid JSON"):
            parse_message("{not valid json}")

    def test_raises_mcp_parse_error_on_missing_jsonrpc(self):
        raw = json.dumps({"method": "ping", "id": 1})
        with pytest.raises(McpParseError, match="jsonrpc"):
            parse_message(raw)

    def test_raises_mcp_parse_error_on_wrong_jsonrpc_version(self):
        raw = json.dumps({"jsonrpc": "1.0", "method": "ping", "id": 1})
        with pytest.raises(McpParseError, match="jsonrpc"):
            parse_message(raw)

    def test_handles_bytes_input(self):
        raw = self._make(method="ping", id=10)
        msg = parse_message(raw.encode("utf-8"))
        assert isinstance(msg, JsonRpcRequest)
        assert msg.id == 10

    def test_handles_str_input(self):
        raw = self._make(id=7, result="ok")
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)

    def test_response_with_null_id(self):
        raw = json.dumps({"jsonrpc": "2.0", "id": None, "result": {}})
        msg = parse_message(raw)
        # "id" key is present with null value → no "method" key → treated as response
        assert isinstance(msg, JsonRpcResponse)
        assert msg.id is None

    def test_notification_with_params(self):
        raw = self._make(method="notify", params={"key": "value"})
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)
        assert msg.params == {"key": "value"}

    def test_raises_on_non_object_json(self):
        with pytest.raises(McpParseError):
            parse_message(json.dumps([1, 2, 3]))


# ---------------------------------------------------------------------------
# TestBuildErrorResponse
# ---------------------------------------------------------------------------


class TestBuildErrorResponse:
    def test_returns_correct_code(self):
        resp = build_error_response(1, McpErrorCode.PARSE_ERROR, "bad JSON")
        assert resp.error.code == -32700

    def test_returns_correct_message(self):
        resp = build_error_response(1, McpErrorCode.INTERNAL_ERROR, "boom")
        assert resp.error.message == "boom"

    def test_none_data_omitted_in_json(self):
        resp = build_error_response(1, McpErrorCode.INTERNAL_ERROR, "err", data=None)
        obj = json.loads(resp.to_json())
        assert "data" not in obj["error"]

    def test_non_none_data_included_in_json(self):
        resp = build_error_response(1, McpErrorCode.INTERNAL_ERROR, "err", data={"x": 1})
        obj = json.loads(resp.to_json())
        assert obj["error"]["data"] == {"x": 1}

    def test_id_propagated(self):
        resp = build_error_response(42, McpErrorCode.INVALID_PARAMS, "bad params")
        assert resp.id == 42

    def test_id_can_be_none(self):
        resp = build_error_response(None, McpErrorCode.PARSE_ERROR, "parse err")
        assert resp.id is None

    def test_all_mcp_error_codes_work(self):
        for code in McpErrorCode:
            resp = build_error_response(1, code, "test")
            assert resp.error.code == int(code)

    def test_int_code_works(self):
        resp = build_error_response(1, -32700, "parse error")
        assert resp.error.code == -32700

    def test_string_id_works(self):
        resp = build_error_response("req-1", McpErrorCode.METHOD_NOT_FOUND, "no method")
        assert resp.id == "req-1"


# ---------------------------------------------------------------------------
# TestContentTypes
# ---------------------------------------------------------------------------


class TestContentTypes:
    def test_text_content_type_is_text(self):
        tc = TextContent(text="hello")
        assert tc.type == "text"

    def test_text_content_stores_text(self):
        tc = TextContent(text="world")
        assert tc.text == "world"

    def test_image_content_type_is_image(self):
        ic = ImageContent(data="base64data", mimeType="image/png")
        assert ic.type == "image"

    def test_image_content_stores_data_and_mime(self):
        ic = ImageContent(data="abc123", mimeType="image/jpeg")
        assert ic.data == "abc123"
        assert ic.mimeType == "image/jpeg"

    def test_tool_schema_stores_input_schema_dict(self):
        ts = ToolSchema(
            name="echo",
            description="Echo text",
            inputSchema={"type": "object", "properties": {"text": {"type": "string"}}},
        )
        assert ts.inputSchema["type"] == "object"
        assert "text" in ts.inputSchema["properties"]

    def test_resource_schema_stores_uri_and_name(self):
        rs = ResourceSchema(uri="file:///data.txt", name="data")
        assert rs.uri == "file:///data.txt"
        assert rs.name == "data"

    def test_tool_result_defaults_not_error(self):
        tr = ToolResult()
        assert tr.isError is False

    def test_tool_result_content_defaults_empty_list(self):
        tr = ToolResult()
        assert tr.content == []

    def test_prompt_argument_default_not_required(self):
        arg = PromptArgument(name="topic")
        assert arg.required is False

    def test_prompt_schema_stores_name(self):
        ps = PromptSchema(name="my-prompt")
        assert ps.name == "my-prompt"


# ---------------------------------------------------------------------------
# TestVersionConstants
# ---------------------------------------------------------------------------


class TestVersionConstants:
    def test_latest_in_supported(self):
        assert LATEST in SUPPORTED

    def test_stable_in_supported(self):
        assert STABLE in SUPPORTED

    def test_latest_not_equal_stable(self):
        assert LATEST != STABLE

    def test_unknown_version_not_in_supported(self):
        assert "1999-01-01" not in SUPPORTED

    def test_supported_is_frozenset(self):
        assert isinstance(SUPPORTED, frozenset)

    def test_both_known_versions_present(self):
        assert "2025-03-26" in SUPPORTED
        assert "2024-11-05" in SUPPORTED

    def test_supported_has_at_least_two_versions(self):
        assert len(SUPPORTED) >= 2

    def test_latest_is_more_recent_than_stable(self):
        # simple lexicographic comparison works for ISO date strings
        assert LATEST > STABLE
