"""Server composition — mount sibling MCP servers and proxy remote ones."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from lauren import Scope, injectable, post_construct, pre_destruct

from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp._types import ToolOutput

from ._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpToolMeta,
)

_logger = logging.getLogger(__name__)


class McpToolNameCollision(Exception):
    """Raised when two composition sources expose the same tool name."""


def _prefixed_metas(source_cls: type, prefix: str) -> tuple[list[Any], list[Any], list[Any]]:
    """Collect tool/resource/prompt metas from *source_cls* with *prefix* applied."""
    tools: list[Any] = []
    resources: list[Any] = []
    prompts: list[Any] = []
    for attr_name in dir(source_cls):
        try:
            attr = getattr(source_cls, attr_name)
        except AttributeError:
            continue
        tool_meta = getattr(attr, MCP_TOOL_META, None)
        if tool_meta is not None:
            tools.append(dataclasses.replace(tool_meta, name=f"{prefix}{tool_meta.name}"))
        resource_meta = getattr(attr, MCP_RESOURCE_META, None)
        if resource_meta is not None:
            resources.append(
                dataclasses.replace(resource_meta, name=f"{prefix}{resource_meta.name}")
            )
        prompt_meta = getattr(attr, MCP_PROMPT_META, None)
        if prompt_meta is not None:
            prompts.append(dataclasses.replace(prompt_meta, name=f"{prefix}{prompt_meta.name}"))
    return tools, resources, prompts


def make_mount_binder(mounted_cls: type, prefix: str) -> type:
    """Build an ``@injectable`` that registers *mounted_cls*'s catalogue entries.

    Add the returned class (and *mounted_cls* itself) to ``for_root``'s
    ``providers=[...]``.  At startup the binder clones every tool / resource /
    prompt meta with *prefix* applied, binds them to the DI-resolved instance
    of *mounted_cls*, and registers them in the shared catalogue.
    """
    if getattr(mounted_cls, MCP_SERVER_META, None) is None:
        raise TypeError(
            f"{mounted_cls!r} is not an MCP server class; decorate it with "
            "@mcp_server before mounting."
        )

    @injectable(scope=Scope.SINGLETON)
    class _MountBinder:
        def __init__(
            self,
            catalog: McpCatalogManager,
            instance: mounted_cls,  # type: ignore[valid-type]
        ) -> None:
            self._catalog = catalog
            self._instance = instance

        @post_construct
        def _bind(self) -> None:
            tools, resources, prompts = _prefixed_metas(mounted_cls, prefix)
            for meta in tools:
                setattr(meta, "_bound_instance", self._instance)  # noqa: B010
                self._catalog.register_tool(meta, on_conflict="error")
            for meta in resources:
                setattr(meta, "_bound_instance", self._instance)  # noqa: B010
                self._catalog.register_resource(meta)
            for meta in prompts:
                setattr(meta, "_bound_instance", self._instance)  # noqa: B010
                self._catalog.register_prompt(meta)

    _MountBinder.__init__.__annotations__["instance"] = mounted_cls
    _MountBinder.__name__ = f"McpMountBinder[{mounted_cls.__name__}]"
    _MountBinder.__qualname__ = _MountBinder.__name__
    return _MountBinder


class _RemoteToolTarget:
    """Adapter exposing one remote tool as a local async method."""

    def __init__(self, client: Any, remote_name: str) -> None:
        self._client = client
        self._remote_name = remote_name

    async def call(self, **kwargs: Any) -> ToolOutput:
        result = await self._client.call_tool(self._remote_name, kwargs)
        if isinstance(result, dict):
            return ToolOutput(
                content=result.get("content") or [],
                structured_content=result.get("structuredContent"),
                is_error=bool(result.get("isError", False)),
            )
        return ToolOutput(content=[{"type": "text", "text": str(result)}])


def make_proxy_binder(client: Any, prefix: str) -> type:
    """Build an ``@injectable`` that proxies a remote MCP server's tools.

    Add the returned class to ``for_root``'s ``providers=[...]``.  At startup
    it connects *client* (an :class:`~lauren_mcp.McpClientProtocol`), fetches
    the remote tool catalogue, and registers each tool locally under
    ``{prefix}{name}``.  Calls are forwarded over the client; the connection
    is closed at shutdown.
    """

    @injectable(scope=Scope.SINGLETON)
    class _ProxyBinder:
        def __init__(self, catalog: McpCatalogManager) -> None:
            self._catalog = catalog
            self._client = client
            self._registered: list[str] = []

        @post_construct
        async def _bind(self) -> None:
            await self._client.connect()
            for schema in await self._client.list_tools():
                local_name = f"{prefix}{schema.name}"
                meta = McpToolMeta(
                    name=local_name,
                    description=schema.description,
                    input_schema=schema.inputSchema,
                    method_name="call",
                )
                setattr(  # noqa: B010
                    meta, "_bound_instance", _RemoteToolTarget(self._client, schema.name)
                )
                self._catalog.register_tool(meta, on_conflict="error")
                self._registered.append(local_name)
            _logger.info("MCP proxy[%s]: registered %d remote tools", prefix, len(self._registered))

        @pre_destruct
        async def _unbind(self) -> None:
            for name in self._registered:
                self._catalog.unregister_tool(name)
            self._registered.clear()
            try:  # noqa: SIM105
                await self._client.close()
            except Exception:
                pass

    _ProxyBinder.__name__ = f"McpProxyBinder[{prefix or 'remote'}]"
    _ProxyBinder.__qualname__ = _ProxyBinder.__name__
    return _ProxyBinder


__all__ = ["McpToolNameCollision", "make_mount_binder", "make_proxy_binder"]
