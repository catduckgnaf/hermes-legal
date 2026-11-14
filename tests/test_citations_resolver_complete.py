"""Completion of the resolver path for issues #3 and #22.

All tests are offline: govinfo and CourtListener responses are recorded
fixtures replayed through injectable openers, and the LOCAL_ONLY tests
use a counting resolver to prove zero network calls happen.
"""
import json
import urllib.error
from pathlib import Path

import pytest

from hermes_legal.citations import (
    CeilingGuardedResolver,
    CourtListenerClient,
    GovInfoClient,
    OfflineResolver,
    ResolverRouter,
    VerificationResult,
    build_lookup_preview,
    govinfo_package_id,
    govinfo_section_root,
    guard_resolver,
    lookup_block_reason,
    parse_govinfo_package_summary,
    verify_all_gate,
    verify_citation,
)

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeResponse:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]


# --- govinfo statute resolver ---------------------------------------------

def _govinfo_client(calls):
    html = (FIXTURES / "govinfo_uscode_42_1983.html").read_text(encoding="utf-8")

    def opener(request, timeout=None):
        calls.append(request.full_url)
        if "/link/uscode/42/1983" in request.full_url:
            return _FakeResponse(html)
        if "/link/uscode/42/9999" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        raise urllib.error.URLError("unexpected URL in fixture opener")

    return GovInfoClient(opener=opener)


def test_govinfo_package_helpers():
    assert govinfo_package_id(42) == "USCODE-2023-title42"
    assert govinfo_section_root("1983") == "1983"
    assert govinfo_section_root("501(c)(3)") == "501"
    summary = _load("govinfo_package_title42.json")
    assert parse_govinfo_package_summary(summary, 42) is True
    assert parse_govinfo_package_summary(summary, 26) is False


def test_govinfo_known_statute_exists():
    calls = []
    result = _govinfo_client(calls).verify("42 U.S.C. § 1983")
    assert result.status == "exists"
    assert result.checked is True
    assert result.source == "govinfo"
    assert "USCODE-2023-title42" in result.detail
    assert calls and "/link/uscode/42/1983" in calls[0]


def test_govinfo_invented_statute_is_not_found():
    result = _govinfo_client([]).verify("42 U.S.C. § 9999")
    assert result.status == "not_found"
    assert result.checked is False


def test_govinfo_quote_verified_and_quote_not_verified():
    client = _govinfo_client([])
    present = client.verify("42 U.S.C. § 1983", quote="under color of any statute")
    assert present.status == "quote_verified"
    absent = client.verify("42 U.S.C. § 1983", quote="words that never appear")
    assert absent.status == "quote_not_verified"
    assert absent.blocks_gate is True


def test_govinfo_network_failure_is_unverified_not_not_found():
    def failing(request, timeout=None):
        raise urllib.error.URLError("offline in tests")

    result = GovInfoClient(opener=failing).verify("42 U.S.C. § 1983")
    assert result.status == "unverified"
    assert "not checked" in result.detail


def test_govinfo_does_not_claim_case_citations():
    result = _govinfo_client([]).verify("678 F. Supp. 3d 443")
    assert result.status == "unverified"
    assert "statute" in result.detail


def test_statute_passes_verify_all_gate_through_govinfo():
    gate = verify_all_gate("Under 42 U.S.C. § 1983, plaintiff sues.",
                           resolver=_govinfo_client([]))
    assert gate.allowed is True, gate.message
    assert gate.results[0].status == "exists"


def test_invented_statute_blocks_verify_all_gate_through_govinfo():
    gate = verify_all_gate("Under 42 U.S.C. § 9999, plaintiff sues.",
                           resolver=_govinfo_client([]))
    assert gate.allowed is False
    assert gate.blocked_citations == ("42 U.S.C. § 9999",)


# --- Resolver routing -------------------------------------------------------

class _KindResolver:
    def __init__(self, name, status="exists"):
        self.name = name
        self.status = status
        self.seen = []

    def verify(self, citation, quote=None):
        self.seen.append(str(citation))
        return VerificationResult(
            citation=str(citation), status=self.status, source=self.name)


def test_router_sends_statutes_to_govinfo_and_cases_to_courtlistener():
    cases = _KindResolver("courtlistener")
    statutes = _KindResolver("govinfo")
    router = ResolverRouter(case_resolver=cases, statute_resolver=statutes)
    assert router.name == "courtlistener+govinfo"
    assert router.verify("42 U.S.C. § 1983").source == "govinfo"
    assert router.verify("678 F. Supp. 3d 443").source == "courtlistener"
    assert statutes.seen and cases.seen


def test_router_without_statute_resolver_names_the_gap():
    router = ResolverRouter(case_resolver=_KindResolver("courtlistener"))
    result = router.verify("42 U.S.C. § 1983")
    assert result.status == "unverified"
    assert "No statute resolver" in result.detail


# --- Opinion-text fetch for quote verification ------------------------------

def _opinion_client(calls):
    lookup = _load("courtlistener_lookup_opinion_ref.json")
    opinion = _load("courtlistener_opinion_text.json")

    def opener(request, timeout=None):
        calls.append(request.full_url)
        if request.full_url.endswith("/citation-lookup/"):
            return _FakeResponse(json.dumps(lookup))
        if "/opinions/910001/" in request.full_url:
            return _FakeResponse(json.dumps(opinion))
        raise urllib.error.URLError("unexpected URL in fixture opener")

    return CourtListenerClient(token="fixture-token", opener=opener)


