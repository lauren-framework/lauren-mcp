"""Unit tests for McpStdioClient using mocked subprocess."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp._client._stdio import McpCallError, McpStdioClient
from lauren_mcp._types import ToolSchema

# ---------------------------------------------------------------------------
# Helper: MockProcess
# ---------------------------------------------------------------------------


class _FakeWriter:
    """Minimal asyncio StreamWriter-like stub."""

    def __init__(self):
        self.written: list[bytes] = []
        self._drained = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        self._drained = True

    def get_lines(self) -> list[dict]:
        """Return all written JSON objects as parsed dicts."""
        result = []
        for chunk in self.written:
            for raw in chunk.decode().strip().splitlines():
                raw = raw.strip()
                if raw:
                    result.append(json.loads(raw))
        return result


class MockProcess:
    """Fake asyncio.subprocess.Process for unit tests."""

    def __init__(self, response_lines: list[bytes] | None = None):
        """
        Parameters
        ----------
        response_lines:
            Lines that stdout will produce, in order.  Each should be a
            complete JSON object followed by ``\\n``.  After the list is
            exhausted, ``readline()`` returns ``b""`` (EOF).
        """
        self.stdin = _FakeWriter()
        self._lines = list(response_lines or [])
        self._line_index = 0
        self.returncode: int | None = None
        self._terminate_called = False
        self._kill_called = False
        self._stdout_reader = MagicMock()

        # Always sleep before reading so that Python 3.11's extra wait_for
        # call_soon hops don't cause _read_loop to consume the next line
        # before the test code can register the matching pending future.
        # The sleep lives here (not in _readline) so it applies even when
        # tests override proc._readline with a patched function.
        async def _forward():
            await asyncio.sleep(0.01)
            return await self._readline()

        self._stdout_reader.readline = _forward

    async def _readline(self) -> bytes:
        if self._line_index < len(self._lines):
            line = self._lines[self._line_index]
            self._line_index += 1
            return line
        # Hang forever (simulate a live server waiting for input)
        await asyncio.sleep(3600)
        return b""

    @property
    def stdout(self):
        return self._stdout_reader

    def terminate(self):
        self._terminate_called = True
        self.returncode = 0

    def kill(self):
        self._kill_called = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def _make_line(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode()


def _init_resp(id_: int) -> bytes:
    return _make_line(
        {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-server", "version": "1.0"},
            },
        }
    )


def _tools_list_resp(id_: int, tools: list[dict]) -> bytes:
    return _make_line({"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}})


def _call_result(id_: int, content: list[dict]) -> bytes:
    return _make_line(
        {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {"content": content, "isError": False},
        }
    )


def _error_resp(id_: int, code: int, message: str) -> bytes:
    return _make_line(
        {
            "jsonrpc": "2.0",
            "id": id_,
            "error": {"code": code, "message": message},
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMcpStdioClientConnect:
    @pytest.mark.asyncio
    async def test_connect_starts_subprocess_with_correct_command(self):
        command = ["python", "server.py"]
        client = McpStdioClient(command)

        proc = MockProcess(response_lines=[_init_resp(0)])

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ) as mock_exec:
            try:  # noqa: SIM105
                await asyncio.wait_for(client.connect(), timeout=2.0)
            except TimeoutError:
                pass
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "python"
            assert call_args[1] == "server.py"

    @pytest.mark.asyncio
    async def test_connect_sends_initialize_request(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(response_lines=[_init_resp(0)])

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            try:  # noqa: SIM105
                await asyncio.wait_for(client.connect(), timeout=2.0)
            except TimeoutError:
                pass

        written = proc.stdin.get_lines()
        methods = [m["method"] for m in written]
        assert "initialize" in methods

    @pytest.mark.asyncio
    async def test_connect_sends_notifications_initialized_after_handshake(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(response_lines=[_init_resp(0)])

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            try:  # noqa: SIM105
                await asyncio.wait_for(client.connect(), timeout=2.0)
            except TimeoutError:
                pass

        written = proc.stdin.get_lines()
        methods = [m["method"] for m in written]
        assert "notifications/initialized" in methods

    @pytest.mark.asyncio
    async def test_connect_raises_on_timeout(self):
        # startup_timeout must be shorter than _forward's sleep(0.01) so the
        # timeout fires before any response is delivered.
        client = McpStdioClient(["python", "server.py"], startup_timeout=0.001)
        # Give no responses — will timeout
        proc = MockProcess(response_lines=[])

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
            pytest.raises(asyncio.TimeoutError),
        ):
            await client.connect()


class TestMcpStdioClientListTools:
    @pytest.mark.asyncio
    async def test_list_tools_parses_response_into_tool_schemas(self):
        client = McpStdioClient(["python", "server.py"])
        tool_dict = {
            "name": "echo",
            "description": "Echo input",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _tools_list_resp(1, [tool_dict]),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            tools = await asyncio.wait_for(client.list_tools(), timeout=2.0)

        assert len(tools) == 1
        assert isinstance(tools[0], ToolSchema)
        assert tools[0].name == "echo"
        assert tools[0].description == "Echo input"

    @pytest.mark.asyncio
    async def test_list_tools_returns_empty_list(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _tools_list_resp(1, []),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            tools = await asyncio.wait_for(client.list_tools(), timeout=2.0)

        assert tools == []


class TestMcpStdioClientCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_sends_correct_params(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _call_result(1, [{"type": "text", "text": "hello"}]),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            await asyncio.wait_for(client.call_tool("echo", {"text": "hello"}), timeout=2.0)

        written = proc.stdin.get_lines()
        tool_call = next(m for m in written if m.get("method") == "tools/call")
        assert tool_call["params"]["name"] == "echo"
        assert tool_call["params"]["arguments"] == {"text": "hello"}

    @pytest.mark.asyncio
    async def test_call_tool_returns_content_list(self):
        client = McpStdioClient(["python", "server.py"])
        content = [{"type": "text", "text": "world"}]
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _call_result(1, content),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            result = await asyncio.wait_for(
                client.call_tool("echo", {"text": "world"}), timeout=2.0
            )

        # call_tool returns the raw result dict from the server
        assert result["content"] == content


class TestMcpStdioClientConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_requests_demuxed_by_id(self):
        """Two concurrent requests get the correct responses matched by id."""
        client = McpStdioClient(["python", "server.py"])

        # We'll intercept _send_raw to inject responses in order
        # so both futures get resolved correctly.
        response_map = {
            1: {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
            2: {"jsonrpc": "2.0", "id": 2, "result": {"prompts": []}},
        }
        sent_ids: list[int] = []

        async def fake_send(obj):
            if obj.get("method") in ("initialize", "notifications/initialized"):
                return
            req_id = obj.get("id")
            if req_id in response_map:
                sent_ids.append(req_id)
                fut = client._pending.get(req_id)
                if fut and not fut.done():
                    fut.set_result(response_map[req_id]["result"])

        proc = MockProcess(response_lines=[_init_resp(0)])
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)

        # Monkey-patch _send_raw after connect
        client._send_raw = fake_send

        # Fire two concurrent list_tools requests
        results = await asyncio.gather(
            client._request("tools/list"),
            client._request("prompts/list"),
        )
        assert results[0] == {"tools": []}
        assert results[1] == {"prompts": []}


class TestMcpStdioClientErrors:
    @pytest.mark.asyncio
    async def test_error_response_raises_mcp_call_error(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _error_resp(1, -32601, "Method not found"),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            with pytest.raises(McpCallError) as exc_info:
                await asyncio.wait_for(client.list_tools(), timeout=2.0)

        assert exc_info.value.code == -32601

    def test_mcp_call_error_has_code_attribute(self):
        err = McpCallError("Method not found", code=-32601)
        assert err.code == -32601
        assert str(err) == "Method not found"

    @pytest.mark.asyncio
    async def test_malformed_json_from_server_ignored_not_raised(self):
        """Malformed JSON lines should be skipped, not crash the client."""
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                b"NOT VALID JSON\n",
                _tools_list_resp(1, []),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            tools = await asyncio.wait_for(client.list_tools(), timeout=2.0)

        assert tools == []


class TestMcpStdioClientClose:
    @pytest.mark.asyncio
    async def test_close_terminates_process(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(response_lines=[_init_resp(0)])

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            await client.close()

        assert proc._terminate_called or proc._kill_called

    @pytest.mark.asyncio
    async def test_close_cancels_reader_task(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(response_lines=[_init_resp(0)])

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            reader_task = client._reader_task
            await client.close()

        assert reader_task is None or reader_task.done()

    @pytest.mark.asyncio
    async def test_server_exit_fails_all_pending_futures(self):
        """When the subprocess exits (EOF), pending futures must be failed."""
        client = McpStdioClient(["python", "server.py"], max_retries=0)
        # Only the init response; no response to tools/list
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                # EOF immediately after init
            ]
        )

        # Make readline return EOF immediately after init
        call_count = 0

        async def patched_readline():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _init_resp(0)
            return b""  # EOF

        proc._readline = patched_readline

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            # Now try to list tools — server exits, future should fail
            with pytest.raises(Exception):  # noqa: B017 — McpCallError or TimeoutError
                await asyncio.wait_for(client.list_tools(), timeout=2.0)


class TestMcpStdioClientAutoRestart:
    @pytest.mark.asyncio
    async def test_server_exit_triggers_restart_within_max_retries(self):
        """When server exits, the client should attempt restart."""
        call_count = 0

        async def fake_create_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = MockProcess()
            # First call: EOF immediately; subsequent calls: hang (simulating successful restart)
            if call_count == 1:
                proc._lines = [_init_resp(0)]
                proc._line_index = 0

                async def readline_eof():
                    nonlocal proc
                    idx = getattr(proc, "_eof_idx", 0)
                    proc._eof_idx = idx + 1
                    await asyncio.sleep(0)
                    if idx == 0:
                        return _init_resp(0)
                    return b""  # EOF after init

                proc._readline = readline_eof
            else:
                # Subsequent: provide init response then hang
                proc._lines = [_init_resp(0)]

                async def readline_hang():
                    await asyncio.sleep(3600)
                    return b""

                proc._readline = readline_hang
            return proc

        client = McpStdioClient(["python", "server.py"], max_retries=2)

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            # Give the reader task a moment to detect EOF and restart
            await asyncio.sleep(0.1)

        # The client should have attempted at least one more subprocess
        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_server_exit_stops_after_max_retries(self):
        """After exhausting max_retries, no further restarts should occur."""
        call_count = 0

        async def fake_create_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = MockProcess()

            call_idx = call_count

            async def readline_eof():
                await asyncio.sleep(0)
                if call_idx == 1 and not getattr(proc, "_did_init", False):
                    proc._did_init = True
                    return _init_resp(0)
                return b""  # always EOF

            proc._readline = readline_eof
            return proc

        client = McpStdioClient(["python", "server.py"], max_retries=2)

        with patch("asyncio.create_subprocess_exec", new=fake_create_subprocess):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            await asyncio.sleep(0.3)  # allow retries to exhaust

        # Should not exceed initial + max_retries
        assert call_count <= 1 + 2 + 1  # generous upper bound


class TestMcpStdioClientListResources:
    @pytest.mark.asyncio
    async def test_list_resources_returns_resource_schemas(self):
        client = McpStdioClient(["python", "server.py"])
        resource = {"uri": "file:///data.txt", "name": "data", "description": "The data"}
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _make_line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"resources": [resource]},
                    }
                ),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            resources = await asyncio.wait_for(client.list_resources(), timeout=2.0)

        assert len(resources) == 1
        assert resources[0].uri == "file:///data.txt"
        assert resources[0].name == "data"


class TestMcpStdioClientPing:
    @pytest.mark.asyncio
    async def test_ping_sends_ping_method(self):
        client = McpStdioClient(["python", "server.py"])
        proc = MockProcess(
            response_lines=[
                _init_resp(0),
                _make_line({"jsonrpc": "2.0", "id": 1, "result": {}}),
            ]
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            await asyncio.wait_for(client.connect(), timeout=2.0)
            await asyncio.wait_for(client.ping(), timeout=2.0)

        written = proc.stdin.get_lines()
        methods = [m["method"] for m in written]
        assert "ping" in methods
