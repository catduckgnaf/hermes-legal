"""The local dashboard: a loopback-only web surface over ``dispatch``.

``legal serve`` starts this server. It is a thin layer like the MCP server:
every read goes through :func:`hermes_legal.dispatch.dispatch`, every write
is only a proposal through that same entry point, and the pending-actions
queue is decided through :func:`hermes_legal.dispatch.approve` and
:func:`hermes_legal.dispatch.reject` — the same persisted-action contract
the CLI enforces, with no side door:

- A decision needs a named person (``--by`` on the CLI, the ``by`` form
  field here) and typing the action id into the confirm field, the
  dashboard equivalent of the CLI's interactive typed confirmation.
- A server started with ``--unattended`` cannot propose a write and cannot
  decide one, exactly like an unattended dispatch context.

Access is local by construction. The server binds 127.0.0.1 unless an
explicit ``--allow-non-loopback`` override is given (which prints a loud
warning), and every request must carry the per-launch random token, in the
``X-Hermes-Legal-Token`` header or the ``token`` query parameter. A new
token is generated on every launch and is never stored.

The Ask box routes through :func:`hermes_legal.providers.route_and_log`,
the one routing entry point that also writes the per-matter AI log, and
only a local provider proceeds to the local model client. Routing is not
reimplemented here.
"""
from __future__ import annotations

import html
import http.server
import ipaddress
import json
import pathlib
import secrets
import urllib.parse

from . import db, dispatch as runtime, providers

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770
TOKEN_HEADER = "X-Hermes-Legal-Token"
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

_CSS = (
    "body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:56rem;padding:0 1rem}"
    "table{border-collapse:collapse}td,th{border:1px solid #999;padding:.3rem .6rem;text-align:left}"
    "nav a{margin-right:1rem}code{background:#eee;padding:.1rem .3rem}"
    ".warn{border:2px solid #a00;padding:.5rem}.err{color:#a00}"
)


def new_token() -> str:
    """A fresh per-launch dashboard token."""
    return secrets.token_urlsafe(32)


def is_loopback_host(host: str) -> bool:
    """True only for a host that names this computer."""
    name = str(host or "").strip().rstrip(".").casefold()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def default_ask(conn, matter_id: int, question: str) -> dict:
    """Answer one dashboard Ask for a matter.

    Routing (and its AI-log row) goes through ``providers.route_and_log``
    only. ``route_and_log`` records the dashboard routing decision;
    ``local_model.ask_matter`` then records its own call, as it does for
    the CLI. Only a local provider proceeds: the dashboard builds no other
    model path.
    """
    provider = providers.route_and_log(conn, matter_id, action="dashboard ask")
    if not provider.is_local:
        return {"answer": None, "provider": provider.name, "tier": provider.tier,
                "notice": "Only local inference is built, so no model was called."}
    from . import local_model

    outcome = local_model.ask_matter(conn, matter_id, question)
    outcome["provider"] = provider.name
    outcome["tier"] = provider.tier
    return outcome


