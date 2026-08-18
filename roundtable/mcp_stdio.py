"""A minimal Model Context Protocol server, speaking JSON-RPC 2.0 over stdio.

MCP's stdio transport is newline-delimited JSON on stdin and stdout, and a
tools-only server needs exactly four methods. That is little enough to
implement directly, which buys something worth more than the code it costs:
the roundtable installs with zero dependencies, so Killy adds it to Claude with
one command and never meets a virtualenv.

The one hard rule of this transport: **stdout carries protocol frames and
nothing else.** Every diagnostic goes to stderr, or it corrupts the stream.
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, IO

#: Protocol revisions this server knows how to speak. The client's requested
#: version is echoed back when we recognise it, otherwise we answer with the
#: newest one we know and let the client decide.
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class Tool:
    """One callable Claude can see."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def log(message: str) -> None:
    """Diagnostics go to stderr — stdout belongs to the protocol."""
    print(f"[roundtable] {message}", file=sys.stderr, flush=True)


class McpServer:
    """Serves a fixed set of tools over the stdio transport."""

    def __init__(self, name: str, version: str, tools: list[Tool]):
        self.name = name
        self.version = version
        self.tools = {tool.name: tool for tool in tools}

    # -- request handling -------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one message. Returns a response, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")

        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        is_notification = "id" not in message

        if not isinstance(method, str):
            return None if is_notification else self._error(
                msg_id, INVALID_REQUEST, "missing method"
            )

        # Notifications get no reply, ever — answering one is a protocol bug.
        if is_notification:
            return None

        try:
            if method == "initialize":
                return self._ok(msg_id, self._initialize(params))
            if method == "ping":
                return self._ok(msg_id, {})
            if method == "tools/list":
                return self._ok(
                    msg_id, {"tools": [t.spec() for t in self.tools.values()]}
                )
            if method == "tools/call":
                return self._ok(msg_id, self._call_tool(params))
            return self._error(msg_id, METHOD_NOT_FOUND, f"unknown method {method!r}")
        except ValueError as exc:
            return self._error(msg_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # pragma: no cover - last line of defence
            log(f"internal error in {method}: {traceback.format_exc()}")
            return self._error(msg_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else LATEST_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise ValueError("tools/call needs a tool name")
        tool = self.tools.get(name)
        if tool is None:
            known = ", ".join(sorted(self.tools)) or "none"
            raise ValueError(f"unknown tool {name!r}; available: {known}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object")

        try:
            result = tool.handler(arguments)
        except Exception as exc:
            # A failing tool is reported inside the result, not as a transport
            # error: Claude should read the failure and adapt, not lose the turn.
            log(f"tool {name} failed: {traceback.format_exc()}")
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            }

        return {"content": [{"type": "text", "text": _as_text(result)}], "isError": False}

    # -- framing -----------------------------------------------------------

    @staticmethod
    def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    def serve(self, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
        """Read messages until stdin closes."""
        source = stdin or sys.stdin
        sink = stdout or sys.stdout
        log(f"{self.name} {self.version} ready ({len(self.tools)} tools)")

        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(sink, self._error(None, PARSE_ERROR, f"invalid JSON: {exc}"))
                continue
            response = self.handle(message)
            if response is not None:
                self._write(sink, response)

    @staticmethod
    def _write(sink: IO[str], payload: dict[str, Any]) -> None:
        sink.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sink.flush()


def _as_text(result: Any) -> str:
    """Render a tool's return value as the text Claude reads."""
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)
