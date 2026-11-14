"""The dispatcher, approvals, MCP and the local model client."""
import http.server
import io
import json
import threading

import pytest

from hermes_legal import cli, db, dispatch as runtime, docx_edit, local_model, matters, mcp_server, providers, tooldefs


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv(runtime.AGENT_TIER_ENV, raising=False)
    monkeypatch.delenv(mcp_server.UNATTENDED_ENV, raising=False)
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "contract.docx").write_bytes(docx_edit.make_docx(["The term is one year.", "Governing law is Delaware."]))
    (folder / "note.txt").write_text("See Mata v. Avianca, 2019 WL 4639462.\nThe lease ends in June.", encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Client Alvarez")
    return conn, mid, folder


def agent(tier="LOCAL_ONLY", surface="mcp", **kwargs):
    ctx = runtime.Context.open(surface, environ={runtime.AGENT_TIER_ENV: tier} if tier else {}, **kwargs)
    return ctx


def code(outcome):
    return outcome["error"]["code"]


# ------------------------------------------------------------------ privacy

@pytest.mark.parametrize("tool,args", [
    ("legal_matter_get", {"matter_id": 1}),
    ("legal_doc_read", {"matter_id": 1, "path": "note.txt"}),
    ("legal_doc_search", {"matter_id": 1, "query": "lease"}),
    ("legal_cite_extract", {"matter_id": 1, "path": "note.txt"}),
])
def test_undeclared_agent_gets_no_matter_content(world, tool, args):
    assert code(runtime.dispatch(tool, args, agent(tier=None))) == "agent_tier_undeclared"


def test_cloud_agent_gets_no_content_from_local_only_matter(world):
    outcome = runtime.dispatch("legal_doc_read", {"matter_id": 1, "path": "note.txt"}, agent("STANDARD"))
    assert code(outcome) == "privacy_ceiling"
    assert "lease" not in json.dumps(outcome)


def test_matter_names_are_hidden_from_an_agent_that_may_not_see_them(world):
    outcome = runtime.dispatch("legal_matter_list", {}, agent(tier=None))
    assert outcome["result"]["matters"] == []
    assert outcome["result"]["withheld_by_privacy_ceiling"] == 1
    assert "Alvarez" not in json.dumps(outcome)


def test_local_agent_reads_and_is_warned_the_text_is_untrusted(world):
    result = runtime.dispatch("legal_doc_read", {"matter_id": 1, "path": "contract.docx"}, agent())["result"]
    assert result["segments"][0]["text"] == "The term is one year."
    assert "untrusted" in result["note"]


def test_path_cannot_leave_the_matter_folder(world):
    assert code(runtime.dispatch("legal_doc_read", {"matter_id": 1, "path": "../data/legal.db"}, agent())) == "path_outside_matter"


def test_local_only_matter_is_never_looked_up_online(world):
    class Fails:
        name = "should-not-run"
        def verify(self, *_, **__):
            raise AssertionError("network resolver was called")
    ctx = agent()
    ctx.resolver = Fails()
    result = runtime.dispatch("legal_cite_check", {"matter_id": 1, "path": "note.txt", "lookup": True}, ctx)["result"]
    assert "LOCAL_ONLY" in result["network"]
    assert result["gate"]["allowed"] is False


# ---------------------------------------------------------------- arguments

def test_unknown_and_unbuilt_tools_are_distinct_errors(world):
    assert code(runtime.dispatch("legal_nope", {}, agent())) == "unknown_tool"
    assert code(runtime.dispatch("legal_chronology", {}, agent())) == "not_implemented"


@pytest.mark.parametrize("args", [{}, {"matter_id": "1"}, {"matter_id": True}, {"matter_id": 1, "extra": 1}, "nope"])
def test_bad_arguments_are_refused(world, args):
    assert code(runtime.dispatch("legal_matter_get", args, agent())) == "invalid_arguments"


def test_every_advertised_tool_is_in_the_catalog():
    built = {tool["name"] for tool in runtime.available_tools()}
    assert built
    assert built <= set(tooldefs.TOOL_NAMES)


# ------------------------------------------------------------------ approvals

REDLINE = {"matter_id": 1, "original": "contract.docx", "output": "contract-redline.docx",
           "paragraphs": ["The term is two years.", "Governing law is Delaware."]}


def test_write_changes_nothing_until_approved_then_runs_once(world):
    conn, _, folder = world
    outcome = runtime.dispatch("legal_doc_redline", REDLINE, agent())
    assert outcome["result"]["status"] == "pending_approval"
    assert not (folder / "contract-redline.docx").exists()
    action_id = outcome["result"]["action_id"]
    assert runtime.approve(conn, action_id, "A. Lawyer")["status"] == "executed"
    out = (folder / "contract-redline.docx").read_bytes()
    assert docx_edit.accept_all_text(out)[0] == "The term is two years."
    assert docx_edit.reject_all_text(out)[0] == "The term is one year."
    with pytest.raises(runtime.ToolError, match="already"):
        runtime.approve(conn, action_id, "A. Lawyer")


def test_unattended_run_cannot_propose(world):
    conn, *_ = world
    outcome = runtime.dispatch("legal_doc_redline", REDLINE, agent(unattended=True))
    assert code(outcome) == "refused_unattended"
    assert runtime.list_actions(conn) == []


def test_approval_needs_a_named_person(world):
    conn, *_ = world
    action_id = runtime.dispatch("legal_time_log", {"matter_id": 1, "minutes": 6, "description": "Review"}, agent())["result"]["action_id"]
    with pytest.raises(runtime.ToolError, match="named person"):
        runtime.approve(conn, action_id, "  ")
    assert runtime.get_action(conn, action_id)["status"] == "pending"


def test_rejected_action_cannot_be_approved(world):
    conn, *_ = world
    action_id = runtime.dispatch("legal_time_log", {"matter_id": 1, "minutes": 6, "description": "Review"}, agent())["result"]["action_id"]
    runtime.reject(conn, action_id, "A. Lawyer")
    with pytest.raises(runtime.ToolError, match="already"):
        runtime.approve(conn, action_id, "A. Lawyer")
    assert conn.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 0


def test_arguments_edited_after_proposal_do_not_run(world):
    conn, _, folder = world
    action_id = runtime.dispatch("legal_doc_redline", REDLINE, agent())["result"]["action_id"]
    conn.execute("UPDATE pending_actions SET args_json=replace(args_json, 'two years', 'ten years') WHERE id=?", (action_id,))
    conn.commit()
    assert runtime.approve(conn, action_id, "A. Lawyer")["error"]["code"] == "tampered"
    assert not (folder / "contract-redline.docx").exists()


def test_failed_action_is_final_and_cannot_overwrite(world):
    conn, _, folder = world
    action_id = runtime.dispatch("legal_doc_redline", REDLINE, agent())["result"]["action_id"]
    (folder / "contract-redline.docx").write_bytes(b"precious")
    assert runtime.approve(conn, action_id, "A. Lawyer")["status"] == "failed"
    assert (folder / "contract-redline.docx").read_bytes() == b"precious"
    with pytest.raises(runtime.ToolError, match="already"):
        runtime.approve(conn, action_id, "A. Lawyer")


def test_agent_read_context_cannot_write(world):
    ctx = agent()
    with pytest.raises(Exception, match="readonly"):
        ctx.conn.execute("UPDATE matters SET privacy_ceiling='STANDARD'")


def test_missing_database_is_never_created(tmp_path):
    missing = tmp_path / "none.db"
    with pytest.raises(runtime.ToolError, match="No hermes-legal database"):
        runtime.Context.open("mcp", path=missing)
    assert not missing.exists()


# ------------------------------------------------------------------------ CLI

def test_cli_refuses_approval_without_a_terminal(world, monkeypatch, capsys):
    conn, _, folder = world
    action_id = runtime.dispatch("legal_doc_redline", REDLINE, agent())["result"]["action_id"]
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{action_id}\n"))
    assert cli.main(["actions", "approve", str(action_id), "--by", "An Agent"]) == 2
    assert not (folder / "contract-redline.docx").exists()
    assert "interactive terminal" in capsys.readouterr().err


def test_cli_approval_requires_typing_the_id(world, monkeypatch):
    conn, _, folder = world
    action_id = runtime.dispatch("legal_doc_redline", REDLINE, agent())["result"]["action_id"]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "wrong")
    assert cli.main(["actions", "approve", str(action_id), "--by", "A. Lawyer"]) == 2
    monkeypatch.setattr("builtins.input", lambda _: str(action_id))
    assert cli.main(["actions", "approve", str(action_id), "--by", "A. Lawyer"]) == 0
    assert (folder / "contract-redline.docx").exists()


