"""`legal cite-check` resolver wiring: offline without a token, resolver
with one. All tests are offline; resolvers are injected or replay fixtures.
"""
import json
from pathlib import Path

import hermes_legal.citations as citations_module
from hermes_legal import cli
from hermes_legal.citations import (
    COURTLISTENER_TOKEN_ENV,
    OfflineResolver,
    VerificationResult,
)

FIXTURES = Path(__file__).parent / "fixtures"
DOC = "Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)."


def _clear_token_env(monkeypatch):
    for name in COURTLISTENER_TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)


def _run(capsys, *args, **kwargs):
    assert cli.main(["cite-check", DOC], **kwargs) == 0
    return json.loads(capsys.readouterr().out)


def test_cite_check_without_token_stays_fully_offline(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    payload = _run(capsys)
    assert payload["resolver"] is None
    assert payload["citations"][0]["status"] == "unverified"
    assert payload["status"] == "unverified"
    assert "no resolver was run" in payload["note"]
    assert payload["verify_all_gate"]["allowed"] is False


def test_cite_check_selector_is_none_without_token_and_client_with_token(monkeypatch):
    _clear_token_env(monkeypatch)
    assert cli._default_cite_resolver() is None
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    client = cli._default_cite_resolver()
    assert client is not None and client.has_token is True


def test_cite_check_runs_injected_resolver(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    resolver = OfflineResolver.from_fixture(FIXTURES / "citation_records.json")
    payload = _run(capsys, cite_resolver=resolver)
    assert payload["resolver"] == "offline-fixture"
    assert payload["citations"][0]["status"] == "exists"
    assert payload["verify_all_gate"]["allowed"] is True


def test_cite_check_runs_resolver_when_token_is_configured(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")

    class FakeClient:
        name = "courtlistener"

        def __init__(self, *args, **kwargs):
            self.has_token = True

        def verify(self, citation, quote=None):
            return VerificationResult(
                citation="678 F. Supp. 3d 443", status="exists", source=self.name,
                matched_name="Mata v. Avianca, Inc.")

    monkeypatch.setattr(citations_module, "CourtListenerClient", FakeClient)
    payload = _run(capsys)
    # The default resolver is now the router pairing CourtListener (cases)
    # with govinfo (statutes); the case citation still resolves through
    # the CourtListener side.
    assert payload["resolver"] == "courtlistener+govinfo"
    assert payload["citations"][0]["status"] == "exists"
    assert payload["verify_all_gate"]["allowed"] is True


class _CountingResolver:
    name = "counting"

    def __init__(self):
        self.calls = 0

    def verify(self, citation, quote=None):
        self.calls += 1
        return VerificationResult(
            citation="678 F. Supp. 3d 443", status="exists", source=self.name)


def test_cite_check_local_only_makes_zero_resolver_calls(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    resolver = _CountingResolver()
    assert cli.main(["cite-check", DOC, "--privacy-ceiling", "LOCAL_ONLY"],
                    cite_resolver=resolver) == 0
    payload = json.loads(capsys.readouterr().out)
    assert resolver.calls == 0
    assert payload["citations"][0]["status"] == "unverified"
    assert payload["verify_all_gate"]["allowed"] is False
    assert payload["privacy_ceiling"] == "LOCAL_ONLY"
    preview = payload["lookup_preview"]
    assert preview["blocked"] is True
    assert preview["would_send"] == []
    assert preview["citations"] == ["678 F. Supp. 3d 443"]
    assert "LOCAL_ONLY" in payload["note"]


def test_cite_check_standard_ceiling_runs_resolver_and_previews_send(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    resolver = _CountingResolver()
    assert cli.main(["cite-check", DOC, "--privacy-ceiling", "STANDARD"],
                    cite_resolver=resolver) == 0
    payload = json.loads(capsys.readouterr().out)
    assert resolver.calls == 1
    assert payload["citations"][0]["status"] == "exists"
    assert payload["lookup_preview"]["blocked"] is False
    assert payload["lookup_preview"]["would_send"] == ["678 F. Supp. 3d 443"]


def test_default_resolver_pairs_govinfo_for_statutes(monkeypatch):
    _clear_token_env(monkeypatch)
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token")
    router = cli._default_cite_resolver()
    assert router is not None
    assert router.name == "courtlistener+govinfo"
    assert router.statute_resolver is not None
    assert router.statute_resolver.name == "govinfo"


# --- `legal cite-attest` ------------------------------------------------------

from hermes_legal import db as db_module  # noqa: E402
from hermes_legal.citations import load_attestations  # noqa: E402


def test_cite_attest_records_who_when_and_source(tmp_path, capsys):
    conn = db_module.connect(tmp_path / "legal.db")
    rc = cli.main(
        ["cite-attest", "42 U.S.C. § 1983", "--by", "catduck",
         "--source", "United States Code (govinfo)"],
        attest_conn=conn)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["citation"] == "42 U.S.C. § 1983"
    assert payload["citation_class"] == "statute"
    assert payload["attested_by"] == "catduck"
    assert payload["source"] == "United States Code (govinfo)"
    assert payload["attested_at"]  # the store recorded when
    saved = load_attestations(conn)["42 U.S.C. § 1983"]
    assert saved.attested_by == "catduck"
    assert saved.source == "United States Code (govinfo)"


def test_cite_attest_records_westlaw_citation(tmp_path, capsys):
    conn = db_module.connect(tmp_path / "legal.db")
    rc = cli.main(
        ["cite-attest", "2019 WL 4639462", "--by", "catduck", "--source", "Westlaw"],
        attest_conn=conn)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["citation_class"] == "westlaw"


def test_cite_attest_rejects_ordinary_case_citation(tmp_path, capsys):
    conn = db_module.connect(tmp_path / "legal.db")
    rc = cli.main(
        ["cite-attest", "678 F. Supp. 3d 443", "--by", "catduck", "--source", "Westlaw"],
        attest_conn=conn)
    assert rc == 2
    assert "error" in capsys.readouterr().err
    assert load_attestations(conn) == {}


def test_cite_attest_requires_who_and_source(tmp_path):
    conn = db_module.connect(tmp_path / "legal.db")
    rc = cli.main(
        ["cite-attest", "42 U.S.C. § 1983", "--by", "  ", "--source", "Westlaw"],
        attest_conn=conn)
    assert rc == 2


def test_cite_check_ambiguous_resolver_result_blocks(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    resolver = OfflineResolver({"678 F. Supp. 3d 443": {"status": "ambiguous"}})
    payload = _run(capsys, cite_resolver=resolver)
    assert payload["citations"][0]["status"] == "ambiguous"
    assert payload["verify_all_gate"]["allowed"] is False
    assert payload["verify_all_gate"]["blocked"] == ["678 F. Supp. 3d 443"]
