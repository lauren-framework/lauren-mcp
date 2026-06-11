"""Unit tests for LaurenMcpMemoryServer."""

from __future__ import annotations

import json

from lauren_mcp import LaurenMcpMemoryServer


class TestConversationTools:
    async def test_save_and_read_conversation(self):
        server = LaurenMcpMemoryServer()
        snapshot = {"messages": [{"role": "user", "content": "hello"}], "summary": None}

        result = await server.save_conversation("conv-1", json.dumps(snapshot))
        assert result["saved"] is True

        text = await server.read_conversation("conv-1")
        loaded = json.loads(text)
        assert loaded["messages"][0]["content"] == "hello"

    async def test_read_missing_returns_empty_list(self):
        server = LaurenMcpMemoryServer()
        text = await server.read_conversation("nonexistent")
        assert json.loads(text) == []

    async def test_delete_conversation(self):
        server = LaurenMcpMemoryServer()
        await server.save_conversation("conv-2", json.dumps({"messages": []}))
        result = await server.delete_conversation("conv-2")
        assert result["deleted"] is True

        text = await server.read_conversation("conv-2")
        assert json.loads(text) == []

    async def test_delete_nonexistent_returns_false(self):
        server = LaurenMcpMemoryServer()
        result = await server.delete_conversation("missing")
        assert result["deleted"] is False


class TestUserFactTools:
    async def test_save_and_get_user_fact(self):
        server = LaurenMcpMemoryServer()
        await server.save_user_fact("user-1", "language", "Python")

        facts_json = await server.get_user_facts("user-1")
        facts = json.loads(facts_json)
        assert any(f["key"] == "language" and f["value"] == "Python" for f in facts)

    async def test_get_empty_user(self):
        server = LaurenMcpMemoryServer()
        facts_json = await server.get_user_facts("no-such-user")
        assert json.loads(facts_json) == []

    async def test_delete_user_fact(self):
        server = LaurenMcpMemoryServer()
        await server.save_user_fact("user-2", "pref", "dark_mode")
        result = await server.delete_user_fact("user-2", "pref")
        assert result["deleted"] is True

        facts_json = await server.get_user_facts("user-2")
        facts = json.loads(facts_json)
        assert not any(f["key"] == "pref" for f in facts)

    async def test_multiple_users_isolated(self):
        server = LaurenMcpMemoryServer()
        await server.save_user_fact("alice", "key", "A")
        await server.save_user_fact("bob", "key", "B")

        alice_facts = json.loads(await server.get_user_facts("alice"))
        bob_facts = json.loads(await server.get_user_facts("bob"))

        assert alice_facts[0]["value"] == "A"
        assert bob_facts[0]["value"] == "B"
