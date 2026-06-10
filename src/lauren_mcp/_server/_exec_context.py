"""McpExecutionContext — minimal context passed to per-tool guards and interceptors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class McpExecutionContext:
    """Lightweight execution context passed to per-tool guards and interceptors.

    This is distinct from :class:`McpToolContext` (which is injected into the
    tool method itself and carries rich capabilities like ``sample()``,
    ``log()``, ``report_progress()``).  ``McpExecutionContext`` is provided to
    the guard/interceptor layer **before** the tool method is invoked; it
    contains only the information available at dispatch time.

    Attributes
    ----------
    tool_name:
        The registered MCP tool / resource / prompt name.
    method_name:
        The Python method name on the server class.
    server_class:
        The ``@mcp_server``-decorated class that owns this tool.
    headers:
        HTTP headers from the current transport binding, or ``None`` when
        not available (e.g. stdio transport).
    execution_context:
        The Lauren HTTP ``ExecutionContext`` from the current transport
        binding, or ``None`` for WS and stdio transports.
    session_id:
        The MCP session ID string, or ``None`` when not available.
    metadata:
        Merged server-level metadata (from ``@set_metadata`` on the server
        class) plus per-tool metadata (from ``@set_metadata`` on the method).
    tool_use_id:
        The JSON-RPC request ``id``, or ``None`` for notifications / prompts.
    """

    tool_name: str
    method_name: str
    server_class: type
    headers: dict[str, str] | None = None
    execution_context: Any = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str | int | None = None

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Return ``metadata[key]`` or *default* if the key is absent."""
        return self.metadata.get(key, default)
