"""Issue #22: the agent `legal_cite_check` path and the `cite-check
--preview` pre-send preview. All tests are offline: resolvers are counting
fakes and no network client is ever constructed against a live host.
"""
import json

import pytest

from hermes_legal import citations, cli, db, dispatch as runtime, matters, mcp_server
from hermes_legal.citations import CourtListenerClient, VerificationResult

BRIEF = ("See Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023); "
         "42 U.S.C. § 1983; Smith v. Jones, 2019 WL 4639462.")


class Counting:
    """A resolver that records what it was sent and finds everything."""

    name = "counting"

    def __init__(self):
        self.seen = []

    def verify(self, citation, quote=None):
        self.seen.append(str(getattr(citation, "normalized", citation)))
        return VerificationResult(citation=self.seen[-1], status="exists", source=self.name)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv(runtime.AGENT_TIER_ENV, raising=False)
    monkeypatch.delenv(mcp_server.UNATTENDED_ENV, raising=False)
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "brief.txt").write_text(BRIEF, encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Client Alvarez")
    return conn, mid


def _check(mid, resolver, tier="STANDARD"):
    ctx = runtime.Context.open("mcp", environ={runtime.AGENT_TIER_ENV: tier})
    ctx.resolver = resolver
    return runtime.dispatch(
        "legal_cite_check", {"matter_id": mid, "path": "brief.txt", "lookup": True}, ctx)["result"]


def _set_ceiling(conn, ceiling):
    conn.execute("UPDATE matters SET privacy_ceiling=?", (ceiling,))
    conn.commit()


# ------------------------------------------------- CourtListener scope

def test_courtlistener_never_sends_a_statute(monkeypatch):
    """A statute must not reach CourtListener: its 404 would be a
    not_found that no attestation can override."""
    client = CourtListenerClient(token="t")
    monkeypatch.setattr(client, "lookup", lambda *_: pytest.fail("statute was sent to CourtListener"))
    result = client.verify(citations.parse_citation("42 U.S.C. § 1983"))
    assert result.status == "unverified"
    assert "case citations only" in result.detail


def test_default_lookup_resolver_routes_statutes_to_govinfo(monkeypatch):
    for name in citations.CAP_TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)
    router = citations.default_lookup_resolver()
    assert isinstance(router.case_resolver, CourtListenerClient)
    assert isinstance(router.statute_resolver, citations.GovInfoClient)
    assert router.fallback_case_resolver is None


# ------------------------------------------------- agent legal_cite_check

def test_agent_lookup_on_local_only_sends_nothing_and_previews_the_block(world):
    conn, mid = world
    _set_ceiling(conn, "LOCAL_ONLY")
    resolver = Counting()
    result = _check(mid, resolver, tier="LOCAL_ONLY")
    assert resolver.seen == []
    preview = result["lookup_preview"]
    assert preview["blocked"] is True and preview["would_send"] == []
    assert "LOCAL_ONLY" in result["network"]
    assert result["gate"]["allowed"] is False


def test_agent_lookup_on_unknown_ceiling_fails_closed(world):
    conn, mid = world
    resolver = Counting()
    real = runtime._ceiling
    try:
        runtime._ceiling = lambda ctx, matter_id: "SOMETHING_NEW"
        ctx = runtime.Context.open("mcp", environ={runtime.AGENT_TIER_ENV: "STANDARD"})
        ctx.resolver = resolver
        result = runtime._cite_check(ctx, {"matter_id": mid, "path": "brief.txt", "lookup": True})
    finally:
        runtime._ceiling = real
    assert resolver.seen == []
    assert result["lookup_preview"]["blocked"] is True
    assert result["gate"]["allowed"] is False


def test_agent_lookup_previews_what_is_sent_and_never_sends_unrecognized(world):
    conn, mid = world
    _set_ceiling(conn, "STANDARD")
    resolver = Counting()
    result = _check(mid, resolver)
    assert "2019 WL 4639462" not in resolver.seen
    assert sorted(resolver.seen) == sorted(result["lookup_preview"]["would_send"])
    assert len(resolver.seen) == 2
    # The Westlaw citation has no resolver and no attestation: it blocks.
    assert result["gate"]["allowed"] is False
    assert result["gate"]["blocked"] == ["2019 WL 4639462"]


