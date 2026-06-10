"""Unit tests for new wire types added in _types.py."""

from __future__ import annotations

import base64
import typing

import pytest

from lauren_mcp._types import (
    AnyContent,
    AudioContent,
    CompletionResult,
    ImageContent,
    McpUrlElicitationNotAvailable,
    PromptSchema,
    ResourceAnnotations,
    ResourceLink,
    ResourceSchema,
    Role,
    SamplingMessage,
    TextContent,
    ToolResultContent,
    ToolSchema,
    ToolUseContent,
    UrlElicitResult,
    validate_sampling_messages,
)

# ---------------------------------------------------------------------------
# AudioContent
# ---------------------------------------------------------------------------


def test_audio_content_type_field_default() -> None:
    a = AudioContent(data="AAAA", mimeType="audio/wav")
    assert a.type == "audio"


def test_audio_content_data_and_mime() -> None:
    a = AudioContent(data="dGVzdA==", mimeType="audio/mpeg")
    assert a.data == "dGVzdA=="
    assert a.mimeType == "audio/mpeg"


def test_audio_content_from_bytes() -> None:
    raw = b"\x00\x01\x02\x03"
    a = AudioContent.from_bytes(raw, mime_type="audio/ogg")
    assert a.data == base64.b64encode(raw).decode("ascii")
    assert a.mimeType == "audio/ogg"
    assert a.type == "audio"


def test_audio_content_from_bytes_default_mime() -> None:
    a = AudioContent.from_bytes(b"hello")
    assert a.mimeType == "audio/wav"


def test_audio_content_serializes_to_dict() -> None:
    a = AudioContent(data="dGVzdA==", mimeType="audio/mpeg")
    # AudioContent is a dataclass; verify fields match expected wire shape
    assert a.type == "audio"
    assert a.data == "dGVzdA=="
    assert a.mimeType == "audio/mpeg"


# ---------------------------------------------------------------------------
# ResourceLink
# ---------------------------------------------------------------------------


def test_resource_link_minimal() -> None:
    r = ResourceLink(uri="file:///data/report.pdf")
    assert r.type == "resource_link"
    assert r.name is None
    assert r.description is None
    assert r.mimeType is None


def test_resource_link_full() -> None:
    r = ResourceLink(
        uri="https://example.com/data.csv",
        name="Sales Data",
        description="Q1 sales report",
        mimeType="text/csv",
    )
    assert r.uri == "https://example.com/data.csv"
    assert r.name == "Sales Data"
    assert r.description == "Q1 sales report"
    assert r.mimeType == "text/csv"
    assert r.type == "resource_link"


# ---------------------------------------------------------------------------
# AnyContent union includes new types
# ---------------------------------------------------------------------------


def test_any_content_union_includes_audio_content() -> None:
    args = typing.get_args(AnyContent)
    assert AudioContent in args


def test_any_content_union_includes_resource_link() -> None:
    args = typing.get_args(AnyContent)
    assert ResourceLink in args


# ---------------------------------------------------------------------------
# ToolUseContent
# ---------------------------------------------------------------------------


def test_tool_use_content_type_default() -> None:
    tuc = ToolUseContent(id="c1", name="list_files", input={"path": "/tmp"})
    assert tuc.type == "tool_use"


def test_tool_use_content_to_dict() -> None:
    tuc = ToolUseContent(id="call_1", name="list_files", input={"path": "/tmp"})
    d = tuc.to_dict()
    assert d == {
        "type": "tool_use",
        "id": "call_1",
        "name": "list_files",
        "input": {"path": "/tmp"},
    }


def test_tool_use_content_from_dict() -> None:
    tuc = ToolUseContent.from_dict(
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "list_files",
            "input": {"path": "/tmp"},
        }
    )
    assert tuc.id == "call_1"
    assert tuc.name == "list_files"
    assert tuc.input == {"path": "/tmp"}


def test_tool_use_content_from_dict_empty_input_defaults_to_empty_dict() -> None:
    tuc = ToolUseContent.from_dict({"id": "x", "name": "f"})
    assert tuc.input == {}


# ---------------------------------------------------------------------------
# ToolResultContent
# ---------------------------------------------------------------------------


def test_tool_result_content_type_default() -> None:
    trc = ToolResultContent(tool_use_id="call_1")
    assert trc.type == "tool_result"
    assert trc.is_error is False
    assert trc.content == []


def test_tool_result_content_to_dict_text() -> None:
    trc = ToolResultContent(
        tool_use_id="call_1",
        content=[TextContent(text="result text")],
    )
    d = trc.to_dict()
    assert d["tool_use_id"] == "call_1"
    assert d["content"] == [{"type": "text", "text": "result text"}]
    assert d["is_error"] is False
    assert d["type"] == "tool_result"


