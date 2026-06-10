"""DNS-rebinding protection for HTTP MCP transports.

Provides :class:`TransportSecuritySettings` and :class:`McpTransportSecurityGuard`
which enforce ``Host``, ``Origin``, and ``Content-Type`` validation on every HTTP
request to MCP server endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lauren.types import ExecutionContext


@dataclass(frozen=True)
class TransportSecuritySettings:
    """Host/Origin validation settings for HTTP MCP transports.

    Parameters
    ----------
    enable_dns_rebinding_protection:
        Master switch.  When ``False`` the guard is a no-op.
    allowed_hosts:
        Accepted ``Host`` header values.  Each entry may be an exact host
        (``"example.com"``) or a host with a wildcard port
        (``"example.com:*"``).  ``"localhost"`` and ``"127.0.0.1"`` are
        always implicitly allowed when the list is empty.
    allowed_origins:
        Accepted ``Origin`` header values for cross-origin POST requests.
        An empty list means *only same-origin* (i.e. requests with no
        ``Origin`` header or an ``Origin`` matching an ``allowed_hosts``
        entry pass through).
    """

    enable_dns_rebinding_protection: bool = True
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    def is_host_allowed(self, host: str) -> bool:
        """Check if Host header is in allowed_hosts (supports 'host:*' wildcard port)."""
        return _host_allowed(host, self.allowed_hosts)

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Check if Origin is in allowed_origins or is None (same-origin)."""
        if origin is None:
            return True
        return _origin_allowed(origin, self)


def _host_allowed(host: str, allowed: list[str]) -> bool:
    """Return True when *host* is in the allowed set.

    Wildcard-port notation: ``"example.com:*"`` matches any port on that
    host.  An empty *allowed* list allows only localhost variants.
    """
    if not allowed:
        bare = host.split(":")[0]
        return bare in ("localhost", "127.0.0.1", "::1")
    for entry in allowed:
        if entry.endswith(":*"):
            if host.split(":")[0] == entry[:-2]:
                return True
        elif host == entry:
            return True
    return False


def _origin_allowed(origin: str, settings: TransportSecuritySettings) -> bool:
    """Return True when the *origin* is explicitly allowed or matches a host."""
    if origin in settings.allowed_origins:
        return True
    # Strip scheme from origin for host comparison
    bare = origin.removeprefix("https://").removeprefix("http://")
    return _host_allowed(bare, settings.allowed_hosts)


class McpTransportSecurityGuard:
    """Lauren guard that validates Host/Origin/Content-Type on MCP HTTP endpoints."""

    def __init__(self) -> None:
        self._settings: TransportSecuritySettings | None = None

    def configure(self, settings: TransportSecuritySettings) -> None:
        self._settings = settings

    async def can_activate(self, ctx: ExecutionContext) -> bool:
        if self._settings is None or not self._settings.enable_dns_rebinding_protection:
            return True

        request = ctx.request

        # --- Host validation (all methods) ---
        host: str = request.headers.get("host") or ""
        if not _host_allowed(host, self._settings.allowed_hosts):
            return False

        # --- Origin and Content-Type validation (POST only) ---
        method: str = (getattr(request, "method", None) or "GET").upper()
        if method == "POST":
            origin: str | None = request.headers.get("origin")
            if origin is not None and not _origin_allowed(origin, self._settings):
                return False

            ct: str = request.headers.get("content-type") or ""
            if "application/json" not in ct:
                return False

        return True
