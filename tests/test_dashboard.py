"""The local dashboard: token-gated, loopback-only, same dispatch contract.

The dashboard is a surface over ``dispatch`` like MCP, so these tests prove
the issue #21 acceptance on this surface too: a write proposed through the
dashboard changes nothing until a named person approves it through the
persisted-action contract, and an unattended server cannot propose or
decide a write at all.
"""
import http.client
import json
import threading
import urllib.parse

import pytest

from hermes_legal import cli, db, dispatch as runtime, docx_edit, local_model, matters, providers, serve


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "contract.docx").write_bytes(docx_edit.make_docx(["The term is one year.", "Governing law is Delaware."]))
    (folder / "note.txt").write_text("See Mata v. Avianca, 2019 WL 4639462.\nThe lease ends in June.", encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Demo — Alvarez (fictional)")
    conn.execute("INSERT INTO deadlines (matter_id, due_at, title) VALUES (?, ?, ?)",
                 (mid, "2026-12-01", "Answer due"))
    conn.commit()
    return conn, mid, folder


@pytest.fixture
def running(world):
    servers = []

    def start(**kwargs):
        kwargs.setdefault("token", "test-token")
        server = serve.make_server("127.0.0.1", 0, **kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def request(server, method, path, *, token="test-token", form=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    body = None
    all_headers = dict(headers or {})
    if token is not None and "token" not in path:
        path += ("&" if "?" in path else "?") + "token=" + token
    if form is not None:
        body = urllib.parse.urlencode(form)
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=body, headers=all_headers)
    response = conn.getresponse()
    text = response.read().decode("utf-8")
    conn.close()
    return response.status, text


REDLINE = {"matter_id": 1, "original": "contract.docx", "output": "contract-redline.docx",
           "paragraphs": ["The term is two years.", "Governing law is Delaware."]}


def propose_redline(server):
    status, body = request(server, "POST", "/tool", form={"name": "legal_doc_redline", "args": json.dumps(REDLINE)})
    assert status == 200
    return json.loads(body.split("<pre>")[1].split("</pre>")[0].replace("&quot;", '"'))


# --------------------------------------------------------------------- access

def test_unauthenticated_and_wrong_token_are_refused(running, world):
    server = running()
    assert request(server, "GET", "/", token=None)[0] == 401
    assert request(server, "GET", "/", token="wrong-token")[0] == 401
    status, body = request(server, "GET", "/", token=None, headers={serve.TOKEN_HEADER: "test-token"})
    assert status == 200 and "Alvarez" in body


def test_token_differs_across_launches(world):
    first, second = serve.make_server("127.0.0.1", 0), serve.make_server("127.0.0.1", 0)
    try:
        assert first.dashboard_token and second.dashboard_token
        assert first.dashboard_token != second.dashboard_token
    finally:
        first.server_close()
        second.server_close()


def test_non_loopback_bind_is_refused_by_default(world):
    with pytest.raises(ValueError, match="loopback-only"):
        serve.make_server("0.0.0.0", 0)


def test_non_loopback_bind_needs_the_explicit_override(world):
    server = serve.make_server("0.0.0.0", 0, allow_non_loopback=True)
    server.server_close()


def test_cli_serve_refuses_a_non_loopback_bind(world, capsys):
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert "loopback-only" in capsys.readouterr().err


def test_cli_serve_delegates_to_the_dashboard(world, monkeypatch):
    seen = {}
    monkeypatch.setattr(serve, "serve", lambda **kwargs: seen.update(kwargs) or 0)
    assert cli.main(["serve", "--port", "8799"]) == 0
    assert seen["port"] == 8799 and seen["host"] == "127.0.0.1" and seen["allow_non_loopback"] is False


# ---------------------------------------------------------------------- pages

def test_authenticated_pages_render_demo_matter_data(running, world):
    _, mid, _ = world
    server = running()
    status, index = request(server, "GET", "/")
    assert status == 200 and "Alvarez" in index and "approval queue" in index
    status, detail = request(server, "GET", f"/matter?matter_id={mid}")
    assert status == 200
    assert "contract.docx" in detail and "note.txt" in detail and "Answer due" in detail and "2026-12-01" in detail


def test_citation_status_view_renders_offline_statuses(running, world):
    _, mid, _ = world
    server = running()
    status, body = request(server, "GET", f"/citations?matter_id={mid}")
    assert status == 200
    assert "2019 WL 4639462" in body and "unverified" in body and "blocked" in body


# ------------------------------------------------------------- write contract

def test_write_through_dashboard_cannot_execute_without_approval(running, world):
    conn, _, folder = world
    server = running()
    outcome = propose_redline(server)
    assert outcome["result"]["status"] == "pending_approval"
    action_id = outcome["result"]["action_id"]
    assert not (folder / "contract-redline.docx").exists()

    # No named approver: refused, still pending, still nothing on disk.
    status, body = request(server, "POST", "/actions/approve",
                           form={"id": action_id, "by": "", "confirm": str(action_id)})
    assert status == 400 and "approver_required" in body
    assert runtime.get_action(conn, action_id)["status"] == "pending"
    assert not (folder / "contract-redline.docx").exists()

    # No typed confirmation: refused the same way.
    status, _ = request(server, "POST", "/actions/approve",
                        form={"id": action_id, "by": "A. Lawyer", "confirm": "yes"})
    assert status == 400
    assert runtime.get_action(conn, action_id)["status"] == "pending"

    # A named person who types the id approves through dispatch, once.
    status, body = request(server, "POST", "/actions/approve",
                           form={"id": action_id, "by": "A. Lawyer", "confirm": str(action_id)})
    assert status == 200 and "executed" in body
    assert docx_edit.has_track_changes((folder / "contract-redline.docx").read_bytes())
    status, body = request(server, "POST", "/actions/approve",
                           form={"id": action_id, "by": "A. Lawyer", "confirm": str(action_id)})
    assert status == 400 and "already_decided" in body


def test_dashboard_reject_records_the_decision_and_changes_nothing(running, world):
    conn, *_ = world
    server = running()
    status, _ = request(server, "POST", "/tool", form={
        "name": "legal_time_log", "args": json.dumps({"matter_id": 1, "minutes": 6, "description": "Review"})})
    assert status == 200
    action_id = runtime.list_actions(conn)[0]["id"]
    status, body = request(server, "POST", "/actions/reject",
                           form={"id": action_id, "by": "A. Lawyer", "confirm": str(action_id)})
    assert status == 200 and "rejected" in body
    assert conn.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 0


def test_unattended_dashboard_refuses_proposals_and_decisions(running, world):
    conn, _, folder = world
    server = running(unattended=True)
    status, body = request(server, "POST", "/tool", form={"name": "legal_doc_redline", "args": json.dumps(REDLINE)})
    assert status == 400 and "refused_unattended" in body
    assert runtime.list_actions(conn) == []

    ctx = runtime.Context(conn=conn, write_conn=conn, surface="dashboard")
    action_id = runtime.dispatch("legal_doc_redline", REDLINE, ctx)["result"]["action_id"]
    status, body = request(server, "POST", "/actions/approve",
                           form={"id": action_id, "by": "A. Lawyer", "confirm": str(action_id)})
    assert status == 403 and "refused_unattended" in body
    assert runtime.get_action(conn, action_id)["status"] == "pending"
    assert not (folder / "contract-redline.docx").exists()


# ------------------------------------------------------------------------ ask

def test_ask_box_uses_the_injected_handler_and_renders_its_answer(running, world):
    _, mid, _ = world
    seen = {}

    def fake_ask(conn, matter_id, question):
        seen.update(matter_id=matter_id, question=question)
        return {"answer": "It ends in June.", "provider": "Local (test)", "notice": "Draft.",
                "unverified_citations": ["12 F.3d 34"]}

    server = running(ask_handler=fake_ask)
    status, body = request(server, "POST", "/ask", form={"matter_id": mid, "question": "When does the lease end?"})
    assert status == 200 and "It ends in June." in body and "12 F.3d 34" in body
    assert seen == {"matter_id": mid, "question": "When does the lease end?"}


def test_default_ask_routes_only_through_route_and_log(world, monkeypatch):
    conn, mid, _ = world
    calls = []
    monkeypatch.setattr(local_model, "ask_matter",
                        lambda conn_, matter_id, question: calls.append(question) or
                        {"answer": "June.", "notice": "Draft.", "unverified_citations": []})
    outcome = serve.default_ask(conn, mid, "When does the lease end?")
    assert outcome["answer"] == "June." and outcome["tier"] == "LOCAL_ONLY"
    logged = providers.list_ai_log(conn, mid)
    assert [row["action"] for row in logged] == ["dashboard ask"]
    assert calls == ["When does the lease end?"]
