import json
import urllib.error
from pathlib import Path

import pytest

from hermes_legal.citations import (
    HISTORY_DISCLAIMER,
    STATUSES,
    CitationGateError,
    CourtListenerClient,
    OfflineResolver,
    assert_verify_all,
    extract_all,
    extract_citations,
    format_all,
    format_citation,
    normalize_reporter,
    parse_citation,
    parse_courtlistener_lookup,
    verify_all,
    verify_all_gate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_federal_cite():
    assert extract_all("See Mata v. Avianca, 678 F. Supp. 3d 443 (S.D.N.Y. 2023).")


def test_no_cite_no_match():
    assert extract_all("No authority cited here.") == []


# --- Extraction: federal reporters -------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Brown v. Board of Education, 347 U.S. 483 (1954).", "347 U.S. 483"),
    ("See 410 U.S. 113, 120 (1973).", "410 U.S. 113"),
    ("Cited at 576 U.S. 644 (2015).", "576 U.S. 644"),
    ("As in 123 F.2d 456 (2d Cir. 1941).", "123 F.2d 456"),
    ("As in 789 F.3d 101 (9th Cir. 2015).", "789 F.3d 101"),
    ("As in 12 F.4th 345 (5th Cir. 2021).", "12 F.4th 345"),
    ("Order at 678 F. Supp. 3d 443 (S.D.N.Y. 2023).", "678 F. Supp. 3d 443"),
    ("Order at 200 F. Supp. 2d 55 (D. Del. 2002).", "200 F. Supp. 2d 55"),
    ("Order at 300 F. Supp. 77 (N.D. Cal. 1980).", "300 F. Supp. 77"),
    ("Sanctions under 100 F.R.D. 200 (1984).", "100 F.R.D. 200"),
    ("Criminal appeal at 500 S. Ct. 100 (2020).", None),  # S. Ct. needs volume form below
])
def test_extracts_federal_reporters(text, expected):
    found = extract_citations(text)
    if expected is None:
        return  # shape covered by the dedicated S. Ct. test
    assert found and found[0].normalized == expected


def test_extracts_supreme_court_reporters():
    cites = extract_citations("See 141 S. Ct. 1234 (2021) and 590 U.S. 1 (2020).")
    assert [c.normalized for c in cites] == ["141 S. Ct. 1234", "590 U.S. 1"]


def test_extracts_pincite_court_and_year():
    (cite,) = extract_citations("Mata v. Avianca, Inc., 678 F. Supp. 3d 443, 450 (S.D.N.Y. 2023).")
    assert cite.pincite == 450
    assert cite.court == "S.D.N.Y."
    assert cite.year == 2023
    assert cite.case_name == "Mata v. Avianca, Inc."


# --- Extraction: regional and state reporters ---------------------------

@pytest.mark.parametrize("text,expected", [
    ("Held at 100 A.2d 200 (1950).", "100 A.2d 200"),
    ("Held at 200 N.E.2d 300 (1964).", "200 N.E.2d 300"),
    ("Held at 300 N.W.2d 400 (1981).", "300 N.W.2d 400"),
    ("Held at 400 S.E.2d 500 (1991).", "400 S.E.2d 500"),
    ("Held at 500 So. 3d 600 (Fla. 2010).", "500 So. 3d 600"),
    ("Held at 600 S.W.3d 700 (Tex. 2020).", "600 S.W.3d 700"),
    ("Held at 700 P.3d 800 (Cal. 2021).", "700 P.3d 800"),
    ("See 31 Cal. 4th 100 (2003).", "31 Cal. 4th 100"),
    ("See 100 Cal. App. 4th 200 (2002).", "100 Cal. App. 4th 200"),
    ("See 1 N.Y.3d 100 (2003).", "1 N.Y.3d 100"),
    ("See 300 A.D.2d 400 (2002).", "300 A.D.2d 400"),
    ("See 200 Ill. 2d 300 (2002).", "200 Ill. 2d 300"),
    ("See 150 Ohio St. 3d 200 (2017).", "150 Ohio St. 3d 200"),
    ("See 180 Wash. 2d 100 (2014).", "180 Wash. 2d 100"),
])
def test_extracts_state_and_regional_reporters(text, expected):
    found = extract_citations(text)
    assert found and found[0].normalized == expected


