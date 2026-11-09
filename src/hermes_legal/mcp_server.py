"""MCP over stdio: the same legal_* tools, read-only by default.

Write tools are listed only after `legal mcp allow-writes on`, and even then a
call saves a pending action for a person to approve; it never applies anything.
Standard library only, so the server works on a default install. The database
is opened per call, so a missing database is a tool error rather than a crash.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

from . import dispatch as runtime

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
UNATTENDED_ENV = "HERMES_LEGAL_UNATTENDED"
ALLOW_WRITES_KEY = "mcp_allow_writes"


def writes_allowed(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (ALLOW_WRITES_KEY,)).fetchone()
    except sqlite3.OperationalError:  # The settings table has not been created yet.
        return False
    return bool(row) and row[0] == "on"


def set_writes_allowed(conn: sqlite3.Connection, allowed: bool) -> None:
    runtime.ensure_tables(conn)
    conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (ALLOW_WRITES_KEY, "on" if allowed else "off"))
    conn.commit()


def _context() -> runtime.Context:
    return runtime.Context.open("mcp", unattended=os.environ.get(UNATTENDED_ENV, "") == "1")


def _list_tools(context_factory) -> list[dict]:
    try:
        ctx = context_factory()
    except runtime.ToolError:
        include_writes = False
    else:
        try:
            include_writes = writes_allowed(ctx.conn)
        finally:
            ctx.close()
    return [{"name": tool["name"], "description": tool["description"], "inputSchema": tool["input_schema"],
             "annotations": {"readOnlyHint": not tool["write"]}}
            for tool in runtime.available_tools(include_writes=include_writes)]


def _call_tool(name: str, arguments, context_factory) -> dict:
    try:
        ctx = context_factory()
    except runtime.ToolError as exc:
        outcome = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
    else:
        try:
            tool = runtime.TOOLS_BY_NAME.get(name)
            if tool is not None and tool.write and not writes_allowed(ctx.conn):
                outcome = {"ok": False, "error": {"code": "writes_disabled", "message": "Writes are off for MCP. A person can run: legal mcp allow-writes on"}}
            else:
                outcome = runtime.dispatch(name, arguments, ctx)
        finally:
            ctx.close()
    return {"content": [{"type": "text", "text": json.dumps(outcome, indent=2)}], "isError": not outcome["ok"]}


def handle(message, context_factory=_context):
    """One JSON-RPC message in, one response out, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in message:
        return None
    request_id, method = message["id"], message["method"]
    params = message.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {"protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "hermes-legal", "version": _version()}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _list_tools(context_factory)}
    elif method == "tools/call":
        result = _call_tool(params.get("name"), params.get("arguments"), context_factory)
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _version() -> str:
    from . import __version__
    return __version__


def serve(stdin=None, stdout=None, context_factory=_context) -> int:
    """Read newline-delimited JSON-RPC until the client closes stdin."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for stream in (stdin, stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    for line in stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line), context_factory)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0
