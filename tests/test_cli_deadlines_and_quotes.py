"""CLI and agent surfaces for deadline list/confirm/export and cite quotes."""
import json
from pathlib import Path

from hermes_legal import cli, citations, db, deadlines, dispatch as runtime, matters


def _world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "note.txt").write_text("A note.", encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Quote matter")
    return conn, mid


def test_deadlines_cli_lists_confirms_and_exports_with_the_warning(tmp_path, monkeypatch, capsys):
    conn, mid = _world(tmp_path, monkeypatch)
    assert cli.main(["deadlines", "list", str(mid), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["deadlines"] == []
    assert deadlines.VERIFY_WARNING in listed["warning"]

    assert cli.main([
        "deadlines", "confirm", str(mid),
        "--rule-id", "frcp-12a1aii-answer-after-waiver",
        "--trigger-date", "2026-03-02",
        "--title", "Answer after waiver",
        "--by", "A. Lawyer",
    ]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["due_at"] == "2026-05-01"
    assert deadlines.VERIFY_WARNING in confirmed["warning"]

    # Filing deadlines still need two different people. Rule 59 is a filing rule.
    assert cli.main([
        "deadlines", "confirm", str(mid),
        "--rule-id", "frcp-59b-new-trial-motion",
        "--trigger-date", "2026-11-26",
        "--title", "New trial motion",
        "--by", "A. Lawyer",
    ]) == 2

    out = tmp_path / "deadlines.ics"
    assert cli.main(["deadlines", "export-ics", str(mid), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "Answer after waiver" in text
    assert "Verify against local rules" in text
    assert cli.main(["deadlines", "export-ics", str(mid), "-o", str(out)]) == 2
    conn.close()


def test_deadline_list_tool_is_read_only_and_confirm_is_not_a_tool(tmp_path, monkeypatch, capsys):
    conn, mid = _world(tmp_path, monkeypatch)
    deadlines.confirm_calculation(
        conn, mid,
        deadlines.calculate("frcp-33b2-interrogatory-answers", "2026-10-08", "personal"),
        "Answer interrogatories", "A. Lawyer")
    conn.close()
    assert cli.main(["tool", "legal_deadline_list", "--args", json.dumps({"matter_id": mid})]) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["ok"] is True
    assert outcome["result"]["deadlines"][0]["title"] == "Answer interrogatories"
    assert deadlines.VERIFY_WARNING in outcome["result"]["warning"]
    names = set(runtime.IMPLS)
    assert "legal_deadline_confirm" not in names
    assert "legal_deadline_list" in names


def test_cite_check_quote_reaches_quote_verified_and_blocks_when_absent(monkeypatch, capsys):
    for name in citations.COURTLISTENER_TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)
    resolver = citations.OfflineResolver.from_fixture(
        Path(__file__).parent / "fixtures" / "citation_records.json")
    text = "Roe v. Wade, 410 U.S. 113 (1973)."
    assert cli.main([
        "cite-check", text, "--quote", "410 U.S. 113=privacy right",
    ], cite_resolver=resolver) == 0
    present = json.loads(capsys.readouterr().out)
    assert present["citations"][0]["status"] == "quote_verified"
    assert present["verify_all_gate"]["allowed"] is True

    assert cli.main([
        "cite-check", text, "--quote", "410 U.S. 113=this sentence is not in the opinion",
    ], cite_resolver=resolver) == 0
    absent = json.loads(capsys.readouterr().out)
    assert absent["citations"][0]["status"] == "quote_not_verified"
    assert absent["verify_all_gate"]["allowed"] is False


def test_agent_cite_check_accepts_a_quotes_object(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "note.txt").write_text("A note.", encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Quote matter", privacy_ceiling="STANDARD")
    resolver = citations.OfflineResolver.from_fixture(
        Path(__file__).parent / "fixtures" / "citation_records.json")
    ctx = runtime.Context(conn=conn, write_conn=conn, resolver=resolver)
    outcome = runtime.dispatch("legal_cite_check", {
        "text": "Roe v. Wade, 410 U.S. 113 (1973).",
        "matter_id": mid,
        "lookup": True,
        "quotes": {"410 U.S. 113": "not in the synthetic opinion"},
    }, ctx)
    assert outcome["ok"] is True, outcome
    statuses = [row["status"] for row in outcome["result"]["results"]]
    assert "quote_not_verified" in statuses
    assert outcome["result"]["gate"]["allowed"] is False
    ctx.close()
