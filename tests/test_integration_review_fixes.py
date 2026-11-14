"""Regression tests for the defects found reviewing PRs #36-#46 together.

Each test pins one fix made on the integration branch:

- statute sections keep their letters and hyphens, and govinfo never
  reports a different section as the cited one;
- the CourtListener token only goes to CourtListener;
- quotation checks see through HTML entities;
- a connector approval covers exactly one action;
- PACER's paid case search is gated per case number;
- the dashboard cannot decide an action unless a person started it;
- tables added to the base schema reach existing databases;
- playbook must_contain treats "without ..." as a condition, not an exclusion;
- the PDF writer keeps WinAnsi punctuation.
"""
import json
import sqlite3
import threading
import urllib.error

import pytest

from hermes_legal import db, serve
from hermes_legal.citations import (
    CourtListenerClient, GovInfoClient, govinfo_section_root, parse_citation,
)
from hermes_legal.connectors import (
    ApprovalRequired, ClioConnector, CourtListenerConnector, DurablePendingActionStore,
    FakeTransport, MemoryCredentialStore, PacerConnector, RecapCheckRequired,
)
from hermes_legal.playbooks import parse_playbook, review_contract

from tests.test_dashboard import REDLINE, propose_redline, request, running, world  # noqa: F401


class _Resp:
    def __init__(self, body, url=""):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self._url = url

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------------- statutes

@pytest.mark.parametrize("text,section,root", [
    ("42 U.S.C. § 2000e-2", "2000e-2", "2000e-2"),
    ("15 U.S.C. § 78j(b)", "78j(b)", "78j"),
    ("42 U.S.C. § 1396a", "1396a", "1396a"),
    ("26 U.S.C. § 501(c)(3)", "501(c)(3)", "501"),
    ("42 U.S.C. § 1983 (2018)", "1983", "1983"),
])
def test_statute_sections_keep_letters_and_hyphens(text, section, root):
    cite = parse_citation(text)
    assert cite.kind == "statute" and cite.section == section
    assert govinfo_section_root(cite.section) == root


def govinfo(routes):
    """A GovInfoClient whose opener serves ``routes`` (link path -> outcome)."""
    def opener(request, timeout=None):
        for fragment, outcome in routes.items():
            if f"/link/uscode/{fragment}?" in request.full_url:
                if isinstance(outcome, int):
                    raise urllib.error.HTTPError(request.full_url, outcome, "error", {}, None)
                return outcome
        raise urllib.error.URLError("unexpected URL")
    return GovInfoClient(opener=opener)


def test_nonexistent_hyphenated_section_is_not_verified_as_its_parent():
    # Before the fix "2000e-99" was looked up as "2000e", which exists.
    client = govinfo({
        "42/2000e": _Resp("<p>Definitions</p>",
                          "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/"
                          "USCODE-2024-title42-chap21-subchapVI-sec2000e.htm"),
        "42/2000e-99": 400,  # what the live link service answers
    })
    result = client.verify("42 U.S.C. § 2000e-99")
    assert result.status == "unverified"
    assert "HTTP 400" in result.detail