def test_tool_result_content_to_dict_image() -> None:
    trc = ToolResultContent(
        tool_use_id="call_2",
        content=[ImageContent(data="base64data", mimeType="image/png")],
    )
    d = trc.to_dict()
    assert d["content"][0] == {"type": "image", "data": "base64data", "mimeType": "image/png"}


def test_tool_result_content_to_dict_is_error() -> None:
    trc = ToolResultContent(
        tool_use_id="call_3",
        content=[TextContent(text="Error: not found")],
        is_error=True,
    )
    assert trc.to_dict()["is_error"] is True


def test_tool_result_content_from_dict_round_trip() -> None:
    raw = {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": [{"type": "text", "text": "hello"}],
        "is_error": False,
    }
    trc = ToolResultContent.from_dict(raw)
    assert trc.tool_use_id == "call_1"
    assert len(trc.content) == 1
    assert isinstance(trc.content[0], TextContent)
    assert trc.content[0].text == "hello"


def test_tool_result_content_from_dict_empty_content() -> None:
    trc = ToolResultContent.from_dict({"tool_use_id": "x"})
    assert trc.content == []


# ---------------------------------------------------------------------------
# ResourceAnnotations
# ---------------------------------------------------------------------------


def test_resource_annotations_priority_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="priority"):
        ResourceAnnotations(priority=1.5)


def test_resource_annotations_priority_negative_raises() -> None:
    with pytest.raises(ValueError, match="priority"):
        ResourceAnnotations(priority=-0.1)


def test_resource_annotations_priority_boundary_valid() -> None:
    # 0.0 and 1.0 are valid boundaries
    ra0 = ResourceAnnotations(priority=0.0)
    assert ra0.priority == 0.0
    ra1 = ResourceAnnotations(priority=1.0)
    assert ra1.priority == 1.0


def test_resource_annotations_to_dict_full() -> None:
    ra = ResourceAnnotations(audience=["user"], priority=0.8)
    d = ra.to_dict()
    assert d == {"audience": ["user"], "priority": 0.8}


def test_resource_annotations_to_dict_omits_none_fields() -> None:
    ra = ResourceAnnotations(audience=["user", "assistant"])
    d = ra.to_dict()
    assert d == {"audience": ["user", "assistant"]}
    assert "priority" not in d


def test_resource_annotations_to_dict_all_none_returns_empty() -> None:
    ra = ResourceAnnotations()
    assert ra.to_dict() == {}


def test_resource_annotations_from_dict_round_trip() -> None:
    ra = ResourceAnnotations.from_dict({"audience": ["assistant"], "priority": 0.5})
    assert ra.audience == ["assistant"]
    assert ra.priority == 0.5


# ---------------------------------------------------------------------------
# validate_sampling_messages
# ---------------------------------------------------------------------------


def test_validate_sampling_messages_empty_is_valid() -> None:
    validate_sampling_messages([])  # no exception


def test_validate_sampling_messages_text_only_is_valid() -> None:
    messages = [SamplingMessage(role="user", content=TextContent(text="hi"))]
    validate_sampling_messages(messages)  # no exception


def test_validate_sampling_messages_valid_tool_use_then_result() -> None:
    messages = [
        SamplingMessage(
            role="assistant",
            content=ToolUseContent(id="c1", name="f", input={}),
        ),
        SamplingMessage(
            role="user",
            content=ToolResultContent(tool_use_id="c1", content=[]),
        ),
    ]
    validate_sampling_messages(messages)  # no exception


def test_validate_sampling_messages_valid_multiple_tool_calls() -> None:
    messages = [
        SamplingMessage(role="assistant", content=ToolUseContent(id="c1", name="f", input={})),
        SamplingMessage(role="user", content=ToolResultContent(tool_use_id="c1", content=[])),
        SamplingMessage(role="assistant", content=ToolUseContent(id="c2", name="g", input={})),
        SamplingMessage(role="user", content=ToolResultContent(tool_use_id="c2", content=[])),
    ]
    validate_sampling_messages(messages)  # no exception


def test_validate_sampling_messages_tool_result_before_tool_use_raises() -> None:
    messages = [
        SamplingMessage(
            role="user",
            content=ToolResultContent(tool_use_id="c1", content=[]),
        ),
    ]
    with pytest.raises(ValueError, match="c1"):
        validate_sampling_messages(messages)


def test_validate_sampling_messages_mismatched_id_raises() -> None:
    messages = [
        SamplingMessage(role="assistant", content=ToolUseContent(id="c1", name="f", input={})),
        SamplingMessage(role="user", content=ToolResultContent(tool_use_id="c999", content=[])),
    ]
    with pytest.raises(ValueError, match="c999"):
        validate_sampling_messages(messages)


