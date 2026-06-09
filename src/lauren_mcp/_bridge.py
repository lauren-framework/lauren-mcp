"""McpServerConfig and McpToolBridge — connects MCP clients to the ToolRegistry."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """Named wrapper pairing an alias string with an MCP client."""

    alias: str
    client: Any  # McpClientProtocol — avoid circular import at module level


class McpToolBridge:
    """SINGLETON that manages MCP client lifecycles and populates ToolRegistry.

    This class is optional — it is only usable when lauren-ai is installed.
    Instantiate via AgentModule.for_root(mcp_servers=[...]).

    Note: this class deliberately does NOT use @injectable from lauren so that
    it can be used without lauren-ai as a standalone orchestration helper.
    """

    def __init__(self, servers: list[McpServerConfig]) -> None:
        self._servers = servers
        self._registry: Any = None  # set via set_registry before connect_all
        self._watch_tasks: list[asyncio.Task] = []

    def set_registry(self, registry: Any) -> None:
        """Attach a ToolRegistry (or any object with register_mcp_server) to this bridge.

        Must be called before :meth:`connect_all` if tool registration is desired.
        """
        self._registry = registry

    async def connect_all(self) -> None:
        """Connect every configured MCP server and load tools into the registry.

        For each configured server the method:

        1. Calls ``client.connect()`` to perform the MCP initialize handshake.
        2. Calls ``client.list_tools()`` to retrieve all available tool schemas.
        3. Registers those tools via ``registry.register_mcp_server(alias, tools, client)``
           (skipped when no registry has been attached via :meth:`set_registry`).

        Failures in individual servers are caught and logged at ERROR level so
        that a single broken server does not prevent the remaining servers from
        loading.
        """
        for cfg in self._servers:
            try:
                await cfg.client.connect()
                tools = await cfg.client.list_tools()
                if self._registry is not None:
                    self._registry.register_mcp_server(cfg.alias, tools, cfg.client)
                logger.info(
                    "MCP bridge: loaded %d tools from '%s'",
                    len(tools),
                    cfg.alias,
                )
                for tool in tools:
                    logger.info("  %s__%s", cfg.alias, tool.name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "MCP bridge: failed to connect '%s': %s",
                    cfg.alias,
                    exc,
                )

    async def disconnect_all(self) -> None:
        """Cancel all watch tasks and close every configured MCP client.

        Exceptions raised by individual ``client.close()`` calls are silently
        suppressed so that all clients receive a close attempt regardless of
        whether earlier ones failed.
        """
        for task in self._watch_tasks:
            task.cancel()
        for cfg in self._servers:
            try:
                await cfg.client.close()
            except Exception:  # noqa: BLE001
                pass