class _Dashboard:
    """The state one running dashboard server carries."""

    def __init__(self, *, db_path, token, unattended=False, ask_handler=None):
        self.db_path = pathlib.Path(db_path) if db_path else db.default_path()
        self.token = token
        self.unattended = unattended
        self.ask_handler = ask_handler or default_ask

    # ------------------------------------------------------------ plumbing

    def _context(self) -> runtime.Context:
        return runtime.Context.open("dashboard", unattended=self.unattended, path=self.db_path)

    def _write_conn(self):
        if not self.db_path.is_file():
            raise runtime.ToolError(
                "database_missing",
                "No hermes-legal database exists yet; run `legal demo` or `legal matter open` first.")
        return db.connect(self.db_path)

    def _dispatch(self, name, args) -> dict:
        ctx = self._context()
        try:
            return runtime.dispatch(name, args, ctx)
        finally:
            ctx.close()

    # --------------------------------------------------------------- pages

    def page_index(self) -> tuple[int, str]:
        outcome = self._dispatch("legal_matter_list", {})
        if not outcome["ok"]:
            return 503, self._page("Dashboard", f'<p class="err">{_esc(outcome["error"]["message"])}</p>')
        conn = self._write_conn()
        try:
            pending = runtime.list_actions(conn)
        finally:
            conn.close()
        rows = "".join(
            f'<tr><td><a href="{self._url("/matter", matter_id=m["id"])}">{m["id"]}</a></td>'
            f"<td>{_esc(m['name'])}</td><td>{_esc(m['privacy_ceiling'])}</td><td>{_esc(m['status'])}</td></tr>"
            for m in outcome["result"]["matters"])
        body = (
            "<h2>Matters</h2>"
            f"<table><tr><th>Id</th><th>Name</th><th>Privacy ceiling</th><th>Status</th></tr>{rows}</table>"
            f"<p>{len(pending)} pending action(s) in the "
            f'<a href="{self._url("/actions")}">approval queue</a>.</p>'
            "<h2>Ask a matter</h2>" + self._ask_form(outcome["result"]["matters"]))
        return 200, self._page("Hermes Legal dashboard", body)

    def page_matter(self, matter_id: int) -> tuple[int, str]:
        outcome = self._dispatch("legal_matter_get", {"matter_id": matter_id})
        if not outcome["ok"]:
            return 404, self._page("No such matter", f'<p class="err">{_esc(outcome["error"]["message"])}</p>')
        matter = outcome["result"]
        docs = "".join(
            f"<tr><td>{_esc(d['relative_path'])}</td><td>{_esc(d['kind'])}</td><td>{d['size']}</td></tr>"
            for d in matter["documents"])
        deadlines = "".join(
            f"<tr><td>{_esc(d.get('due_at'))}</td><td>{_esc(d.get('title'))}</td><td>{_esc(d.get('status'))}</td></tr>"
            for d in matter.get("deadlines", []))
        body = (
            f"<h2>Matter {matter['id']}: {_esc(matter['name'])}</h2>"
            f"<p>Privacy ceiling: {_esc(matter['privacy_ceiling'])} | Status: {_esc(matter['status'])}</p>"
            f"<h3>Documents</h3><table><tr><th>Path</th><th>Kind</th><th>Bytes</th></tr>{docs}</table>"
            f"<h3>Deadlines</h3><table><tr><th>Due</th><th>Title</th><th>Status</th></tr>{deadlines}</table>"
            f'<p><a href="{self._url("/citations", matter_id=matter_id)}">Citation status for this matter</a></p>'
            "<h3>Ask this matter</h3>" + self._ask_form([matter], selected=matter_id))
        return 200, self._page(f"Matter {matter_id}", body)

    def page_citations(self, matter_id: int) -> tuple[int, str]:
        matter = self._dispatch("legal_matter_get", {"matter_id": matter_id})
        if not matter["ok"]:
            return 404, self._page("No such matter", f'<p class="err">{_esc(matter["error"]["message"])}</p>')
        sections = []
        for record in matter["result"]["documents"]:
            checked = self._dispatch(
                "legal_cite_check", {"matter_id": matter_id, "path": record["relative_path"]})
            if not checked["ok"]:
                continue  # A document type cite-check cannot read has no citation status.
            result = checked["result"]
            rows = "".join(
                f"<tr><td>{_esc(r['citation'])}</td><td>{_esc(r['status'])}</td><td>{_esc(r['source'])}</td></tr>"
                for r in result["results"])
            gate = "allowed" if result["gate"]["allowed"] else "blocked: " + ", ".join(result["gate"]["blocked"])
            sections.append(
                f"<h3>{_esc(record['relative_path'])}</h3>"
                f"<table><tr><th>Citation</th><th>Status</th><th>Source</th></tr>{rows}</table>"
                f"<p>Gate: {_esc(gate)}. {_esc(result['history_note'])}</p>")
        body = (f"<h2>Citation status: matter {matter_id}</h2>"
                "<p>Offline check only; no lookup was run, so a citation with no "
                "resolver result is unverified, never a match.</p>" + "".join(sections))
        return 200, self._page("Citation status", body)

    def page_actions(self) -> tuple[int, str]:
        conn = self._write_conn()
        try:
            actions = runtime.list_actions(conn)
        finally:
            conn.close()
        blocks = []
        for action in actions:
            blocks.append(
                f"<h3>Action {action['id']}: {_esc(action['tool'])}</h3>"
                f"<p>{_esc(action['summary'])}</p>"
                f"<p>Proposed via {_esc(action['surface'])} at {_esc(action['requested_at'])}. "
                "Nothing has changed yet.</p>"
                f'<form method="post" action="{self._url("/actions/approve")}">'
                '<label>Your name <input name="by" required></label> '
                f'<label>Type {action["id"]} to confirm <input name="confirm" required></label> '
                f'<input type="hidden" name="id" value="{action["id"]}">'
                '<button type="submit">Approve and run</button></form>'
                f'<form method="post" action="{self._url("/actions/reject")}">'
                '<label>Your name <input name="by" required></label> '
                f'<label>Type {action["id"]} to confirm <input name="confirm" required></label> '
                f'<input type="hidden" name="id" value="{action["id"]}">'
                '<button type="submit">Reject</button></form>')
        body = "<h2>Pending actions</h2>" + ("".join(blocks) or "<p>Nothing is waiting for approval.</p>")
        if self.unattended:
            body += '<p class="warn">This server runs unattended: write proposals and decisions are refused.</p>'
        return 200, self._page("Pending actions", body)

    # -------------------------------------------------------------- actions

    def call_tool(self, form: dict) -> tuple[int, str]:
        try:
            args = json.loads(form.get("args", "{}"))
        except ValueError as exc:
            return 400, self._page("Bad arguments", f'<p class="err">args is not JSON: {_esc(exc)}</p>')
        outcome = self._dispatch(form.get("name", ""), args)
        status = 200 if outcome["ok"] else 400
        return status, self._page(
            "Tool result",
            f"<pre>{_esc(json.dumps(outcome, indent=2))}</pre>"
            "<p>A write tool only proposes a pending action here; it changes "
            "nothing until a person approves it in the queue.</p>")

    def decide(self, kind: str, form: dict) -> tuple[int, str]:
        if self.unattended:
            return 403, self._page(
                "Refused unattended",
                '<p class="err">refused_unattended: this server runs unattended, '
                "so it cannot decide a pending action.</p>")
        try:
            action_id = int(form.get("id", ""))
        except ValueError:
            return 400, self._page("Bad action id", '<p class="err">id must be an integer.</p>')
        conn = self._write_conn()
        action_status = "pending"
        try:
            action_status = runtime.get_action(conn, action_id)["status"]
            if form.get("confirm", "").strip() != str(action_id):
                return 400, self._page(
                    "Not decided",
                    f'<p class="err">Type the action id ({action_id}) in the confirm '
                    "field to decide it; nothing changed.</p>")
            outcome = (runtime.approve(conn, action_id, form.get("by", "")) if kind == "approve"
                       else runtime.reject(conn, action_id, form.get("by", "")))
        except runtime.ToolError as exc:
            return 400, self._page(
                "Decision refused",
                f'<p class="err">{_esc(exc.code)}: {_esc(exc.message)}</p>'
                f"<p>Action {action_id} is still {_esc(action_status)}.</p>")
        finally:
            conn.close()
        return 200, self._page(
            "Decision recorded",
            f"<p>Action {outcome['action_id']} is now {_esc(outcome['status'])}.</p>"
            f"<pre>{_esc(json.dumps(outcome, indent=2))}</pre>")

    def ask(self, form: dict) -> tuple[int, str]:
        try:
            matter_id = int(form.get("matter_id", ""))
        except ValueError:
            return 400, self._page("Bad matter id", '<p class="err">matter_id must be an integer.</p>')
        question = form.get("question", "").strip()
        if not question:
            return 400, self._page("No question", '<p class="err">Ask needs a question.</p>')
        conn = self._write_conn()
        try:
            outcome = self.ask_handler(conn, matter_id, question)
        except (ValueError, RuntimeError, OSError) as exc:
            return 400, self._page("Ask refused", f'<p class="err">{_esc(exc)}</p>')
        finally:
            conn.close()
        citations = "".join(f"<li>{_esc(c)}</li>" for c in outcome.get("unverified_citations", []))
        body = (
            f"<h2>Ask: matter {matter_id}</h2><p>{_esc(question)}</p>"
            f"<p><strong>{_esc(outcome.get('answer') or '(no answer)')}</strong></p>"
            f"<p>{_esc(outcome.get('notice', ''))}</p>"
            f"<p>Provider: {_esc(outcome.get('provider', outcome.get('badge', '')))}</p>"
            + (f"<p>Unverified citations in the answer:</p><ul>{citations}</ul>" if citations else ""))
        return 200, self._page("Ask result", body)

    # -------------------------------------------------------------- helpers

    def _url(self, path: str, **params) -> str:
        query = urllib.parse.urlencode({"token": self.token, **params})
        return f"{path}?{query}"

    def _ask_form(self, matter_options, selected=None) -> str:
        options = "".join(
            f'<option value="{m["id"]}"{" selected" if m["id"] == selected else ""}>{_esc(m["name"])}</option>'
            for m in matter_options)
        return (
            f'<form method="post" action="{self._url("/ask")}">'
            f'<label>Matter <select name="matter_id">{options}</select></label> '
            '<label>Question <input name="question" size="48" required></label> '
            '<button type="submit">Ask (local model only)</button></form>')

    def _page(self, title: str, body: str) -> str:
        nav = (f'<nav><a href="{self._url("/")}">Matters</a>'
               f'<a href="{self._url("/actions")}">Pending actions</a></nav>')
        return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{_esc(title)}</title>"
                f"<style>{_CSS}</style></head><body><h1>Hermes Legal</h1>{nav}{body}</body></html>")


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, db_path=None,
                token: str | None = None, unattended: bool = False, ask_handler=None,
                allow_non_loopback: bool = False) -> http.server.ThreadingHTTPServer:
    """Build (but do not start) the dashboard server.

    Refuses a non-loopback ``host`` unless ``allow_non_loopback`` is set.
    The token is generated here when not supplied, so two launches never
    share one.
    """
    if not is_loopback_host(host) and not allow_non_loopback:
        raise ValueError(
            f"refusing to bind {host}: the dashboard is loopback-only by default; "
            "pass --allow-non-loopback to override, and understand that the token "
            "is then the only access control")
    dashboard = _Dashboard(db_path=db_path, token=token or new_token(),
                           unattended=unattended, ask_handler=ask_handler)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):  # Keep matter names out of the server log.
            pass

        def _authorized(self, query: dict) -> bool:
            offered = self.headers.get(TOKEN_HEADER) or (query.get("token") or [""])[0]
            return secrets.compare_digest(str(offered), dashboard.token)

        def _send(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _route(self, form: dict | None) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if not self._authorized(query):
                self._send(401, dashboard._page(
                    "Token required",
                    '<p class="err">401: a valid per-launch dashboard token is '
                    "required on every request.</p>"))
                return
            try:
                if form is None and parsed.path == "/":
                    status, body = dashboard.page_index()
                elif form is None and parsed.path == "/matter":
                    status, body = dashboard.page_matter(int((query.get("matter_id") or ["0"])[0]))
                elif form is None and parsed.path == "/citations":
                    status, body = dashboard.page_citations(int((query.get("matter_id") or ["0"])[0]))
                elif form is None and parsed.path == "/actions":
                    status, body = dashboard.page_actions()
                elif form is not None and parsed.path == "/tool":
                    status, body = dashboard.call_tool(form)
                elif form is not None and parsed.path == "/actions/approve":
                    status, body = dashboard.decide("approve", form)
                elif form is not None and parsed.path == "/actions/reject":
                    status, body = dashboard.decide("reject", form)
                elif form is not None and parsed.path == "/ask":
                    status, body = dashboard.ask(form)
                else:
                    status, body = 404, dashboard._page("Not found", '<p class="err">404: no such page.</p>')
            except runtime.ToolError as exc:
                status, body = 503, dashboard._page(
                    "Unavailable", f'<p class="err">{_esc(exc.code)}: {_esc(exc.message)}</p>')
            except ValueError:
                status, body = 400, dashboard._page("Bad request", '<p class="err">400: bad request.</p>')
            self._send(status, body)

        def do_GET(self):
            self._route(None)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            form = {key: values[0] for key, values in urllib.parse.parse_qs(raw).items()}
            # A form may carry the token as a field instead of in the URL.
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if "token" not in query and form.get("token"):
                query["token"] = [form.pop("token")]
                self.path = parsed.path + "?" + urllib.parse.urlencode(
                    {key: values[0] for key, values in query.items()})
            self._route(form)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.dashboard_token = dashboard.token
    server.dashboard = dashboard
    return server


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, db_path=None,
          allow_non_loopback: bool = False, unattended: bool = False) -> int:
    """Run the dashboard until interrupted; return a process exit code."""
    server = make_server(host, port, db_path=db_path, unattended=unattended,
                         allow_non_loopback=allow_non_loopback)
    bound_host, bound_port = server.server_address[:2]
    if not is_loopback_host(bound_host):
        print("*** WARNING: dashboard is bound to a NON-LOOPBACK address. ***")
        print("*** Anyone who can reach this host and learns the token below can ***")
        print("*** read matter data and approve pending actions. Stop this server ***")
        print("*** as soon as you are done. ***")
    print(f"Dashboard at http://{bound_host}:{bound_port}/?token={server.dashboard_token}")
    print(f"Token (required on every request, new on every launch): {server.dashboard_token}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