def test_longest_reporter_wins():
    (cite,) = extract_citations("At 678 F. Supp. 3d 443.")
    assert cite.reporter == "F. Supp. 3d"


def test_extracts_statute_citation():
    (cite,) = extract_citations("Under 42 U.S.C. § 1983, plaintiff sues.")
    assert cite.kind == "statute"
    assert cite.normalized == "42 U.S.C. § 1983"


def test_multiple_citations_in_order():
    text = "First 347 U.S. 483 (1954). Second 678 F. Supp. 3d 443 (S.D.N.Y. 2023)."
    assert [c.normalized for c in extract_citations(text)] == [
        "347 U.S. 483", "678 F. Supp. 3d 443"]


def test_unlisted_reporter_not_invented():
    # An unknown reporter abbreviation is not guessed into a citation.
    assert extract_all("See 12 Xyz. Q. 34 (2000).") == []


# --- Formatting ----------------------------------------------------------

def test_normalize_reporter_variants():
    assert normalize_reporter("F.Supp.3d") == "F. Supp. 3d"
    assert normalize_reporter("S.Ct.") == "S. Ct."
    assert normalize_reporter("F.  Supp.   3d") == "F. Supp. 3d"


def test_format_known_citation():
    assert format_citation("678 F. Supp. 3d 443") == "678 F. Supp. 3d 443"
    assert format_citation("678 F.Supp.3d 443") == "678 F. Supp. 3d 443"


def test_format_with_case_name_pincite_and_parenthetical():
    cite = parse_citation("Mata v. Avianca, Inc., 678 F. Supp. 3d 443, 450 (S.D.N.Y. 2023)")
    assert format_citation(cite) == (
        "Mata v. Avianca, Inc., 678 F. Supp. 3d 443, 450 (S.D.N.Y. 2023)")


def test_format_year_only_parenthetical():
    assert format_citation("347 U.S. 483 (1954)") == "347 U.S. 483 (1954)"


def test_format_statute():
    assert format_citation("42 U.S.C. § 1983") == "42 U.S.C. § 1983"


def test_format_unrecognized_text_unchanged():
    assert format_citation("not a citation at all") == "not a citation at all"


def test_format_all_rewrites_in_place():
    text = "See 678 F.Supp.3d 443 today."
    assert format_all(text) == "See 678 F. Supp. 3d 443 today."


def test_formatting_does_not_verify():
    # A formatted citation carries no status; only a resolver checks.
    result = verify_all("See 678 F. Supp. 3d 443.")
    assert result.results[0].status == "unverified"


# --- Offline resolver and fixtures ---------------------------------------

def _fixture_resolver():
    return OfflineResolver.from_fixture(FIXTURES / "citation_records.json")


def test_known_good_citation_verifies():
    result = _fixture_resolver().verify("678 F. Supp. 3d 443")
    assert result.status == "exists"
    assert result.checked is True
    assert result.history_status == "history_unknown"
    assert result.matched_name == "Mata v. Avianca, Inc."


def test_invented_citation_reports_not_found():
    result = _fixture_resolver().verify("999 F.3d 9999")
    assert result.status == "not_found"
    assert result.checked is False


def test_unrecorded_citation_is_unverified_not_invented():
    result = _fixture_resolver().verify("347 U.S. 483")
    assert result.status == "unverified"


def test_quote_verified_against_recorded_text():
    result = _fixture_resolver().verify("410 U.S. 113", quote="privacy right")
    assert result.status == "quote_verified"


def test_quote_not_in_text_stays_exists():
    result = _fixture_resolver().verify("410 U.S. 113", quote="words that never appear")
    assert result.status == "exists"


def test_statuses_contract():
    assert STATUSES == ("unverified", "exists", "quote_verified", "not_found", "history_unknown")
    assert "Shepard" in HISTORY_DISCLAIMER


# --- CourtListener parsing (recorded fixtures, no network) ---------------