def test_govinfo_landing_on_another_section_is_not_verification():
    client = govinfo({"42/1983": _Resp(
        "<p>other text</p>",
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/USCODE-2024-title42-sec1981.htm")})
    result = client.verify("42 U.S.C. § 1983")
    assert result.status == "unverified"
    assert "different page" in result.detail


def test_govinfo_reports_the_edition_it_actually_resolved():
    client = govinfo({"42/2000e-2": _Resp(
        "<p>Unlawful employment practices</p>",
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/"
        "USCODE-2024-title42-chap21-subchapVI-sec2000e-2.htm")})
    result = client.verify("42 U.S.C. § 2000e-2")
    assert result.status == "exists"
    assert "USCODE-2024-title42" in result.detail


def test_quote_check_unescapes_html_entities():
    client = govinfo({"42/1983": _Resp(
        "<p>&#8220;Every person who, under color of any statute&#8221; &sect; shall be liable</p>",
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title42/html/USCODE-2024-title42-sec1983.htm")})
    result = client.verify("42 U.S.C. § 1983", quote="Every person who, under color of any statute")
    assert result.status == "quote_verified"


def test_courtlistener_token_never_goes_to_another_host():
    lookup = [{"citation": "678 F. Supp. 3d 443", "status": 200, "clusters": [{
        "case_name": "Mata v. Avianca, Inc.",
        "sub_opinions": ["https://attacker.example/opinions/1/",
                         "https://www.courtlistener.com/api/rest/v4/opinions/2/"]}]}]
    seen = []

    def opener(request, timeout=None):
        seen.append(request.full_url)
        if request.full_url.endswith("/citation-lookup/"):
            return _Resp(json.dumps(lookup))
        if "/opinions/2/" in request.full_url:
            return _Resp(json.dumps({"plain_text": "the court imposed sanctions"}))
        raise urllib.error.URLError("unexpected URL")

    client = CourtListenerClient(token="secret-token", opener=opener)
    client.verify("678 F. Supp. 3d 443", quote="imposed sanctions")
    assert not any("attacker.example" in url for url in seen)


# ------------------------------------------------------------- connectors

def clio(tmp_path):
    t = FakeTransport()
    t.add("POST", "https://app.clio.com/api/v4/matters.json", lambda req: (201, {"data": {"id": 9}}))
    creds = MemoryCredentialStore()
    creds.set("clio", "access_token", "synthetic")
    store = DurablePendingActionStore(db.connect(tmp_path / "legal.db"))
    return t, ClioConnector(t, creds, pending_store=store), store


def test_an_approval_for_one_action_never_approves_another(tmp_path):
    t, c, _ = clio(tmp_path)
    first, second = c.create_matter("First"), c.create_matter("Second")
    record = c.record_approval("catduck", action=first)
    with pytest.raises(ApprovalRequired):
        second.approve(record.approval_id)
    with pytest.raises(ApprovalRequired):
        second.approve("catduck")
    assert t.calls == []
    assert first.approve(record.approval_id)["data"]["id"] == 9


def test_an_unbound_approval_is_single_use(tmp_path):
    t, c, store = clio(tmp_path)
    first, second = c.create_matter("First"), c.create_matter("Second")
    store.record_approval("catduck")  # recorded before any action id was known
    first.approve("catduck")
    with pytest.raises(ApprovalRequired):
        second.approve("catduck")
    assert len(t.calls_to("POST")) == 1


def test_pacer_paid_search_needs_a_recap_check_of_that_case():
    t = FakeTransport()
    t.add("GET", "https://www.courtlistener.com/api/rest/v4/search/", lambda req: (200, {"results": []}))
    creds = MemoryCredentialStore()
    creds.set("pacer", "username", "u")
    creds.set("pacer", "password", "p")
    pacer = PacerConnector(t, creds, recap=CourtListenerConnector(t, MemoryCredentialStore()))
    pacer.locate_case("1:26-cv-00001")
    with pytest.raises(RecapCheckRequired):
        pacer.search_pacer_cases("1:26-cv-00002", approved_by="catduck")
    assert t.calls_to("POST", "pcl.uscourts.gov") == []


# -------------------------------------------------------------- dashboard

def test_dashboard_started_without_a_terminal_cannot_decide(running, world):
    conn, *_ = world
    server = running(allow_decisions=False)
    action = propose_redline(server)["result"]
    action_id = str(action["action_id"])
    status, body = request(server, "POST", "/actions/approve",
                           form={"id": action_id, "by": "catduck", "confirm": action_id})
    assert status == 403 and "needs_interactive_terminal" in body
    pending = conn.execute("SELECT status FROM pending_actions WHERE id=?", (int(action_id),)).fetchone()
    assert pending[0] == "pending"


def test_serve_disables_decisions_when_stdin_is_not_a_terminal(monkeypatch, tmp_path):
    captured = {}

    class Stop(Exception):
        pass

    def fake_make_server(*args, **kwargs):
        captured.update(kwargs)
        raise Stop

    monkeypatch.setattr(serve, "make_server", fake_make_server)
    monkeypatch.setattr(serve.sys, "stdin", type("NoTTY", (), {"isatty": lambda self: False})())
    with pytest.raises(Stop):
        serve.serve(db_path=tmp_path / "legal.db")
    assert captured["allow_decisions"] is False


# --------------------------------------------------------------- database

def test_a_table_added_to_the_schema_reaches_an_existing_database(tmp_path):
    path = tmp_path / "legal.db"
    db.connect(path).close()
    raw = sqlite3.connect(path)
    raw.execute("DROP TABLE ceiling_raises")  # stands in for a table added to SCHEMA later
    raw.commit()
    raw.close()
    conn = db.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ceiling_raises" in tables


# -------------------------------------------------------------- playbooks

def test_without_prior_written_consent_still_contains_written():
    pb = parse_playbook(
        "id: nda\nname: NDA\n\n## Rules\n\n"
        "### require-confidentiality\n"
        "title: Confidentiality is required\nkind: required\nseverity: high\n"
        "topic: confidentiality\npatterns: confidential information\n"
        "must_contain: written\n"
        "rationale: Disclosure needs written consent.\n"
        "fallback: Neither party discloses Confidential Information without prior written consent.\n")
    contract = ("## 2. Confidentiality\n"
                "Neither party shall disclose Confidential Information without the prior "
                "written consent of the other party.\n")
    findings = [f for f in review_contract(contract, pb).findings if f.rule_id == "require-confidentiality"]
    assert findings == []


# -------------------------------------------------------------------- PDF

def test_pdf_writer_keeps_winansi_punctuation():
    pytest.importorskip("pypdf")
    from hermes_legal.pdf_tools import build_text_pdf, extract_text_layer
    pdf = build_text_pdf(["The party’s “notice” under § 12 — final."])
    text = extract_text_layer(pdf).pages[0].text
    assert "’" in text and "“" in text and "—" in text and "?" not in text
