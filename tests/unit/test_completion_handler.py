"""Unit tests for make_completion_handler and McpCompletionMeta."""

from __future__ import annotations

import pytest

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import make_completion_handler
from lauren_mcp.server._meta import McpCompletionMeta


class FakeServer:
    async def complete_name(self, partial: str) -> list[str]:
        names = ["Alice", "Bob", "Charlie", "Carol"]
        return [n for n in names if n.lower().startswith(partial.lower())]

    async def complete_lang(self, partial: str) -> object:
        """Returns a CompletionResult-like object."""
        langs = ["Python", "Go", "Rust", "TypeScript"]
        matches = [ln for ln in langs if ln.lower().startswith(partial.lower())]

        # Return a simple namespace that quacks like CompletionResult
        class _CR:
            values = matches
            total = len(langs)
            has_more = False

        return _CR()


COMPLETIONS = [
    McpCompletionMeta(
        ref_type="ref/prompt",
        target_name="greet",
        argument_name="name",
        method_name="complete_name",
    ),
    McpCompletionMeta(
        ref_type="ref/resource",
        target_name="code://{lang}",
        argument_name="lang",
        method_name="complete_lang",
    ),
]


@pytest.fixture
def handler():
    return make_completion_handler(FakeServer(), COMPLETIONS)


def make_req(ref: dict, argument: dict) -> JsonRpcRequest:
    return JsonRpcRequest(
        method="completion/complete",
        params={"ref": ref, "argument": argument},
        id=1,
    )


async def test_prompt_completion_partial_match(handler) -> None:
    req = make_req(
        {"type": "ref/prompt", "name": "greet"},
        {"name": "name", "value": "Al"},
    )
    result = await handler(req)
    assert result["completion"]["values"] == ["Alice"]


async def test_prompt_completion_empty_partial(handler) -> None:
    req = make_req(
        {"type": "ref/prompt", "name": "greet"},
        {"name": "name", "value": ""},
    )
    result = await handler(req)
    assert set(result["completion"]["values"]) == {"Alice", "Bob", "Charlie", "Carol"}


async def test_resource_completion_returns_completion_result(handler) -> None:
    req = make_req(
        {"type": "ref/resource", "uri": "code://{lang}"},
        {"name": "lang", "value": "Py"},
    )
    result = await handler(req)
    assert result["completion"]["values"] == ["Python"]
    assert result["completion"]["total"] == 4


async def test_unknown_ref_returns_empty(handler) -> None:
    req = make_req(
        {"type": "ref/prompt", "name": "nonexistent"},
        {"name": "x", "value": ""},
    )
    result = await handler(req)
    assert result["completion"]["values"] == []
    assert result["completion"]["total"] == 0


async def test_no_completions_registered() -> None:
    h = make_completion_handler(FakeServer(), [])
    req = make_req(
        {"type": "ref/prompt", "name": "greet"},
        {"name": "name", "value": "A"},
    )
    result = await h(req)
    assert result["completion"]["values"] == []


async def test_has_more_false_by_default(handler) -> None:
    req = make_req(
        {"type": "ref/prompt", "name": "greet"},
        {"name": "name", "value": "Al"},
    )
    result = await handler(req)
    assert result["completion"]["hasMore"] is False


async def test_missing_value_field_defaults_to_empty_string(handler) -> None:
    """argument dict with no 'value' key should use '' as partial."""
    req = JsonRpcRequest(
        method="completion/complete",
        params={"ref": {"type": "ref/prompt", "name": "greet"}, "argument": {"name": "name"}},
        id=2,
    )
    result = await handler(req)
    # All names match empty partial
    assert set(result["completion"]["values"]) == {"Alice", "Bob", "Charlie", "Carol"}
