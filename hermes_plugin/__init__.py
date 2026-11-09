"""Thin Hermes adapter. Loads the tools from a trusted local checkout
(HERMES_LEGAL_APP_DIR), opens the database read-only, never creates a missing
database, and reads keys only from Hermes, never from a secrets file.

Every call goes through hermes_legal.dispatch, which owns the privacy and
approval rules. A write only saves a pending action for a person to approve.
"""
import json
import logging
import os
import pathlib
import sys

logger = logging.getLogger(__name__)

TOOLSET = "hermes_legal"
UNATTENDED_PLATFORMS = ("cron", "subagent")
_unattended_sessions = set()


def _load_dispatch():
    """The app's dispatch module from the configured checkout, or None."""
    app_dir = os.environ.get("HERMES_LEGAL_APP_DIR", "").strip()
    if not app_dir:
        return None
    src = pathlib.Path(app_dir).expanduser().resolve() / "src"
    if not (src / "hermes_legal" / "dispatch.py").is_file():
        return None
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from hermes_legal import dispatch

    return dispatch


def _make_handler(runtime, name):
    def handler(args, session_id=None, **_):
        unattended = session_id in _unattended_sessions
        try:
            ctx = runtime.Context.open("hermes", unattended=unattended)
        except runtime.ToolError as exc:
            return json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}})
        try:
            return json.dumps(runtime.dispatch(name, args, ctx))
        finally:
            ctx.close()

    return handler


def _note_session(session_id=None, platform=None, **_):
    if platform in UNATTENDED_PLATFORMS and session_id:
        _unattended_sessions.add(session_id)


def _make_write_guard(write_tools):
    def guard(tool_name=None, session_id=None, **_):
        if tool_name in write_tools and session_id in _unattended_sessions:
            return {"action": "block", "message": f"{tool_name} changes something, so it is refused in an unattended run."}
        return None

    return guard


def register(ctx):
    runtime = _load_dispatch()
    if runtime is None:
        logger.warning("hermes-legal: set HERMES_LEGAL_APP_DIR to a prepared checkout to enable its tools")
        return
    tools = runtime.available_tools()
    for tool in tools:
        ctx.register_tool(
            name=tool["name"],
            toolset=TOOLSET,
            schema={"name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]},
            handler=_make_handler(runtime, tool["name"]),
            description=tool["description"],
        )
    ctx.register_hook("pre_llm_call", _note_session)
    ctx.register_hook("pre_tool_call", _make_write_guard({t["name"] for t in tools if t["write"]}))