def test_quote_verified_is_reachable_through_fetched_opinion_text():
    calls = []
    result = _opinion_client(calls).verify(
        "678 F. Supp. 3d 443", quote="imposed sanctions")
    assert result.status == "quote_verified"
    # Two fetches happened: the lookup, then the opinion itself.
    assert any("/opinions/910001/" in url for url in calls)


def test_quote_absent_from_fetched_opinion_text_is_quote_not_verified():
    result = _opinion_client([]).verify(
        "678 F. Supp. 3d 443", quote="words that never appear")
    assert result.status == "quote_not_verified"
    assert result.blocks_gate is True


def test_unconfirmed_quote_blocks_gate_even_with_opinion_fetch():
    gate = verify_all_gate(
        "Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023).",
        resolver=_opinion_client([]),
        quotes={"678 F. Supp. 3d 443": "words that never appear"})
    assert gate.allowed is False
    assert gate.results[0].status == "quote_not_verified"


def test_confirmed_quote_passes_gate_through_verify_citation():
    result = verify_citation(
        "Mata v. Avianca, Inc., 678 F. Supp. 3d 443",
        _opinion_client([]), quote="imposed sanctions")
    assert result.status == "quote_verified"
    assert result.checked is True


def test_opinion_fetch_failure_keeps_exists_but_gate_blocks_quote():
    lookup = _load("courtlistener_lookup_opinion_ref.json")

    def opener(request, timeout=None):
        if request.full_url.endswith("/citation-lookup/"):
            return _FakeResponse(json.dumps(lookup))
        raise urllib.error.URLError("opinion fetch offline")

    client = CourtListenerClient(token="t", opener=opener)
    direct = client.verify("678 F. Supp. 3d 443", quote="imposed sanctions")
    assert direct.status == "exists"
    assert "no opinion text could be fetched" in direct.detail
    gated = verify_citation("678 F. Supp. 3d 443", client, quote="imposed sanctions")
    assert gated.status == "quote_not_verified"


# --- LOCAL_ONLY lookup behavior ----------------------------------------------

class _CountingResolver:
    name = "counting"

    def __init__(self):
        self.calls = 0

    def verify(self, citation, quote=None):
        self.calls += 1
        return VerificationResult(
            citation=str(citation), status="exists", source=self.name)


@pytest.mark.parametrize("ceiling", ["LOCAL_ONLY", "local_only", "BOGUS", None, ""])
def test_local_only_and_unknown_ceilings_block_with_zero_calls(ceiling):
    inner = _CountingResolver()
    guarded = CeilingGuardedResolver(inner, ceiling)
    result = guarded.verify("678 F. Supp. 3d 443")
    assert inner.calls == 0
    assert result.status == "unverified"
    assert result.blocks_gate is True


def test_local_only_block_reason_names_attestation_path():
    reason = lookup_block_reason("LOCAL_ONLY")
    assert reason is not None
    assert "LOCAL_ONLY" in reason
    assert "attestation" in reason


@pytest.mark.parametrize("ceiling", ["ZERO_RETENTION", "STANDARD"])
def test_allowed_ceilings_pass_lookups_through(ceiling):
    inner = _CountingResolver()
    guarded = guard_resolver(inner, ceiling)
    result = guarded.verify("678 F. Supp. 3d 443")
    assert inner.calls == 1
    assert result.status == "exists"
    assert lookup_block_reason(ceiling) is None


def test_local_only_verify_all_makes_zero_network_calls():
    inner = _CountingResolver()
    gate = verify_all_gate(
        "See 678 F. Supp. 3d 443 and 42 U.S.C. § 1983.",
        resolver=guard_resolver(inner, "LOCAL_ONLY"))
    assert inner.calls == 0
    assert gate.allowed is False
    assert len(gate.blocked_citations) == 2


def test_lookup_preview_lists_pending_lookups_and_block_state():
    found = ["678 F. Supp. 3d 443", "42 U.S.C. § 1983"]
    blocked = build_lookup_preview(found, ceiling="LOCAL_ONLY", resolver_name="counting")
    assert blocked.blocked is True
    assert blocked.leaves_device is True
    payload = blocked.to_dict()
    assert payload["citations"] == found
    assert payload["would_send"] == []
    assert "LOCAL_ONLY" in payload["blocked_reason"]
    allowed = build_lookup_preview(found, ceiling="STANDARD", resolver_name="counting")
    assert allowed.blocked is False
    assert allowed.to_dict()["would_send"] == found
    assert "counting" in allowed.render()


def test_guarded_resolver_preview_performs_no_lookup():
    inner = _CountingResolver()
    preview = CeilingGuardedResolver(inner, "LOCAL_ONLY").preview(["347 U.S. 483"])
    assert inner.calls == 0
    assert preview.citations == ("347 U.S. 483",)


# --- Issue #3 acceptance, restated against the completed path -----------------

def test_issue3_known_good_verifies_and_invented_is_not_found():
    resolver = OfflineResolver.from_fixture(FIXTURES / "citation_records.json")
    assert resolver.verify("678 F. Supp. 3d 443").status == "exists"
    assert resolver.verify("999 F.3d 9999").status == "not_found"


def test_issue3_no_model_path_presents_unchecked_as_checked():
    # Extraction and formatting produce no status; a resolver-less
    # Verify-All blocks and names the citation.
    gate = verify_all_gate("Model text citing 678 F. Supp. 3d 443.")
    assert gate.allowed is False
    assert gate.blocked_citations == ("678 F. Supp. 3d 443",)
    assert all(not r.checked for r in gate.results)