# ---------------------------------------------------------------------------
# UrlElicitResult
# ---------------------------------------------------------------------------


def test_url_elicit_result_from_dict_accept() -> None:
    r = UrlElicitResult.from_dict({"action": "accept"})
    assert r.action == "accept"


def test_url_elicit_result_from_dict_cancel() -> None:
    r = UrlElicitResult.from_dict({"action": "cancel"})
    assert r.action == "cancel"


def test_url_elicit_result_from_dict_unknown_action_coerced_to_cancel() -> None:
    r = UrlElicitResult.from_dict({"action": "decline"})
    assert r.action == "cancel"


def test_url_elicit_result_from_dict_empty_defaults_to_cancel() -> None:
    r = UrlElicitResult.from_dict({})
    assert r.action == "cancel"


def test_mcp_url_elicitation_not_available_is_runtime_error() -> None:
    exc = McpUrlElicitationNotAvailable("test message")
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "test message"


# ---------------------------------------------------------------------------
# CompletionResult
# ---------------------------------------------------------------------------


def test_completion_result_defaults() -> None:
    cr = CompletionResult(values=["a", "b"])
    assert cr.values == ["a", "b"]
    assert cr.total is None
    assert cr.has_more is False


def test_completion_result_with_all_fields() -> None:
    cr = CompletionResult(values=["x"], total=10, has_more=True)
    assert cr.total == 10
    assert cr.has_more is True


# ---------------------------------------------------------------------------
# title field on ToolSchema, ResourceSchema, PromptSchema
# ---------------------------------------------------------------------------


def test_tool_schema_title_field() -> None:
    ts = ToolSchema(name="find", description="desc", title="Find Items")
    assert ts.title == "Find Items"


def test_tool_schema_title_defaults_to_none() -> None:
    ts = ToolSchema(name="find", description="desc")
    assert ts.title is None


def test_resource_schema_title_field() -> None:
    rs = ResourceSchema(uri="file:///x", name="x", title="My Resource")
    assert rs.title == "My Resource"


def test_resource_schema_title_defaults_to_none() -> None:
    rs = ResourceSchema(uri="file:///x", name="x")
    assert rs.title is None


def test_prompt_schema_title_field() -> None:
    ps = PromptSchema(name="greet", title="Greet User")
    assert ps.title == "Greet User"


def test_prompt_schema_title_defaults_to_none() -> None:
    ps = PromptSchema(name="greet")
    assert ps.title is None


# ---------------------------------------------------------------------------
# All new types importable from lauren_mcp top-level
# ---------------------------------------------------------------------------


def test_all_new_types_importable_from_top_level() -> None:
    import lauren_mcp

    for name in [
        "AudioContent",
        "ResourceLink",
        "ToolUseContent",
        "ToolResultContent",
        "ResourceAnnotations",
        "Role",
        "UrlElicitResult",
        "McpUrlElicitationNotAvailable",
        "CompletionResult",
        "validate_sampling_messages",
    ]:
        assert hasattr(lauren_mcp, name), f"lauren_mcp.{name} not found"


def test_new_types_in_init_all() -> None:
    import lauren_mcp

    for name in [
        "AudioContent",
        "ResourceLink",
        "ToolUseContent",
        "ToolResultContent",
        "ResourceAnnotations",
        "UrlElicitResult",
        "McpUrlElicitationNotAvailable",
        "CompletionResult",
    ]:
        assert name in lauren_mcp.__all__, f"{name!r} not in lauren_mcp.__all__"


# ---------------------------------------------------------------------------
# Role type alias
# ---------------------------------------------------------------------------


def test_role_type_alias_is_literal() -> None:
    # Role is Literal["user", "assistant"] — verify the alias exists and has
    # the expected args
    assert typing.get_args(Role) == ("user", "assistant")


# ---------------------------------------------------------------------------
# SamplingMessage.to_dict with new content types
# ---------------------------------------------------------------------------


def test_sampling_message_tool_use_to_dict() -> None:
    tuc = ToolUseContent(id="c1", name="search", input={"query": "python"})
    msg = SamplingMessage(role="assistant", content=tuc)
    d = msg.to_dict()
    assert d["role"] == "assistant"
    assert d["content"]["type"] == "tool_use"
    assert d["content"]["id"] == "c1"


def test_sampling_message_tool_result_to_dict() -> None:
    trc = ToolResultContent(
        tool_use_id="c1",
        content=[TextContent(text="10 results")],
    )
    msg = SamplingMessage(role="user", content=trc)
    d = msg.to_dict()
    assert d["role"] == "user"
    assert d["content"]["type"] == "tool_result"
    assert d["content"]["tool_use_id"] == "c1"
