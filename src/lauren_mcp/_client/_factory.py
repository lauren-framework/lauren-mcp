"""McpServer — factory / namespace for constructing MCP clients."""

from __future__ import annotations

from typing import Any

from ._protocol import McpClientProtocol


class McpServer:
    """Static factory for creating MCP clients for different transports.

    Usage::

        # stdio subprocess
        client = McpServer.stdio(["python", "-m", "my_mcp_server"])

        # WebSocket (requires lauren-mcp[ws])
        client = McpServer.ws("ws://localhost:8000/mcp/ws")

        # HTTP + SSE, legacy 2024-11-05 transport (requires lauren-mcp[sse])
        client = McpServer.http("http://localhost:8000/mcp")

        # Streamable HTTP, 2025-03-26 transport (requires lauren-mcp[sse])
        client = McpServer.streamable_http("http://localhost:8000/mcp")

        await client.connect()
        tools = await client.list_tools()
        await client.close()

    All factories accept these optional keyword arguments:

    ``protocol_version``
        Protocol version to request during the handshake (defaults to the
        latest the library supports).
    ``roots``
        Static list of :class:`~lauren_mcp.Root` or a callable returning the
        current roots; advertised via the ``roots`` capability.
    ``progress_handler`` / ``log_handler`` / ``list_changed_handler``
        Callbacks invoked when the server pushes the matching notification.
    ``sampling_handler`` / ``elicitation_handler``
        Callbacks answering server-initiated ``sampling/createMessage`` /
        ``elicitation/create`` requests.
    """

    @staticmethod
    def stdio(
        command: list[str] | tuple[str, ...],
        *,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        **feature_kwargs: Any,
    ) -> McpClientProtocol:
        """Create an MCP stdio client that launches *command* as a subprocess.

        Parameters
        ----------
        command:
            Argv sequence, e.g. ``["python", "-m", "myserver"]``.
        max_retries:
            Subprocess restart attempts on unexpected EOF.
        startup_timeout:
            Seconds to wait for the ``initialize`` handshake response.
        """
        from ._stdio import McpStdioClient

        return McpStdioClient(
            command,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )

    @staticmethod
    def ws(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        **feature_kwargs: Any,
    ) -> McpClientProtocol:
        """Create an MCP WebSocket client.

        Requires ``pip install 'lauren-mcp[ws]'``.

        Parameters
        ----------
        url:
            Full WebSocket URL, e.g. ``"ws://localhost:8000/mcp/ws"``.
        headers:
            Optional extra HTTP headers sent during the upgrade handshake.
        max_retries:
            Reconnect attempts after unexpected disconnect.
        startup_timeout:
            Seconds to wait for the ``initialize`` handshake response.
        """
        from ._ws import McpWebSocketClient

        return McpWebSocketClient(
            url,
            headers=headers,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )

    @staticmethod
    def http(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        **feature_kwargs: Any,
    ) -> McpClientProtocol:
        """Create an MCP HTTP+SSE client (legacy 2024-11-05 transport).

        Requires ``pip install 'lauren-mcp[sse]'``.

        For servers speaking the 2025-03-26 Streamable HTTP transport use
        :meth:`streamable_http` instead.

        Parameters
        ----------
        url:
            Base URL of the MCP HTTP+SSE server, e.g.
            ``"http://localhost:8000/mcp"``.
        headers:
            Optional extra HTTP headers included in every request.
        max_retries:
            Reconnect attempts after SSE stream closes unexpectedly.
        startup_timeout:
            Seconds to wait for the ``initialize`` handshake response.
        """
        from ._sse import McpHttpSseClient

        return McpHttpSseClient(
            url,
            headers=headers,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )

    @staticmethod
    def streamable_http(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        **feature_kwargs: Any,
    ) -> McpClientProtocol:
        """Create an MCP Streamable HTTP client (2025-03-26 transport).

        Requires ``pip install 'lauren-mcp[sse]'``.

        Parameters
        ----------
        url:
            Base URL of the MCP endpoint, e.g. ``"http://localhost:8000/mcp"``.
        headers:
            Optional extra HTTP headers included in every request.
        max_retries:
            Reconnect attempts after the connection drops.
        startup_timeout:
            Seconds to wait for the ``initialize`` handshake response.
        """
        from ._streamable import McpStreamableHttpClient

        return McpStreamableHttpClient(
            url,
            headers=headers,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )
