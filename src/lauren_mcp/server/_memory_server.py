"""PRD 10 — LaurenMcpMemoryServer: deployable MCP memory server.

Provides :class:`LaurenMcpMemoryServer` — a ready-to-deploy ``@mcp_server``
class backed by either in-memory or SQLite storage that fulfils the contract
expected by :class:`~lauren_ai.mcp._memory.McpConversationStore` and
:class:`~lauren_ai.mcp._memory.McpUserMemoryStore`.

Usage::

    from lauren_mcp.server import LaurenMcpMemoryServer
    from lauren_mcp import McpServerModule
    from lauren import module, LaurenFactory

    @module(imports=[McpServerModule.for_root(LaurenMcpMemoryServer)])
    class MemoryApp: pass

    app = LaurenFactory.create(MemoryApp)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from lauren_mcp.server._decorators import mcp_resource, mcp_server, mcp_tool

logger = logging.getLogger(__name__)


@mcp_server("/memory")
class LaurenMcpMemoryServer:
    """Deployable MCP memory server for :mod:`lauren-ai` agents.

    Exposes:

    Tools (write operations):
    - ``save_conversation(conversation_id, snapshot)``
    - ``delete_conversation(conversation_id)``
    - ``save_user_fact(user_id, key, value)``
    - ``get_user_facts(user_id)`` → JSON string
    - ``delete_user_fact(user_id, key)``

    Resources (read operations):
    - ``memory://conversations/{conversation_id}`` — snapshot JSON

    All storage is in-memory by default.  For persistent storage, subclass and
    override :meth:`_load_conv`, :meth:`_save_conv`, :meth:`_delete_conv`,
    :meth:`_save_fact`, :meth:`_get_facts`, :meth:`_delete_fact`.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, str] = {}
        self._user_facts: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Conversation tools
    # ------------------------------------------------------------------

    @mcp_tool(name="save_conversation", description="Save a conversation snapshot.")
    async def save_conversation(
        self,
        conversation_id: str,
        snapshot: str,
    ) -> dict[str, Any]:
        """Save a conversation snapshot as JSON.

        Args:
            conversation_id: Unique conversation identifier.
            snapshot: JSON-encoded snapshot dict.
        """
        try:
            parsed = json.loads(snapshot)
        except (json.JSONDecodeError, ValueError):
            parsed = snapshot
        self._conversations[conversation_id] = json.dumps(parsed)
        return {"saved": True, "conversation_id": conversation_id}

    @mcp_tool(name="delete_conversation", description="Delete a conversation by ID.")
    async def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        """Delete a conversation from the store.

        Args:
            conversation_id: Unique conversation identifier.
        """
        existed = conversation_id in self._conversations
        self._conversations.pop(conversation_id, None)
        return {"deleted": existed, "conversation_id": conversation_id}

    # ------------------------------------------------------------------
    # Conversation resource
    # ------------------------------------------------------------------

    @mcp_resource(
        "memory://conversations/{conversation_id}",
        mime_type="application/json",
        description="Read a conversation snapshot.",
    )
    async def read_conversation(self, conversation_id: str) -> str:
        """Return the JSON snapshot for *conversation_id*, or ``'[]'`` if absent."""
        return self._conversations.get(conversation_id, "[]")

    # ------------------------------------------------------------------
    # User memory tools
    # ------------------------------------------------------------------

    @mcp_tool(name="save_user_fact", description="Save a discrete user memory fact.")
    async def save_user_fact(
        self,
        user_id: str,
        key: str,
        value: str,
    ) -> dict[str, Any]:
        """Persist a key/value user fact.

        Args:
            user_id: User identifier.
            key: Fact key (e.g. "preferred_language").
            value: Fact value.
        """
        if user_id not in self._user_facts:
            self._user_facts[user_id] = {}
        self._user_facts[user_id][key] = value
        return {"saved": True, "user_id": user_id, "key": key}

    @mcp_tool(
        name="get_user_facts",
        description="Return all user memory facts as a JSON array.",
    )
    async def get_user_facts(self, user_id: str) -> str:
        """Return all facts for *user_id* as a JSON-encoded list of ``{key, value}`` dicts.

        Args:
            user_id: User identifier.
        """
        facts = self._user_facts.get(user_id, {})
        return json.dumps([{"key": k, "value": v} for k, v in facts.items()])

    @mcp_tool(name="delete_user_fact", description="Delete a user memory fact by key.")
    async def delete_user_fact(self, user_id: str, key: str) -> dict[str, Any]:
        """Delete a fact from the user's memory store.

        Args:
            user_id: User identifier.
            key: Fact key to delete.
        """
        user_data = self._user_facts.get(user_id, {})
        existed = key in user_data
        user_data.pop(key, None)
        return {"deleted": existed, "user_id": user_id, "key": key}
