"""Abstract base class defining the MCP client protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from lauren_mcp._types import (
    PromptSchema,
    ResourceSchema,
    ToolSchema,
)


class McpClientProtocol(ABC):
    """Abstract interface for all MCP transport clients.

    Concrete implementations must provide transport-specific connect /
    close logic and override all abstract methods.  The protocol methods
    map one-to-one to MCP JSON-RPC methods.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection and complete the MCP handshake.

        Must be called before any protocol method.  Calling connect()
        on an already-connected client has implementation-defined
        behaviour (either a no-op or a re-connect).
        """

    @abstractmethod
    async def close(self) -> None:
        """Tear down the transport connection gracefully.

        Cancels any pending in-flight requests, closes the underlying
        socket / pipe, and cleans up background tasks.
        """

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_tools(self) -> list[ToolSchema]:
        """Retrieve the server's tool catalogue (``tools/list``).

        Returns a list of :class:`~lauren_mcp._types.ToolSchema` objects
        describing each available tool.
        """

    @abstractmethod
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke a tool on the server (``tools/call``).

        Parameters
        ----------
        name:
            The tool name as reported by :meth:`list_tools`.
        arguments:
            Keyword arguments to pass to the tool.  Must conform to the
            tool's ``inputSchema``.

        Returns
        -------
        Any
            The raw result value from the server's response.
        """

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_resources(self) -> list[ResourceSchema]:
        """Retrieve the server's resource catalogue (``resources/list``).

        Returns a list of :class:`~lauren_mcp._types.ResourceSchema`
        objects.
        """

    @abstractmethod
    async def read_resource(self, uri: str) -> Any:
        """Read a resource by URI (``resources/read``).

        Parameters
        ----------
        uri:
            The exact URI of the resource to read, which may be a
            concrete instantiation of a URI template returned by
            :meth:`list_resources`.

        Returns
        -------
        Any
            The raw contents returned by the server.
        """

    @abstractmethod
    async def subscribe_resource(self, uri: str) -> None:
        """Subscribe to change notifications for the resource at *uri*.

        Sends ``resources/subscribe`` with ``{"uri": uri}``.  After a
        successful subscription the server will push
        ``notifications/resources/updated`` whenever the resource changes.

        The server returns ``METHOD_NOT_FOUND`` if it does not support
        subscriptions; this is surfaced as :class:`McpCallError` with
        ``code == -32601``.

        Parameters
        ----------
        uri:
            The exact resource URI previously returned by :meth:`list_resources`.
        """

    @abstractmethod
    async def unsubscribe_resource(self, uri: str) -> None:
        """Cancel a previously established resource subscription.

        Sends ``resources/unsubscribe`` with ``{"uri": uri}``.  The server
        will stop pushing ``notifications/resources/updated`` for this URI.

        Parameters
        ----------
        uri:
            The URI that was passed to :meth:`subscribe_resource`.
        """

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    @abstractmethod
    async def list_prompts(self) -> list[PromptSchema]:
        """Retrieve the server's prompt catalogue (``prompts/list``).

        Returns a list of :class:`~lauren_mcp._types.PromptSchema`
        objects.
        """

    @abstractmethod
    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        """Retrieve a rendered prompt from the server (``prompts/get``).

        Parameters
        ----------
        name:
            The prompt name as reported by :meth:`list_prompts`.
        arguments:
            String arguments to substitute into the prompt template.

        Returns
        -------
        Any
            The raw GetPromptResult value from the server.
        """

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @abstractmethod
    async def ping(self) -> None:
        """Send a ``ping`` request and await the empty ``{}`` response.

        Useful for connection health-checks and keep-alive probing.
        Raises :class:`McpCallError` (or a subclass) on failure.
        """

    @abstractmethod
    async def set_logging_level(self, level: str) -> None:
        """Ask the server to change its minimum log-notification threshold.

        Sends ``logging/setLevel`` with ``{"level": level}``.  The server
        will suppress ``notifications/message`` entries below *level* from
        that point forward.

        Parameters
        ----------
        level:
            One of ``"debug"``, ``"info"``, ``"notice"``, ``"warning"``,
            ``"error"``, ``"critical"``, ``"alert"``, ``"emergency"``.

        Raises
        ------
        ValueError
            If *level* is not one of the accepted strings.
        McpCallError
            If the server returns a JSON-RPC error response.
        """

    @abstractmethod
    async def complete(self, ref: dict[str, Any], argument: dict[str, Any]) -> Any:
        """Request completion suggestions from the server (``completion/complete``).

        Parameters
        ----------
        ref:
            A reference object identifying the completable item, e.g.
            ``{"type": "ref/prompt", "name": "greet"}``.
        argument:
            The argument being completed, e.g.
            ``{"name": "nam", "value": "Jo"}``.

        Returns
        -------
        Any
            The raw completion result from the server.
        """
