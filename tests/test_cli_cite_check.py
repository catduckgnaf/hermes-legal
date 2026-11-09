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
    assert payload["resolver"] == "courtlistener"
    assert payload["citations"][0]["status"] == "exists"
    assert payload["verify_all_gate"]["allowed"] is True


def test_cite_check_ambiguous_resolver_result_blocks(monkeypatch, capsys):
    _clear_token_env(monkeypatch)
    resolver = OfflineResolver({"678 F. Supp. 3d 443": {"status": "ambiguous"}})
    payload = _run(capsys, cite_resolver=resolver)
    assert payload["citations"][0]["status"] == "ambiguous"
    assert payload["verify_all_gate"]["allowed"] is False
    assert payload["verify_all_gate"]["blocked"] == ["678 F. Supp. 3d 443"]
