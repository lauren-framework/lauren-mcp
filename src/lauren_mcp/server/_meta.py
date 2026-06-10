"""Metadata dataclasses attached to MCP-decorated classes and methods."""

from __future__ import annotations

import inspect as _inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from lauren_mcp._types import ToolAnnotations

if TYPE_CHECKING:
    from lauren_mcp._types import ResourceAnnotations

# Attribute names used to store metadata on decorated objects
MCP_SERVER_META = "__mcp_server_meta__"
MCP_TOOL_META = "__mcp_tool_meta__"
MCP_RESOURCE_META = "__mcp_resource_meta__"
MCP_PROMPT_META = "__mcp_prompt_meta__"
MCP_LIFESPAN_META = "__mcp_lifespan_meta__"
MCP_COMPLETION_META = "__mcp_completion_meta__"

#: Sentinel for "no default value supplied" in :class:`HeaderParamSpec`.
_HEADER_NO_DEFAULT = _inspect.Parameter.empty


@dataclass
class HeaderParamSpec:
    """Describes a single ``Header[T]`` parameter on an ``@mcp_tool`` method."""

    header_name: str  # already converted from param_name (underscores → hyphens)
    coerce_to: type  # T from Header[T]
    default: Any  # inspect.Parameter.empty when no default supplied
    is_optional: bool  # True when Optional[Header[T]]
    pipe_chain: list[Any] = field(default_factory=list)


@dataclass
class McpServerMeta:
    """Metadata attached to a class decorated with ``@mcp_server``."""

    path: str
    transport: str  # "ws" | "sse" | "streamable" | "both" | "all"


@dataclass
class McpToolMeta:
    """Metadata attached to a method decorated with ``@mcp_tool``."""

    name: str
    description: str
    input_schema: dict[str, Any]
    method_name: str
    context_param_name: str | None = None
    reads_context: bool = False
    annotations: ToolAnnotations | None = None
    output_schema: dict[str, Any] | None = None
    timeout: float | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    meta: dict[str, Any] = field(default_factory=dict)
    param_descriptions: dict[str, str] = field(default_factory=dict)
    structured_output: bool | None = None
    title: str | None = None
    # --- Feature: pipe chains / FieldDescriptor validation ---
    #: Per-parameter pipe chains collected at decoration time.
    pipe_chains: dict[str, list[Any]] = field(default_factory=dict)
    # --- Feature: BackgroundTasks injection ---
    #: BackgroundTasks parameter name (or comma-separated names), or None.
    bg_tasks_param: str | None = None
    # --- Feature: Depends[callable] ---
    #: param_name → provider callable (the X in Depends[X])
    depends_params: dict[str, Any] = field(default_factory=dict)
    # --- Feature: Header[T] ---
    #: param_name → HeaderParamSpec
    header_params: dict[str, HeaderParamSpec] = field(default_factory=dict)
    # --- Feature: State[T] ---
    #: param_name → T (the class to instantiate)
    state_params: dict[str, type] = field(default_factory=dict)
    # --- Backward-compat aliases ---
    #: Alias for bg_tasks_param; accepted by constructor for compat with older tests.
    bg_param_name: str | None = None
    #: Per-parameter FieldDescriptor / _ParamSpec specs (older API).
    #: In the merged code, validation is embedded in pipe_chains; this field is
    #: kept for backward compatibility with tests that construct McpToolMeta directly.
    param_specs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Sync bg_param_name ↔ bg_tasks_param so both APIs work.
        if self.bg_param_name is not None and self.bg_tasks_param is None:
            self.bg_tasks_param = self.bg_param_name
        elif self.bg_tasks_param is not None and self.bg_param_name is None:
            self.bg_param_name = self.bg_tasks_param


@dataclass
class McpResourceMeta:
    """Metadata attached to a method decorated with ``@mcp_resource``."""

    uri_template: str
    name: str
    description: str | None
    mime_type: str | None
    method_name: str
    query_params: list[str] = field(default_factory=list)
    param_type_hints: dict[str, Any] = field(default_factory=dict)
    annotations: ResourceAnnotations | None = None
    title: str | None = None
    # --- Feature: pipe chains / FieldDescriptor validation ---
    pipe_chains: dict[str, list[Any]] = field(default_factory=dict)
    # --- Feature: BackgroundTasks injection ---
    bg_tasks_param: str | None = None
    # --- Feature: Depends[callable] ---
    depends_params: dict[str, Any] = field(default_factory=dict)
    # --- Feature: Header[T] ---
    header_params: dict[str, HeaderParamSpec] = field(default_factory=dict)
    # --- Feature: State[T] ---
    state_params: dict[str, type] = field(default_factory=dict)


@dataclass
class McpPromptMeta:
    """Metadata attached to a method decorated with ``@mcp_prompt``."""

    name: str
    description: str | None
    arguments: list[dict[str, Any]]  # [{name, description, required}]
    method_name: str
    title: str | None = None


@dataclass
class McpLifespanMeta:
    """Metadata attached to a method decorated with ``@mcp_lifespan``."""

    method_name: str


@dataclass
class McpCompletionMeta:
    """Metadata attached to a method decorated with ``@mcp_completion``."""

    ref_type: str  # "ref/prompt" or "ref/resource"
    target_name: str  # prompt name or resource URI template
    argument_name: str  # the argument this function completes
    method_name: str  # the method to call on the server instance
