"""McpServerModule — Lauren DI module factory for MCP servers."""

from __future__ import annotations

from typing import Any

from lauren import Scope, injectable, module, post_construct, pre_destruct

from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp._server._context import VALID_LOG_LEVELS, LogLevelState
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._handshake import build_initialize_result
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp._server._session import SseSessionStore
from lauren_mcp._server._sse import mcp_http_sse_controller
from lauren_mcp._server._streamable import (
    StreamableSessionStore,
    mcp_streamable_http_controller,
)
from lauren_mcp._server._subscriptions import ResourceSubscriptionManager
from lauren_mcp._server._ws import mcp_ws_controller
from lauren_mcp._types import (
    ClientCapabilities,
    Implementation,
    InitializeParams,
    ServerCapabilities,
)

from ._handlers import (
    make_completion_handler,
    make_context_factory,
    make_prompts_get_handler,
    make_prompts_list_handler,
    make_resources_list_handler,
    make_resources_read_handler,
    make_tools_call_handler,
    make_tools_list_handler,
)
from ._meta import (
    MCP_COMPLETION_META,
    MCP_LIFESPAN_META,
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpCompletionMeta,
    McpLifespanMeta,
    McpPromptMeta,
    McpResourceMeta,
    McpServerMeta,
    McpToolMeta,
)

#: Transport spellings accepted by :meth:`McpServerModule.for_root`.
_TRANSPORTS = ("ws", "sse", "streamable", "both", "all")