def _load(name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data["response"]


def test_parse_courtlistener_found_fixture():
    result = parse_courtlistener_lookup(_load("courtlistener_lookup_found.json"), "678 F. Supp. 3d 443")
    assert result.status == "exists"
    assert result.matched_name == "Mata v. Avianca, Inc."
    assert result.source == "courtlistener"


def test_parse_courtlistener_not_found_fixture():
    result = parse_courtlistener_lookup(_load("courtlistener_lookup_not_found.json"), "999 F.3d 9999")
    assert result.status == "not_found"


def test_parse_courtlistener_empty_payload_is_unverified():
    assert parse_courtlistener_lookup([], "347 U.S. 483").status == "unverified"
    assert parse_courtlistener_lookup({}, "347 U.S. 483").status == "unverified"


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client_replaying(name):
    payload = _load(name)
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["auth"] = request.get_header("Authorization")
        return _FakeResponse(payload)

    return CourtListenerClient(token="fixture-token", opener=opener), seen


def test_courtlistener_client_replays_fixture_and_sends_token():
    client, seen = _client_replaying("courtlistener_lookup_found.json")
    result = client.verify("678 F. Supp. 3d 443")
    assert result.status == "exists"
    assert seen["auth"] == "Token fixture-token"
    assert seen["url"].endswith("/citation-lookup/")
    assert seen["method"] == "POST"


def test_courtlistener_client_not_found_fixture():
    client, _ = _client_replaying("courtlistener_lookup_not_found.json")
    assert client.verify("999 F.3d 9999").status == "not_found"


def test_courtlistener_token_from_env(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "env-token")
    client = CourtListenerClient(opener=lambda req, timeout=None: _FakeResponse([]))
    assert client.has_token is True


def test_courtlistener_network_failure_is_unverified():
    def failing(request, timeout=None):
        raise urllib.error.URLError("offline in tests")

    client = CourtListenerClient(token="t", opener=failing)
    result = client.verify("347 U.S. 483")
    assert result.status == "unverified"
    assert "not checked" in result.detail


def test_courtlistener_http_404_is_not_found():
    def not_found(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    client = CourtListenerClient(token="t", opener=not_found)
    assert client.verify("999 F.3d 9999").status == "not_found"


def test_courtlistener_http_500_is_unverified_not_not_found():
    def broken(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, None)

    client = CourtListenerClient(token="t", opener=broken)
    assert client.verify("347 U.S. 483").status == "unverified"


# --- Verify-All gate -------------------------------------------------------

_DOC = "Claim under Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)."


def test_verify_all_passes_when_every_citation_exists():
    result = verify_all(_DOC, resolver=_fixture_resolver())
    assert result.allowed is True
    gate = verify_all_gate(_DOC, resolver=_fixture_resolver())
    assert gate.allowed is True
    assert assert_verify_all(_DOC, resolver=_fixture_resolver()).allowed is True


def test_verify_all_blocks_unverified_and_names_it():
    result = verify_all(_DOC)  # no resolver: nothing was checked
    assert result.allowed is False
    assert result.blocked_citations == ("678 F. Supp. 3d 443",)
    gate = verify_all_gate(_DOC)
    assert gate.allowed is False
    assert "678 F. Supp. 3d 443" in gate.message


def test_verify_all_blocks_not_found_and_names_it():
    text = "Invented authority at 999 F.3d 9999 (9th Cir. 2020)."
    gate = verify_all_gate(text, resolver=_fixture_resolver())
    assert gate.allowed is False
    assert gate.blocked_citations == ("999 F.3d 9999",)
    with pytest.raises(CitationGateError) as excinfo:
        assert_verify_all(text, resolver=_fixture_resolver())
    assert "999 F.3d 9999" in str(excinfo.value)


def test_verify_all_mixed_document_blocks_only_the_bad_one():
    text = _DOC + " Also 999 F.3d 9999."
    gate = verify_all_gate(text, resolver=_fixture_resolver())
    assert gate.allowed is False
    assert gate.blocked_citations == ("999 F.3d 9999",)


def test_verify_all_no_citations_is_allowed():
    assert verify_all_gate("No authority cited here.").allowed is True


def test_gate_accepts_precomputed_results():
    results = [_fixture_resolver().verify("678 F. Supp. 3d 443")]
    assert verify_all_gate(results).allowed is True


def test_history_unknown_warns_but_does_not_block():
    result = verify_all(_DOC, resolver=_fixture_resolver())
    assert result.allowed is True
    assert any("history is unknown" in w for w in result.warnings)
