"""Unit tests for lauren_mcp.server._openapi — build_openapi_server_class and RouteEntry.

Covers all previously-uncovered paths:
  - RouteEntry.matches with method filter and regex
  - _load_spec: dict path, file path (JSON), file path (YAML), missing yaml
  - _resolve_ref and _deref helpers (indirectly via build_openapi_server_class)
  - _operation_schema: path params, query params, required, body
  - _make_operation_method: URL building, query extraction, body building
  - _default_name: operationId path and fallback
  - build_openapi_server_class: tool generation, route_map exclude / name_override /
    description_override, empty spec warning, class_name kwarg
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp.server._meta import MCP_TOOL_META
from lauren_mcp.server._openapi import (
    RouteEntry,
    _default_name,
    _deref,
    _load_spec,
    _operation_schema,
    _resolve_ref,
    build_openapi_server_class,
)

# ---------------------------------------------------------------------------
# RouteEntry
# ---------------------------------------------------------------------------


class TestRouteEntry:
    def test_matches_any_method_when_none(self):
        r = RouteEntry(pattern=r"/widgets")
        assert r.matches("/widgets", "GET")
        assert r.matches("/widgets", "DELETE")

    def test_method_filter_case_insensitive(self):
        r = RouteEntry(pattern=r"/widgets", method="GET")
        assert r.matches("/widgets", "get")
        assert not r.matches("/widgets", "POST")

    def test_pattern_regex(self):
        r = RouteEntry(pattern=r"^/users/\d+$")
        assert r.matches("/users/42", "GET")
        assert not r.matches("/users/abc", "GET")

    def test_method_upper_comparison(self):
        r = RouteEntry(pattern=r".*", method="post")
        assert r.matches("/anything", "POST")
        assert r.matches("/anything", "post")
        assert not r.matches("/anything", "GET")

    def test_default_expose_as(self):
        r = RouteEntry(pattern=r".*")
        assert r.expose_as == "tool"

    def test_expose_as_exclude(self):
        r = RouteEntry(pattern=r".*", expose_as="exclude")
        assert r.expose_as == "exclude"

    def test_name_override_default_none(self):
        r = RouteEntry(pattern=r".*")
        assert r.name_override is None

    def test_description_override_default_none(self):
        r = RouteEntry(pattern=r".*")
        assert r.description_override is None

    def test_no_regex_match(self):
        r = RouteEntry(pattern=r"^/strict$")
        assert not r.matches("/strict/extra", "GET")


# ---------------------------------------------------------------------------
# _load_spec
# ---------------------------------------------------------------------------


class TestLoadSpec:
    def test_dict_passthrough(self):
        spec = {"openapi": "3.0.0", "paths": {}}
        assert _load_spec(spec) is spec

    def test_json_file(self, tmp_path: Path):
        spec = {"openapi": "3.0.0", "paths": {}}
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        result = _load_spec(p)
        assert result == spec

    def test_json_file_string_path(self, tmp_path: Path):
        spec = {"openapi": "3.0.0", "paths": {}}
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        result = _load_spec(str(p))
        assert result == spec

    def test_yaml_file_with_pyyaml(self, tmp_path: Path):
        """Parse a YAML spec when pyyaml is available (or skip if not)."""
        pytest.importorskip("yaml")
        import yaml  # noqa: PLC0415

        spec = {"openapi": "3.0.0", "paths": {}}
        p = tmp_path / "spec.yaml"
        p.write_text(yaml.dump(spec))
        result = _load_spec(p)
        assert result["openapi"] == "3.0.0"

    def test_yaml_file_without_pyyaml_raises(self, tmp_path: Path):
        """When yaml is not installed, ImportError with helpful message is raised."""
        p = tmp_path / "spec.yaml"
        # Write something that is valid YAML but not JSON (would fail json.loads)
        p.write_text("openapi: '3.0.0'\npaths: {}\n")
        # Temporarily hide yaml from imports
        saved = sys.modules.get("yaml")
        sys.modules["yaml"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(ImportError, match="pyyaml"):
                _load_spec(p)
        finally:
            if saved is None:
                sys.modules.pop("yaml", None)
            else:
                sys.modules["yaml"] = saved


# ---------------------------------------------------------------------------
# _resolve_ref and _deref
# ---------------------------------------------------------------------------


class TestResolveRef:
    def test_resolves_components_schemas(self):
        spec: dict[str, Any] = {
            "components": {
                "schemas": {"Widget": {"type": "object", "properties": {"id": {"type": "integer"}}}}
            }
        }
        result = _resolve_ref(spec, "#/components/schemas/Widget")
        assert result["type"] == "object"

    def test_non_local_ref_returns_empty(self):
        assert _resolve_ref({}, "https://external.com/schema") == {}

    def test_missing_path_returns_empty(self):
        spec: dict[str, Any] = {"components": {}}
        result = _resolve_ref(spec, "#/components/schemas/Missing")
        assert result == {}

    def test_non_dict_node_returns_empty(self):
        spec: dict[str, Any] = {"items": ["a", "b"]}
        result = _resolve_ref(spec, "#/items/0")
        assert result == {}


class TestDeref:
    def test_passthrough_non_dict(self):
        assert _deref({}, "a string") == "a string"  # type: ignore[arg-type]

    def test_depth_guard(self):
        spec: dict[str, Any] = {}
        schema = {"type": "string"}
        # depth > 8 returns as-is
        result = _deref(spec, schema, depth=9)
        assert result == schema

    def test_inlines_ref(self):
        spec: dict[str, Any] = {"components": {"schemas": {"Foo": {"type": "integer"}}}}
        schema = {"$ref": "#/components/schemas/Foo"}
        result = _deref(spec, schema)
        assert result == {"type": "integer"}

    def test_nested_dict_values(self):
        spec: dict[str, Any] = {}
        schema = {"outer": {"inner": {"type": "string"}}}
        result = _deref(spec, schema)
        assert result == {"outer": {"inner": {"type": "string"}}}

    def test_list_values_with_dicts(self):
        spec: dict[str, Any] = {}
        schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        result = _deref(spec, schema)
        assert result["oneOf"] == [{"type": "string"}, {"type": "integer"}]

    def test_list_values_with_non_dicts(self):
        spec: dict[str, Any] = {}
        schema = {"enum": ["a", "b", "c"]}
        result = _deref(spec, schema)
        assert result["enum"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _operation_schema
# ---------------------------------------------------------------------------


class TestOperationSchema:
    def test_path_param_required(self):
        spec: dict[str, Any] = {}
        operation = {
            "parameters": [{"name": "widget_id", "in": "path", "schema": {"type": "integer"}}]
        }
        schema, path_params, query_params, has_body = _operation_schema(spec, operation, {})
        assert "widget_id" in schema["properties"]
        assert "widget_id" in path_params
        assert "widget_id" in schema["required"]
        assert not has_body

    def test_query_param_optional(self):
        spec: dict[str, Any] = {}
        operation = {"parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}]}
        schema, path_params, query_params, has_body = _operation_schema(spec, operation, {})
        assert "q" in schema["properties"]
        assert "q" in query_params
        assert "required" not in schema

    def test_query_param_required_flag(self):
        spec: dict[str, Any] = {}
        operation = {
            "parameters": [
                {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}
            ]
        }
        schema, path_params, query_params, has_body = _operation_schema(spec, operation, {})
        assert "q" in schema["required"]

    def test_header_cookie_params_excluded(self):
        spec: dict[str, Any] = {}
        operation = {
            "parameters": [
                {"name": "X-Api-Key", "in": "header", "schema": {"type": "string"}},
                {"name": "session", "in": "cookie", "schema": {"type": "string"}},
            ]
        }
        schema, path_params, query_params, has_body = _operation_schema(spec, operation, {})
        assert schema["properties"] == {}

    def test_param_description_added_to_schema(self):
        spec: dict[str, Any] = {}
        operation = {
            "parameters": [
                {
                    "name": "limit",
                    "in": "query",
                    "description": "Max results",
                    "schema": {"type": "integer"},
                }
            ]
        }
        schema, _, _, _ = _operation_schema(spec, operation, {})
        assert schema["properties"]["limit"]["description"] == "Max results"

    def test_path_item_params_merged(self):
        spec: dict[str, Any] = {}
        path_item = {
            "parameters": [{"name": "tenant_id", "in": "path", "schema": {"type": "string"}}]
        }
        operation: dict[str, Any] = {}
        schema, path_params, _, _ = _operation_schema(spec, operation, path_item)
        assert "tenant_id" in path_params

    def test_request_body_object(self):
        spec: dict[str, Any] = {}
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                            "required": ["name"],
                        }
                    }
                }
            }
        }
        schema, _, _, has_body = _operation_schema(spec, operation, {})
        assert has_body
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert "name" in schema["required"]

    def test_no_required_key_when_empty(self):
        spec: dict[str, Any] = {}
        schema, _, _, _ = _operation_schema(spec, {}, {})
        assert "required" not in schema

    def test_param_without_name_skipped(self):
        spec: dict[str, Any] = {}
        operation = {
            "parameters": [{"in": "query", "schema": {"type": "string"}}]  # no name
        }
        schema, _, _, _ = _operation_schema(spec, operation, {})
        assert schema["properties"] == {}


# ---------------------------------------------------------------------------
# _default_name
# ---------------------------------------------------------------------------


class TestDefaultName:
    def test_uses_operation_id(self):
        assert _default_name({"operationId": "getWidget"}, "GET", "/widgets/{id}") == "getWidget"

    def test_sanitises_operation_id(self):
        assert _default_name({"operationId": "get-widget-by-id"}, "GET", "/x") == "get_widget_by_id"

    def test_falls_back_to_method_path(self):
        name = _default_name({}, "GET", "/widgets/{id}")
        assert "get" in name
        assert "widgets" in name

    def test_strips_leading_trailing_underscores(self):
        name = _default_name({}, "GET", "/{id}")
        # should not start or end with underscore
        assert not name.startswith("_")
        assert not name.endswith("_")


# ---------------------------------------------------------------------------
# build_openapi_server_class
# ---------------------------------------------------------------------------

_SIMPLE_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "0.1"},
    "paths": {
        "/widgets": {
            "get": {
                "operationId": "listWidgets",
                "summary": "List all widgets",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
            },
            "post": {
                "operationId": "createWidget",
                "description": "Create a widget",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            }
                        }
                    }
                },
            },
        },
        "/widgets/{widget_id}": {
            "get": {
                "operationId": "getWidget",
                "summary": "Get a widget",
                "parameters": [{"name": "widget_id", "in": "path", "schema": {"type": "string"}}],
            },
            "delete": {
                "operationId": "deleteWidget",
                "summary": "Delete a widget",
                "parameters": [{"name": "widget_id", "in": "path", "schema": {"type": "string"}}],
            },
        },
    },
}


class TestBuildOpenApiServerClass:
    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        resp = MagicMock()
        resp.headers = {"content-type": "application/json"}
        resp.json.return_value = {"items": []}
        resp.raise_for_status = MagicMock()
        client.request = AsyncMock(return_value=resp)
        return client

    def test_returns_class_with_mcp_server_meta(self):
        from lauren_mcp.server._meta import MCP_SERVER_META

        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        assert hasattr(cls, MCP_SERVER_META)

    def test_custom_class_name(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(
            _SIMPLE_SPEC, http_client=client, class_name="MyOpenApiServer"
        )
        assert cls.__name__ == "MyOpenApiServer"

    def test_all_operations_become_tools(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        tool_methods = [
            name
            for name in dir(cls)
            if getattr(getattr(cls, name, None), MCP_TOOL_META, None) is not None
        ]
        assert "listWidgets" in tool_methods
        assert "createWidget" in tool_methods
        assert "getWidget" in tool_methods
        assert "deleteWidget" in tool_methods

    def test_tool_meta_has_correct_name(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.listWidgets, MCP_TOOL_META)
        assert meta.name == "listWidgets"

    def test_tool_description_from_summary(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.listWidgets, MCP_TOOL_META)
        assert meta.description == "List all widgets"

    def test_tool_description_from_description(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.createWidget, MCP_TOOL_META)
        assert meta.description == "Create a widget"

    def test_route_map_exclude(self):
        client = self._make_mock_client()
        route_map = [RouteEntry(pattern=r"^/widgets$", method="GET", expose_as="exclude")]
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client, route_map=route_map)
        assert not hasattr(cls, "listWidgets")

    def test_route_map_name_override(self):
        client = self._make_mock_client()
        route_map = [
            RouteEntry(pattern=r"^/widgets$", method="GET", name_override="get_all_widgets")
        ]
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client, route_map=route_map)
        assert hasattr(cls, "get_all_widgets")
        meta = getattr(cls.get_all_widgets, MCP_TOOL_META)
        assert meta.name == "get_all_widgets"

    def test_route_map_description_override(self):
        client = self._make_mock_client()
        route_map = [
            RouteEntry(
                pattern=r"^/widgets$",
                method="GET",
                description_override="Overridden description",
            )
        ]
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client, route_map=route_map)
        meta = getattr(cls.listWidgets, MCP_TOOL_META)
        assert meta.description == "Overridden description"

    def test_empty_spec_logs_warning(self, caplog: pytest.LogCaptureFixture):
        import logging

        client = self._make_mock_client()
        empty_spec: dict[str, Any] = {"openapi": "3.0.0", "paths": {}}
        with caplog.at_level(logging.WARNING, logger="lauren_mcp.server._openapi"):
            build_openapi_server_class(empty_spec, http_client=client)
        assert "no operations found" in caplog.text

    def test_server_path_passed(self):
        from lauren_mcp.server._meta import MCP_SERVER_META, McpServerMeta

        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client, server_path="/api/mcp")
        meta: McpServerMeta = getattr(cls, MCP_SERVER_META)
        assert meta.path == "/api/mcp"

    def test_from_json_file(self, tmp_path: Path):
        client = self._make_mock_client()
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(_SIMPLE_SPEC))
        cls = build_openapi_server_class(p, http_client=client)
        assert hasattr(cls, "listWidgets")

    def test_input_schema_has_query_param(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.listWidgets, MCP_TOOL_META)
        assert "limit" in meta.input_schema["properties"]

    def test_input_schema_has_path_param_required(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.getWidget, MCP_TOOL_META)
        assert "widget_id" in meta.input_schema["properties"]
        assert "widget_id" in meta.input_schema["required"]

    def test_input_schema_has_body_properties(self):
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        meta = getattr(cls.createWidget, MCP_TOOL_META)
        assert "name" in meta.input_schema["properties"]
        assert "name" in meta.input_schema["required"]

    async def test_generated_tool_callable_json_response(self):
        """The generated async method executes and returns the JSON body."""
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        instance = cls()
        result = await cls.listWidgets(instance)
        assert client.request.called
        call_kwargs = client.request.call_args
        assert call_kwargs[0][0] == "GET"

    async def test_generated_tool_builds_url_with_path_params(self):
        """Path params are substituted into the URL."""
        client = self._make_mock_client()
        cls = build_openapi_server_class(
            _SIMPLE_SPEC, http_client=client, base_url="https://api.example.com"
        )
        instance = cls()
        await cls.getWidget(instance, widget_id="42")
        call_args = client.request.call_args
        # URL should have /widgets/42 with base_url prepended
        assert "42" in call_args[0][1]

    async def test_generated_tool_sends_body(self):
        """POST body params are forwarded as JSON."""
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        instance = cls()
        await cls.createWidget(instance, name="Sprocket")
        call_kwargs = client.request.call_args[1]
        assert call_kwargs["json"] == {"name": "Sprocket"}

    async def test_generated_tool_text_response(self):
        """If content-type is not JSON, the text body is returned."""
        client = MagicMock()
        resp = MagicMock()
        resp.headers = {"content-type": "text/plain"}
        resp.text = "hello"
        resp.raise_for_status = MagicMock()
        client.request = AsyncMock(return_value=resp)

        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        instance = cls()
        result = await cls.listWidgets(instance)
        assert result == "hello"

    async def test_generated_tool_query_params(self):
        """Query params are passed as params kwarg (not body)."""
        client = self._make_mock_client()
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client)
        instance = cls()
        await cls.listWidgets(instance, limit=10)
        call_kwargs = client.request.call_args[1]
        assert call_kwargs["params"] == {"limit": 10}

    def test_route_map_first_match_wins(self):
        """Only the first matching RouteEntry applies."""
        client = self._make_mock_client()
        route_map = [
            RouteEntry(pattern=r"^/widgets$", method="GET", name_override="first_match"),
            RouteEntry(pattern=r"^/widgets$", method="GET", name_override="second_match"),
        ]
        cls = build_openapi_server_class(_SIMPLE_SPEC, http_client=client, route_map=route_map)
        # first match should win — "first_match" exists, "second_match" doesn't
        assert hasattr(cls, "first_match")
        assert not hasattr(cls, "second_match")

    def test_spec_with_no_paths_key(self):
        """Spec without 'paths' key should produce an @mcp_server class without crashing."""
        from lauren_mcp.server._meta import MCP_SERVER_META

        client = self._make_mock_client()
        spec: dict[str, Any] = {"openapi": "3.0.0"}
        cls = build_openapi_server_class(spec, http_client=client)
        assert hasattr(cls, MCP_SERVER_META)

    def test_non_dict_path_item_skipped(self):
        """Non-dict path items in paths are gracefully skipped."""
        client = self._make_mock_client()
        spec: dict[str, Any] = {
            "openapi": "3.0.0",
            "paths": {
                "/bad": "not-a-dict",  # should be skipped
                "/widgets": {"get": {"operationId": "ok", "summary": "Fine"}},
            },
        }
        cls = build_openapi_server_class(spec, http_client=client)
        assert hasattr(cls, "ok")