class McpServerModule:
    """Namespace for the :meth:`for_root` class factory."""

    @staticmethod
    def for_root(
        server_cls: type,
        *,
        transport: str = "ws",
        server_info: Implementation | None = None,
        capabilities: ServerCapabilities | None = None,
        providers: list[Any] | None = None,
        imports: list[Any] | None = None,
        exports: list[Any] | None = None,
        log_level: str = "debug",
        mounts: list[tuple[type, str]] | None = None,
        proxies: list[tuple[Any, str]] | None = None,
        instrument_otel: bool | None = None,
    ) -> type:
        """Build a Lauren ``@module`` that wires *server_cls* into the MCP stack.

        Parameters
        ----------
        server_cls:
            A class decorated with ``@mcp_server``.  Must have a
            ``__mcp_server_meta__`` attribute attached by the decorator.
        transport:
            ``"ws"`` — WebSocket only (default).
            ``"sse"`` — legacy HTTP+SSE only (MCP 2024-11-05).
            ``"streamable"`` — Streamable HTTP only (MCP 2025-03-26).
            ``"both"`` — WebSocket + legacy HTTP+SSE.
            ``"all"`` — WebSocket + Streamable HTTP.  (Legacy SSE and
            Streamable HTTP share the ``POST /`` route, so they cannot be
            mounted together on one path.)
        server_info:
            Optional :class:`~lauren_mcp._types.Implementation` describing this
            server; defaults to ``Implementation(name=server_cls.__name__,
            version="1.0.0")``.
        capabilities:
            Optional :class:`~lauren_mcp._types.ServerCapabilities` override.
            When ``None`` the capabilities are inferred from which
            ``@mcp_tool`` / ``@mcp_resource`` / ``@mcp_prompt`` methods the
            class exposes (with ``listChanged: True`` and logging enabled).
        providers:
            Extra Lauren providers to add to the generated module.  Use this
            to make services visible to *server_cls* via constructor injection.
        imports:
            Extra Lauren ``@module`` classes to import into the generated module.
        exports:
            Extra types to export from the generated module.
        log_level:
            Minimum severity for client-bound log notifications emitted via
            ``ctx.log()`` (``"debug"`` | ``"info"`` | ``"warning"`` |
            ``"error"``).  Clients may raise it at runtime with
            ``logging/setLevel``.
        mounts:
            ``[(OtherServerCls, "prefix_"), ...]`` — expose another
            ``@mcp_server`` class's tools / resources / prompts through this
            server, names prefixed to avoid collisions.  Colliding names
            raise :class:`~lauren_mcp.McpToolNameCollision` at startup.
        proxies:
            ``[(client, "prefix_"), ...]`` — connect each
            :class:`~lauren_mcp.McpClientProtocol` at startup and re-export
            the remote server's tools under the prefix.  Calls are forwarded
            over the client; connections close at shutdown.
        instrument_otel:
            ``True``  — always instrument with OpenTelemetry (raises
            ``ImportError`` if ``opentelemetry-api`` is not installed).
            ``False`` — never instrument.
            ``None``  — auto-detect: instrument if ``opentelemetry-api`` is
            installed (default).

        Returns
        -------
        type
            A ``@module`` class ready to be imported by the root application
            module.

        Raises
        ------
        TypeError
            If *server_cls* was not decorated with ``@mcp_server``.
        ValueError
            If *transport* is not one of the accepted spellings.
        """
        # ------------------------------------------------------------------
        # 1. Validate server_cls and transport
        # ------------------------------------------------------------------
        server_meta: McpServerMeta | None = getattr(server_cls, MCP_SERVER_META, None)
        if server_meta is None:
            raise TypeError(
                f"{server_cls!r} is not an MCP server class. "
                "Decorate it with @mcp_server before passing to McpServerModule.for_root()."
            )
        effective_transport = transport or server_meta.transport
        if effective_transport not in _TRANSPORTS:
            raise ValueError(
                f"Unknown transport {effective_transport!r}; expected one of {_TRANSPORTS}"
            )

        # ------------------------------------------------------------------
        # 2. Collect tool / resource / prompt / lifespan / completion metadata
        # ------------------------------------------------------------------
        tools: list[McpToolMeta] = []
        resources: list[McpResourceMeta] = []
        prompts: list[McpPromptMeta] = []
        completions: list[McpCompletionMeta] = []
        lifespan_meta: McpLifespanMeta | None = None

        # Import decorator-reader helper once for the loop below.
        from ._decorators import _read_method_decorators as _rmd  # noqa: PLC0415

        for attr_name in dir(server_cls):
            try:
                attr = getattr(server_cls, attr_name)
            except AttributeError:
                continue

            tool_meta: McpToolMeta | None = getattr(attr, MCP_TOOL_META, None)
            if tool_meta is not None:
                # Re-read all 4 decorator attrs at for_root() time from the
                # fully-decorated method (all outer decorators already applied).
                _deco = _rmd(attr)
                if _deco["guards"] and not tool_meta.guards:
                    tool_meta.guards = _deco["guards"]
                if _deco["interceptors"] and not tool_meta.interceptors:
                    tool_meta.interceptors = _deco["interceptors"]
                if _deco["exception_handlers"] and not tool_meta.exception_handlers:
                    tool_meta.exception_handlers = _deco["exception_handlers"]
                if _deco["tool_metadata"] and not tool_meta.tool_metadata:
                    tool_meta.tool_metadata = _deco["tool_metadata"]
                tools.append(tool_meta)

            resource_meta: McpResourceMeta | None = getattr(attr, MCP_RESOURCE_META, None)
            if resource_meta is not None:
                _deco = _rmd(attr)
                if _deco["guards"] and not resource_meta.guards:
                    resource_meta.guards = _deco["guards"]
                if _deco["interceptors"] and not resource_meta.interceptors:
                    resource_meta.interceptors = _deco["interceptors"]
                if _deco["exception_handlers"] and not resource_meta.exception_handlers:
                    resource_meta.exception_handlers = _deco["exception_handlers"]
                if _deco["tool_metadata"] and not resource_meta.tool_metadata:
                    resource_meta.tool_metadata = _deco["tool_metadata"]
                resources.append(resource_meta)

            prompt_meta: McpPromptMeta | None = getattr(attr, MCP_PROMPT_META, None)
            if prompt_meta is not None:
                _deco = _rmd(attr)
                if _deco["guards"] and not prompt_meta.guards:
                    prompt_meta.guards = _deco["guards"]
                if _deco["interceptors"] and not prompt_meta.interceptors:
                    prompt_meta.interceptors = _deco["interceptors"]
                if _deco["exception_handlers"] and not prompt_meta.exception_handlers:
                    prompt_meta.exception_handlers = _deco["exception_handlers"]
                if _deco["tool_metadata"] and not prompt_meta.tool_metadata:
                    prompt_meta.tool_metadata = _deco["tool_metadata"]
                prompts.append(prompt_meta)

            completion_meta_val: McpCompletionMeta | None = getattr(attr, MCP_COMPLETION_META, None)
            if completion_meta_val is not None:
                completions.append(completion_meta_val)

            ls_meta: McpLifespanMeta | None = getattr(attr, MCP_LIFESPAN_META, None)
            if ls_meta is not None:
                if lifespan_meta is not None:
                    raise TypeError(
                        f"{server_cls.__name__} declares more than one @mcp_lifespan "
                        "method; merge them into a single generator."
                    )
                lifespan_meta = ls_meta

        # ------------------------------------------------------------------
        # 3. Build ServerCapabilities (auto or caller-supplied)
        # ------------------------------------------------------------------
        if capabilities is None:
            resolved_caps = ServerCapabilities(
                tools={"listChanged": True} if tools else None,
                resources={"listChanged": True, "subscribe": True} if resources else None,
                prompts={"listChanged": True} if prompts else None,
                logging={},
            )
        else:
            resolved_caps = capabilities

        # Whether to include completions capability in the initialize response.
        # Stored separately because ServerCapabilities doesn't (yet) have a
        # completions field — avoids touching _types.py.
        _has_completions = bool(completions)

        # ------------------------------------------------------------------
        # 4. Resolve server_info
        # ------------------------------------------------------------------
        resolved_server_info: Implementation = server_info or Implementation(
            name=server_cls.__name__,
            version="1.0.0",
        )

        # ------------------------------------------------------------------
        # 5. Build transport controller(s)
        #
        # All Lauren ``@use_*`` metadata declared on *server_cls* — guards,
        # interceptors, middlewares, encoder, exception_handlers, and user
        # metadata (@set_metadata) — is propagated onto the generated
        # transport controllers via ``propagate_metadata(server_cls)``.
        # ------------------------------------------------------------------
        path: str = server_meta.path

        controllers: list[type] = []
        if effective_transport in ("ws", "both", "all"):
            controllers.append(mcp_ws_controller(path, source=server_cls))
        if effective_transport in ("sse", "both"):
            controllers.append(mcp_http_sse_controller(path, source=server_cls))
        if effective_transport in ("streamable", "all"):
            controllers.append(mcp_streamable_http_controller(path, source=server_cls))

        # ------------------------------------------------------------------
        # 6. Capture all resolved values in closure-friendly locals
        # ------------------------------------------------------------------
        _tools = tools
        _resources = resources
        _prompts = prompts
        _completions = completions
        _lifespan_meta = lifespan_meta
        _resolved_caps = resolved_caps
        _resolved_server_info = resolved_server_info
        _log_level = log_level
        _instrument_otel = instrument_otel
        _server_metadata: dict[str, Any] = dict(
            getattr(server_cls, "__lauren_metadata__", None) or {}
        )

        # ------------------------------------------------------------------
        # 7. Build the handler-registrar injectable.
        # ------------------------------------------------------------------
        @injectable(scope=Scope.SINGLETON)
        class _McpHandlerRegistrar:
            """Singleton that wires handler coroutines onto the dispatcher."""

            def __init__(
                self,
                dispatcher: McpDispatcher,
                registry: McpConnectionRegistry,
                catalog: McpCatalogManager,
                subscriptions: ResourceSubscriptionManager,
                server_instance: server_cls,  # type: ignore[valid-type]
            ) -> None:
                self._dispatcher = dispatcher
                self._registry = registry
                self._catalog = catalog
                self._subscriptions = subscriptions
                self._server_instance = server_instance
                self._lifespan_gen: Any = None
                self._lifespan_ctx: dict[str, Any] = {}
                self._log_state = LogLevelState(_log_level)
                self._container: Any = None  # populated at @post_construct time via gc

            @post_construct
            async def _register_handlers(self) -> None:
                """Run the lifespan hook and wire all MCP handlers."""
                dispatcher = self._dispatcher
                srv = self._server_instance
                catalog = self._catalog
                sub_mgr = self._subscriptions

                # Discover the DI container that created this singleton via gc.
                # This runs once at startup and is O(n) in live objects — acceptable
                # for initialisation cost.  Allows per-tool guards/interceptors to
                # resolve their DI dependencies without any user-side wiring.
                try:
                    import gc  # noqa: PLC0415

                    from lauren import DIContainer  # noqa: PLC0415

                    for _obj in gc.get_objects():
                        if isinstance(_obj, DIContainer) and any(
                            v is self for v in _obj._singletons.values()
                        ):
                            self._container = _obj
                            break
                except Exception:  # noqa: BLE001
                    pass  # Container discovery failed — guards will be skipped

                # --- lifespan ---
                if _lifespan_meta is not None:
                    gen = getattr(srv, _lifespan_meta.method_name)()
                    ctx = await gen.__anext__()
                    if ctx is None:
                        ctx = {}
                    if not isinstance(ctx, dict):
                        raise TypeError(
                            "@mcp_lifespan generator must yield a dict (or None), "
                            f"got {type(ctx).__name__}"
                        )
                    self._lifespan_gen = gen
                    self._lifespan_ctx = ctx

                # --- catalog seeding (silent: broadcast fn not yet attached) ---
                for t in _tools:
                    catalog.register_tool(t)
                for r in _resources:
                    catalog.register_resource(r)
                for p in _prompts:
                    catalog.register_prompt(p)
                catalog.set_broadcast_fn(self._registry.broadcast_method)

                # --- initialize ---
                _si = _resolved_server_info
                _sc = _resolved_caps

                async def _initialize_handler(params: dict[str, Any] | None) -> dict[str, Any]:
                    params = params or {}
                    client_caps_raw = params.get("capabilities") or {}
                    client_info_raw = params.get("clientInfo") or {}
                    client_caps = ClientCapabilities(
                        roots=client_caps_raw.get("roots"),
                        sampling=client_caps_raw.get("sampling"),
                        elicitation=client_caps_raw.get("elicitation"),
                        experimental=client_caps_raw.get("experimental"),
                    )
                    client_info = Implementation(
                        name=client_info_raw.get("name", "unknown"),
                        version=client_info_raw.get("version", "0.0.0"),
                    )
                    init_params = InitializeParams(
                        protocolVersion=params.get("protocolVersion", "2024-11-05"),
                        capabilities=client_caps,
                        clientInfo=client_info,
                    )
                    result = build_initialize_result(init_params, _si, _sc)
                    caps_dict: dict[str, Any] = {}
                    if result.capabilities.tools is not None:
                        caps_dict["tools"] = result.capabilities.tools
                    if result.capabilities.resources is not None:
                        caps_dict["resources"] = result.capabilities.resources
                    if result.capabilities.prompts is not None:
                        caps_dict["prompts"] = result.capabilities.prompts
                    if result.capabilities.logging is not None:
                        caps_dict["logging"] = result.capabilities.logging
                    if result.capabilities.experimental is not None:
                        caps_dict["experimental"] = result.capabilities.experimental
                    # completions is not a field on ServerCapabilities yet; handle separately
                    if _has_completions:
                        caps_dict["completions"] = {}
                    return {
                        "protocolVersion": result.protocolVersion,
                        "capabilities": caps_dict,
                        "serverInfo": {
                            "name": result.serverInfo.name,
                            "version": result.serverInfo.version,
                        },
                        **(
                            {"instructions": result.instructions}
                            if result.instructions is not None
                            else {}
                        ),
                    }

                dispatcher.register("initialize", _initialize_handler)

                # --- logging/setLevel ---
                log_state = self._log_state

                async def _set_level(params: dict[str, Any] | None) -> dict[str, Any]:
                    level = (params or {}).get("level")
                    if level not in VALID_LOG_LEVELS:
                        raise ValueError(f"Invalid log level: {level!r}")
                    log_state.level = level
                    return {}

                dispatcher.register("logging/setLevel", _set_level)

                # --- shared context factory ---
                context_factory = make_context_factory(
                    _server_metadata,
                    lifespan_getter=lambda: self._lifespan_ctx,
                    log_level_state=log_state,
                )

                from lauren_mcp._types import JsonRpcRequest as _Req  # noqa: PLC0415

                # --- tools (catalog-backed; registered even when empty so
                #     dynamically added tools work) ---
                _tl_inner = make_tools_list_handler(catalog.list_tools)
                _tc_inner = make_tools_call_handler(
                    srv,
                    catalog.list_tools,
                    context_factory=context_factory,
                    dispatcher=dispatcher,
                    container=self._container,
                    owning_module=_McpModule,
                    server_metadata=_server_metadata,
                )

                async def _tools_list(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _tl_inner(_Req(method="tools/list", params=params))

                async def _tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _tc_inner(_Req(method="tools/call", params=params))

                dispatcher.register("tools/list", _tools_list)
                dispatcher.register("tools/call", _tools_call)

                # --- resources ---
                _rl_inner = make_resources_list_handler(catalog.list_resources)
                _rr_inner = make_resources_read_handler(
                    srv,
                    catalog.list_resources,
                    container=self._container,
                    owning_module=_McpModule,
                    server_metadata=_server_metadata,
                )

                async def _resources_list(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _rl_inner(_Req(method="resources/list", params=params))

                async def _resources_read(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _rr_inner(_Req(method="resources/read", params=params))

                dispatcher.register("resources/list", _resources_list)
                dispatcher.register("resources/read", _resources_read)

                # --- resources/subscribe, resources/unsubscribe ---
                async def _resources_subscribe(
                    params: dict[str, Any] | None,
                ) -> dict[str, Any]:
                    from lauren_mcp._server._binding import CURRENT_BINDING  # noqa: PLC0415

                    p = params or {}
                    uri = p.get("uri")
                    if not uri:
                        raise ValueError("resources/subscribe requires 'uri'")
                    binding = CURRENT_BINDING.get()
                    session_key = (binding.session_id or "unknown") if binding else "unknown"
                    send_notification = binding.send_notification if binding else None
                    if send_notification is None:
                        raise ValueError("resources/subscribe requires a push-capable transport")
                    # Wrap the dict-based send_notification into a raw-string SendFn
                    import json as _json  # noqa: PLC0415

                    _sn = send_notification

                    async def _raw_send(raw: str) -> None:
                        await _sn(_json.loads(raw))

                    sub_mgr.subscribe(uri, session_key, _raw_send)
                    return {}

                async def _resources_unsubscribe(
                    params: dict[str, Any] | None,
                ) -> dict[str, Any]:
                    from lauren_mcp._server._binding import CURRENT_BINDING  # noqa: PLC0415

                    p = params or {}
                    uri = p.get("uri")
                    if not uri:
                        raise ValueError("resources/unsubscribe requires 'uri'")
                    binding = CURRENT_BINDING.get()
                    session_key = (binding.session_id or "unknown") if binding else "unknown"
                    sub_mgr.unsubscribe(uri, session_key)
                    return {}

                dispatcher.register("resources/subscribe", _resources_subscribe)
                dispatcher.register("resources/unsubscribe", _resources_unsubscribe)

                # --- prompts ---
                _pl_inner = make_prompts_list_handler(catalog.list_prompts)
                _pg_inner = make_prompts_get_handler(srv, catalog.list_prompts)

                async def _prompts_list(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _pl_inner(_Req(method="prompts/list", params=params))

                async def _prompts_get(params: dict[str, Any] | None) -> dict[str, Any]:
                    return await _pg_inner(_Req(method="prompts/get", params=params))

                dispatcher.register("prompts/list", _prompts_list)
                dispatcher.register("prompts/get", _prompts_get)

                # --- completion/complete ---
                if _completions:
                    _cc_inner = make_completion_handler(srv, _completions)

                    async def _completion_complete(
                        params: dict[str, Any] | None,
                    ) -> dict[str, Any]:
                        return await _cc_inner(_Req(method="completion/complete", params=params))

                    dispatcher.register("completion/complete", _completion_complete)

                # --- OpenTelemetry instrumentation ---
                from lauren_mcp._server._otel import (  # noqa: PLC0415
                    instrument_dispatcher,
                    is_otel_available,
                )

                effective_otel = _instrument_otel
                if effective_otel is None:
                    effective_otel = is_otel_available()

                if effective_otel:
                    if not is_otel_available():
                        raise ImportError(
                            "instrument_otel=True requires opentelemetry-api; "
                            "install it with: pip install 'lauren-mcp[otel]'"
                        )
                    instrument_dispatcher(dispatcher)

            @pre_destruct
            async def _shutdown(self) -> None:
                """Close the lifespan generator at server shutdown."""
                gen = self._lifespan_gen
                self._lifespan_gen = None
                if gen is not None:
                    await gen.aclose()

        # With ``from __future__ import annotations`` all annotations are
        # stored as strings.  Lauren's DI evaluates them via
        # ``typing.get_type_hints()``, which looks up names in the module
        # globals — ``server_cls`` is a local, so it won't be found.
        # Override the annotation with the actual class object so the DI
        # compiler can locate the provider.
        _McpHandlerRegistrar.__init__.__annotations__["server_instance"] = server_cls

        _McpHandlerRegistrar.__name__ = f"McpHandlerRegistrar[{server_cls.__name__}]"
        _McpHandlerRegistrar.__qualname__ = _McpHandlerRegistrar.__name__

        # ------------------------------------------------------------------
        # 8. Build the @module class — a thin container; all lifecycle
        #    logic lives in _McpHandlerRegistrar above.
        # ------------------------------------------------------------------
        from lauren.reflect import (  # noqa: PLC0415
            reflect_guards,
            reflect_interceptors,
            reflect_middlewares,
        )

        _composition_providers: list[type] = []
        if mounts:
            from ._composition import make_mount_binder  # noqa: PLC0415

            for mounted_cls, prefix in mounts:
                _composition_providers.append(mounted_cls)
                _composition_providers.append(make_mount_binder(mounted_cls, prefix))
        if proxies:
            from ._composition import make_proxy_binder  # noqa: PLC0415

            for proxy_client, prefix in proxies:
                _composition_providers.append(make_proxy_binder(proxy_client, prefix))

        _existing_extra = set(providers or [])
        _auto_guard_providers: list[type] = [
            cls
            for cls in (
                *reflect_guards(server_cls),
                *reflect_interceptors(server_cls),
                *reflect_middlewares(server_cls),
            )
            if cls not in _existing_extra
        ]
        _auto_guard_set = set(_auto_guard_providers)

        # Collect per-method guard, interceptor, and exception_handler classes
        # not already in providers — auto-register them so DI can resolve them.
        _method_level_providers: list[type] = []
        for _meta_item in (*_tools, *_resources, *_prompts):
            for _cls in (
                *getattr(_meta_item, "guards", ()),
                *getattr(_meta_item, "interceptors", ()),
                *getattr(_meta_item, "exception_handlers", ()),
            ):
                if (
                    isinstance(_cls, type)
                    and _cls not in _existing_extra
                    and _cls not in _auto_guard_set
                    and _cls not in _method_level_providers
                ):
                    _method_level_providers.append(_cls)

        _all_providers = [
            server_cls,
            McpDispatcher,
            SseSessionStore,
            StreamableSessionStore,
            McpConnectionRegistry,
            McpCatalogManager,
            ResourceSubscriptionManager,
            _McpHandlerRegistrar,
            *_composition_providers,
            *_auto_guard_providers,
            *_method_level_providers,
            *(providers or []),
        ]
        _all_imports = list(imports or [])
        _all_exports = list(exports or [])

        @module(
            providers=_all_providers,
            imports=_all_imports,
            exports=_all_exports,
            controllers=controllers,
        )
        class _McpModule:
            """Auto-generated Lauren module for MCP server integration."""

        _McpModule.__name__ = f"McpModule[{server_cls.__name__}]"
        _McpModule.__qualname__ = (
            f"McpServerModule.for_root.<locals>._McpModule[{server_cls.__name__}]"
        )
        # Expose the registrar for tests that need to wire handlers without DI.
        _McpModule._handler_registrar_cls = _McpHandlerRegistrar  # type: ignore[attr-defined]

        return _McpModule
