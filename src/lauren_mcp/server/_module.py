"""McpServerModule — Lauren DI module factory for MCP servers."""

from __future__ import annotations

from typing import Any

from lauren import Scope, injectable, module, post_construct

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._handshake import build_initialize_result
from lauren_mcp._server._session import SseSessionStore
from lauren_mcp._server._sse import mcp_http_sse_controller
from lauren_mcp._server._ws import mcp_ws_controller
from lauren_mcp._types import (
    ClientCapabilities,
    Implementation,
    InitializeParams,
    ServerCapabilities,
)

from ._handlers import (
    make_prompts_get_handler,
    make_prompts_list_handler,
    make_resources_list_handler,
    make_resources_read_handler,
    make_tools_call_handler,
    make_tools_list_handler,
)
from ._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpPromptMeta,
    McpResourceMeta,
    McpServerMeta,
    McpToolMeta,
)


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
    ) -> type:
        """Build a Lauren ``@module`` that wires *server_cls* into the MCP stack.

        Parameters
        ----------
        server_cls:
            A class decorated with ``@mcp_server``.  Must have a
            ``__mcp_server_meta__`` attribute attached by the decorator.
        transport:
            ``"ws"`` — WebSocket only (default).
            ``"sse"`` — HTTP+SSE only.
            ``"both"`` — register both transports.
        server_info:
            Optional :class:`~lauren_mcp._types.Implementation` describing this
            server; defaults to ``Implementation(name=server_cls.__name__,
            version="1.0.0")``.
        capabilities:
            Optional :class:`~lauren_mcp._types.ServerCapabilities` override.
            When ``None`` the capabilities are inferred from which
            ``@mcp_tool`` / ``@mcp_resource`` / ``@mcp_prompt`` methods the
            class exposes.
        providers:
            Extra Lauren providers to add to the generated module.  Use this
            to make services visible to *server_cls* via constructor injection.
            Example::

                @injectable(scope=Scope.SINGLETON)
                class MyService: ...

                McpServerModule.for_root(MyServer, providers=[MyService])

        imports:
            Extra Lauren ``@module`` classes to import into the generated module.
            Use this to re-use modules that export services needed by *server_cls*::

                @module(providers=[MyService], exports=[MyService])
                class ServiceModule: ...

                McpServerModule.for_root(MyServer, imports=[ServiceModule])

        exports:
            Extra types to export from the generated module so that parent
            modules that import it can see additional providers::

                McpServerModule.for_root(MyServer, providers=[MyService],
                                         exports=[MyService])

        Returns
        -------
        type
            A ``@module`` class ready to be imported by the root application
            module.

        Raises
        ------
        TypeError
            If *server_cls* was not decorated with ``@mcp_server``.
        """
        # ------------------------------------------------------------------
        # 1. Validate server_cls
        # ------------------------------------------------------------------
        server_meta: McpServerMeta | None = getattr(server_cls, MCP_SERVER_META, None)
        if server_meta is None:
            raise TypeError(
                f"{server_cls!r} is not an MCP server class. "
                "Decorate it with @mcp_server before passing to McpServerModule.for_root()."
            )

        # ------------------------------------------------------------------
        # 2. Collect tool / resource / prompt metadata from class methods
        # ------------------------------------------------------------------
        tools: list[McpToolMeta] = []
        resources: list[McpResourceMeta] = []
        prompts: list[McpPromptMeta] = []

        for attr_name in dir(server_cls):
            try:
                attr = getattr(server_cls, attr_name)
            except AttributeError:
                continue

            tool_meta: McpToolMeta | None = getattr(attr, MCP_TOOL_META, None)
            if tool_meta is not None:
                tools.append(tool_meta)

            resource_meta: McpResourceMeta | None = getattr(attr, MCP_RESOURCE_META, None)
            if resource_meta is not None:
                resources.append(resource_meta)

            prompt_meta: McpPromptMeta | None = getattr(attr, MCP_PROMPT_META, None)
            if prompt_meta is not None:
                prompts.append(prompt_meta)

        # ------------------------------------------------------------------
        # 3. Build ServerCapabilities (auto or caller-supplied)
        # ------------------------------------------------------------------
        if capabilities is None:
            auto_caps = ServerCapabilities(
                tools={"listChanged": False} if tools else None,
                resources={"listChanged": False} if resources else None,
                prompts={"listChanged": False} if prompts else None,
            )
            resolved_caps = auto_caps
        else:
            resolved_caps = capabilities

        # ------------------------------------------------------------------
        # 4. Resolve server_info
        # ------------------------------------------------------------------
        resolved_server_info: Implementation = server_info or Implementation(
            name=server_cls.__name__,
            version="1.0.0",
        )

        # ------------------------------------------------------------------
        # 5. Build transport controller(s)
        # ------------------------------------------------------------------
        path: str = server_meta.path
        effective_transport = transport or server_meta.transport

        controllers: list[type] = []
        if effective_transport in ("ws", "both"):
            controllers.append(mcp_ws_controller(path))
        if effective_transport in ("sse", "both"):
            controllers.append(mcp_http_sse_controller(path))

        # ------------------------------------------------------------------
        # 6. Capture all resolved values in closure-friendly locals
        # ------------------------------------------------------------------
        _tools = tools
        _resources = resources
        _prompts = prompts
        _resolved_caps = resolved_caps
        _resolved_server_info = resolved_server_info
        _server_cls = server_cls

        # ------------------------------------------------------------------
        # 7. Build the handler-registrar injectable.
        #
        # Lauren's @module class body is NOT instantiated by the DI
        # container — lifecycle hooks must live on @injectable providers
        # inside ``providers=[...]``.  We generate a unique singleton class
        # per ``for_root()`` call and add it to the providers list so the
        # DI container constructs it (injecting dispatcher + server) and
        # then fires its @post_construct to register all MCP handlers.
        # ------------------------------------------------------------------
        @injectable(scope=Scope.SINGLETON)
        class _McpHandlerRegistrar:
            """Singleton that wires handler coroutines onto the dispatcher."""

            def __init__(
                self,
                dispatcher: McpDispatcher,
                server_instance: server_cls,  # type: ignore[valid-type]
            ) -> None:
                self._dispatcher = dispatcher
                self._server_instance = server_instance

            @post_construct
            def _register_handlers(self) -> None:
                """Wire all MCP method handlers onto the dispatcher."""
                dispatcher = self._dispatcher
                srv = self._server_instance

                # --- initialize ---
                _si = _resolved_server_info
                _sc = _resolved_caps

                async def _initialize_handler(params: dict[str, Any] | None) -> dict[str, Any]:
                    from lauren_mcp._types import (  # noqa: PLC0415
                        Implementation,
                    )

                    params = params or {}
                    client_caps_raw = params.get("capabilities") or {}
                    client_info_raw = params.get("clientInfo") or {}
                    client_caps = ClientCapabilities(
                        roots=client_caps_raw.get("roots"),
                        sampling=client_caps_raw.get("sampling"),
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
                    return {
                        "protocolVersion": result.protocolVersion,
                        "capabilities": {
                            k: v
                            for k, v in {
                                "tools": result.capabilities.tools,
                                "resources": result.capabilities.resources,
                                "prompts": result.capabilities.prompts,
                                "logging": result.capabilities.logging,
                                "experimental": result.capabilities.experimental,
                            }.items()
                            if v is not None
                        },
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

                # --- tools ---
                if _tools:
                    _tl_inner = make_tools_list_handler(_tools)
                    _tc_inner = make_tools_call_handler(srv, _tools)

                    from lauren_mcp._types import JsonRpcRequest as _Req  # noqa: PLC0415

                    async def _tools_list(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req(method="tools/list", params=params)
                        return await _tl_inner(req)

                    async def _tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req(method="tools/call", params=params)
                        return await _tc_inner(req)

                    dispatcher.register("tools/list", _tools_list)
                    dispatcher.register("tools/call", _tools_call)

                # --- resources ---
                if _resources:
                    _rl_inner = make_resources_list_handler(_resources)
                    _rr_inner = make_resources_read_handler(srv, _resources)

                    from lauren_mcp._types import JsonRpcRequest as _Req2  # noqa: PLC0415

                    async def _resources_list(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req2(method="resources/list", params=params)
                        return await _rl_inner(req)

                    async def _resources_read(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req2(method="resources/read", params=params)
                        return await _rr_inner(req)

                    dispatcher.register("resources/list", _resources_list)
                    dispatcher.register("resources/read", _resources_read)

                # --- prompts ---
                if _prompts:
                    _pl_inner = make_prompts_list_handler(_prompts)
                    _pg_inner = make_prompts_get_handler(srv, _prompts)

                    from lauren_mcp._types import JsonRpcRequest as _Req3  # noqa: PLC0415

                    async def _prompts_list(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req3(method="prompts/list", params=params)
                        return await _pl_inner(req)

                    async def _prompts_get(params: dict[str, Any] | None) -> dict[str, Any]:
                        req = _Req3(method="prompts/get", params=params)
                        return await _pg_inner(req)

                    dispatcher.register("prompts/list", _prompts_list)
                    dispatcher.register("prompts/get", _prompts_get)

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
        # Combine built-in providers with any user-supplied extra providers.
        _all_providers = [
            server_cls,
            McpDispatcher,
            SseSessionStore,
            _McpHandlerRegistrar,
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
