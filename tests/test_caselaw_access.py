"""Offline tests for the Caselaw Access Project (CAP) citation resolver."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from hermes_legal import citations, cli


class _FakeResponse:
    def __init__(self, payload):
        self._raw = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _cap_client(payload=None, *, exc=None, token="cap-test-token"):
    calls = []

    def opener(request, timeout=15.0):
        calls.append((request.full_url, dict(request.header_items())))
        if exc is not None:
            raise exc
        return _FakeResponse(payload)

    return citations.CaselawAccessClient(token=token, opener=opener), calls


def test_cap_single_match_and_quote_verification():
    payload = {
        "count": 1,
        "results": [{
            "name_abbreviation": "Hadley v. Baxendale",
            "frontend_url": "https://cite.case.law/ex/9/341/",
            "casebody": {
                "data": {
                    "opinions": [{"text": "<p>Where two parties have made a contract which one of them has broken.</p>"}]
                }
            },
        }],
    }
    client, calls = _cap_client(payload)
    res = client.verify("156 Eng. Rep. 145")
    assert res.status == "exists"
    assert res.source == "caselaw-access-project"
    assert res.matched_name == "Hadley v. Baxendale"
    assert res.source_url == "https://cite.case.law/ex/9/341/"
    assert "full_case=true" not in calls[0][0]

    verified = client.verify("156 Eng. Rep. 145", quote="made a contract which one of them has broken")
    assert verified.status == "quote_verified"
    assert "full_case=true" in calls[1][0]

    missing_quote = client.verify("156 Eng. Rep. 145", quote="not in the opinion")
    assert missing_quote.status == "quote_not_verified"


def test_cap_quote_without_casebody_stays_exists():
    payload = {"count": 1, "results": [{"name_abbreviation": "Acme v. Roe", "url": "https://api.case.law/v1/cases/1/"}]}
    client, _ = _cap_client(payload)
    res = client.verify("347 U.S. 483", quote="separate educational facilities")
    assert res.status == "exists"


def test_cap_not_found_ambiguous_and_errors():
    empty_client, _ = _cap_client({"count": 0, "results": []})
    assert empty_client.verify("999 U.S. 999").status == "not_found"

    ambig_client, _ = _cap_client({"count": 2, "results": [{"name_abbreviation": "A v. B"}, {"name_abbreviation": "C v. D"}]})
    assert ambig_client.verify("100 F.3d 1").status == "ambiguous"

    http_err = urllib.error.HTTPError("https://api.case.law/v1/cases/", 429, "Too Many Requests", {}, io.BytesIO(b""))
    err_client, _ = _cap_client(exc=http_err)
    assert err_client.verify("347 U.S. 483").status == "unverified"

    bad_json_client, _ = _cap_client("not-json")
    assert bad_json_client.verify("347 U.S. 483").status == "unverified"


def test_cap_ignores_statutes_without_network_call():
    client, calls = _cap_client({"count": 0, "results": []})
    res = client.verify("42 U.S.C. § 1983")
    assert res.status == "unverified"
    assert calls == []


def test_router_fallback_and_ceiling_guard():
    cl_calls = []

    def cl_opener(request, timeout=15.0):
        cl_calls.append(request.full_url)
        return _FakeResponse([{"status": 404, "clusters": []}])

    cl = citations.CourtListenerClient(token="cl-token", opener=cl_opener)
    cap, cap_calls = _cap_client({"count": 1, "results": [{"name_abbreviation": "Brown v. Board of Education"}]})
    router = citations.ResolverRouter(case_resolver=cl, fallback_case_resolver=cap)

    res = router.verify("347 U.S. 483")
    assert res.status == "exists"
    assert res.source == "caselaw-access-project"
    assert len(cl_calls) == 1
    assert len(cap_calls) == 1

    guarded = citations.CeilingGuardedResolver(router, "LOCAL_ONLY")
    blocked = guarded.verify("347 U.S. 483")
    assert blocked.status == "unverified"
    assert len(cap_calls) == 1


def test_cli_default_resolver_wires_cap_token(monkeypatch):
    for name in (*citations.COURTLISTENER_TOKEN_ENV, *citations.CAP_TOKEN_ENV, *citations.GOVINFO_API_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    assert cli._default_cite_resolver() is None

    monkeypatch.setenv("HERMES_LEGAL_CAP_TOKEN", "cap-123")
    resolver = cli._default_cite_resolver()
    assert isinstance(resolver, citations.ResolverRouter)
    assert isinstance(resolver.case_resolver, citations.CaselawAccessClient)