def test_agent_gate_accepts_recorded_attestation_for_westlaw_only(world):
    conn, mid = world
    _set_ceiling(conn, "STANDARD")
    citations.record_attestation(conn, "2019 WL 4639462", attested_by="A. Lawyer",
                                 source="Westlaw", matter_id=mid)
    result = _check(mid, Counting())
    by_cite = {r["citation"]: r for r in result["results"]}
    attested = by_cite["2019 WL 4639462"]
    assert attested["status"] == "attested" and attested["source"] == "human-attestation"
    assert "A. Lawyer" in attested["detail"] and "Westlaw" in attested["detail"]
    assert result["gate"]["allowed"] is True


def test_agent_attestation_never_lifts_a_not_found_or_a_case(world):
    conn, mid = world
    _set_ceiling(conn, "STANDARD")
    citations.record_attestation(conn, "42 U.S.C. § 1983", attested_by="A. Lawyer",
                                 source="govinfo", matter_id=mid)

    class NotFound(Counting):
        def verify(self, citation, quote=None):
            super().verify(citation, quote)
            return VerificationResult(citation=self.seen[-1], status="not_found", source=self.name)

    result = _check(mid, NotFound())
    statuses = {r["citation"]: r["status"] for r in result["results"]}
    assert statuses["42 U.S.C. § 1983"] == "not_found"
    assert "attested" not in statuses.values()
    assert result["gate"]["allowed"] is False


def test_agent_without_lookup_builds_no_preview_and_no_resolver(world, monkeypatch):
    conn, mid = world
    monkeypatch.setattr(citations, "default_lookup_resolver",
                        lambda: pytest.fail("a resolver was built without lookup"))
    ctx = runtime.Context.open("mcp", environ={runtime.AGENT_TIER_ENV: "LOCAL_ONLY"})
    result = runtime.dispatch("legal_cite_check", {"matter_id": mid, "path": "brief.txt"}, ctx)["result"]
    assert result["lookup_preview"] is None
    assert result["gate"]["allowed"] is False


# ------------------------------------------------- legal cite-check --preview

def _preview(capsys, *extra, resolver=None):
    assert cli.main(["cite-check", BRIEF, "--preview", *extra], cite_resolver=resolver) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_preview_runs_no_lookup_and_lists_what_would_be_sent(capsys):
    resolver = Counting()
    payload = _preview(capsys, "--privacy-ceiling", "STANDARD", resolver=resolver)
    assert resolver.seen == []
    assert payload["lookup_ran"] is False and payload["blocked"] is False
    assert payload["would_send"] == ["678 F. Supp. 3d 443", "42 U.S.C. § 1983"]
    assert payload["never_sent"] == ["2019 WL 4639462"]
    assert "status" not in payload and "verify_all_gate" not in payload


def test_cli_preview_local_only_would_send_nothing(capsys):
    resolver = Counting()
    payload = _preview(capsys, "--privacy-ceiling", "LOCAL_ONLY", resolver=resolver)
    assert resolver.seen == []
    assert payload["blocked"] is True and payload["would_send"] == []
    assert "LOCAL_ONLY" in payload["blocked_reason"]


def test_cli_preview_without_ceiling_says_the_run_is_unguarded(capsys):
    payload = _preview(capsys, resolver=Counting())
    assert payload["ceiling_enforced"] is False and payload["privacy_ceiling"] is None
    assert len(payload["would_send"]) == 2


def test_cli_preview_without_resolver_would_send_nothing(capsys, monkeypatch):
    monkeypatch.setattr(cli, "_default_cite_resolver", lambda: None)
    payload = _preview(capsys)
    assert payload["resolver"] is None and payload["would_send"] == []