def test_cli_tool_matches_dispatch(world, capsys):
    assert cli.main(["tool", "legal_deadline_calc", "--args", json.dumps({"rule_id": "frcp-12a1ai-answer-after-service", "trigger_date": "2026-03-02"})]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["due_date"] == "2026-03-23"


# ------------------------------------------------------------------------ MCP

def rpc(method, params=None, id_=1):
    return mcp_server.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def call(name, arguments):
    result = rpc("tools/call", {"name": name, "arguments": arguments})["result"]
    return result, json.loads(result["content"][0]["text"])


def test_mcp_initialize_and_notifications():
    assert rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["protocolVersion"] == "2025-06-18"
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc("nope")["error"]["code"] == -32601


def test_mcp_serve_loop_reports_bad_json_and_keeps_going():
    out = io.StringIO()
    mcp_server.serve(io.StringIO('not json\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_mcp_lists_writes_only_after_a_person_turns_them_on(world, monkeypatch):
    conn, *_ = world
    monkeypatch.setenv(runtime.AGENT_TIER_ENV, "LOCAL_ONLY")
    names = lambda: {tool["name"] for tool in rpc("tools/list")["result"]["tools"]}
    assert "legal_doc_redline" not in names() and "legal_doc_read" in names()
    assert "legal_chronology" not in names()
    result, outcome = call("legal_doc_redline", REDLINE)
    assert result["isError"] and code(outcome) == "writes_disabled"
    mcp_server.set_writes_allowed(conn, True)
    assert "legal_doc_redline" in names()


def test_full_matter_workflow_through_mcp(world, monkeypatch):
    """Open, review, cite-check and redline, ending with a human approval."""
    conn, mid, folder = world
    monkeypatch.setenv(runtime.AGENT_TIER_ENV, "LOCAL_ONLY")
    mcp_server.set_writes_allowed(conn, True)
    assert call("legal_matter_list", {})[1]["result"]["matters"][0]["id"] == mid
    assert call("legal_doc_search", {"matter_id": mid, "query": "Delaware"})[1]["result"]["results"][0]["path"] == "contract.docx"
    cite = call("legal_cite_check", {"matter_id": mid, "path": "note.txt"})[1]["result"]
    assert cite["gate"]["allowed"] is False and "2019 WL 4639462" in " ".join(cite["gate"]["blocked"])
    proposal = call("legal_doc_redline", REDLINE)[1]["result"]
    assert proposal["status"] == "pending_approval" and not (folder / "contract-redline.docx").exists()
    assert runtime.approve(conn, proposal["action_id"], "A. Lawyer")["status"] == "executed"
    assert docx_edit.has_track_changes((folder / "contract-redline.docx").read_bytes())


# ---------------------------------------------------------------- local model

@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://10.0.0.5:11434/v1", "http://localhost.example.com/v1", "ftp://127.0.0.1/"])
def test_non_loopback_endpoints_are_refused(url):
    with pytest.raises(local_model.LocalEndpointError):
        local_model.require_loopback(url)


def test_localhost_that_resolves_elsewhere_is_refused():
    resolve = lambda *_: [(2, 1, 6, "", ("203.0.113.9", 80))]
    with pytest.raises(local_model.LocalEndpointError):
        local_model.require_loopback("http://localhost:11434/v1", resolve=resolve)


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "kimi:cloud", "", "  "])
def test_cloud_tags_and_empty_models_are_refused(model):
    with pytest.raises(local_model.LocalEndpointError):
        local_model.require_local_model(model)


@pytest.fixture
def model_server():
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            answer = {"choices": [{"message": {"content": "It ends in June. See 12 F.3d 34."}}]}
            body = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1", seen
    server.shutdown()


def test_ask_uses_the_local_server_logs_and_flags_citations(world, model_server):
    conn, mid, _ = world
    url, seen = model_server
    outcome = local_model.ask_matter(conn, mid, "When does the lease end?", model="qwen3:8b", client=local_model.LocalModelClient(url))
    assert outcome["unverified_citations"] == ["12 F.3d 34"]
    assert outcome["preview"]["leaves_device"] is False
    assert "lease ends in June" in seen[0]["messages"][1]["content"]
    logged = providers.list_ai_log(conn, mid)
    assert len(logged) == 1 and logged[0]["tier"] == "LOCAL_ONLY" and "prompt_sha256=" in logged[0]["action"]


def test_ask_refuses_a_cloud_tag_before_logging_or_sending(world, model_server):
    conn, mid, _ = world
    url, seen = model_server
    with pytest.raises(local_model.LocalEndpointError):
        local_model.ask_matter(conn, mid, "lease", model="x:cloud", client=local_model.LocalModelClient(url))
    assert seen == [] and providers.list_ai_log(conn, mid) == []
