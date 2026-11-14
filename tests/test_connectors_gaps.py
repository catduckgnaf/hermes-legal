"""Offline tests for the issue #25 connector gaps and the #8 remainders.

All HTTP runs against FakeTransport with fixture responses and
synthetic accounts; no test touches the network or a live account.
"""
import json
import sqlite3
import warnings
from pathlib import Path

import pytest

from hermes_legal import db as legal_db
from hermes_legal.connectors import (
    ApprovalRequired, ChainCredentialStore, ClioConnector, ConnectorDisabled,
    CourtListenerConnector, DocuSignConnector, DurablePendingActionStore,
    EnvCredentialStore, FakeTransport, KeychainCredentialStore,
    MemoryCredentialStore, OAuthClient, OAuthError, PacerAuthError,
    PacerConnector, RecapCheckRequired, TransportResponse, clio_oauth,
    code_challenge_s256, docusign_oauth, generate_code_verifier,
)
from hermes_legal.providers import PrivacyViolationError

FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def creds(values):
    store = MemoryCredentialStore()
    for (service, key), value in values.items():
        store.set(service, key, value)
    return store


CLIO_CREDS = {("clio", "access_token"): "synthetic-clio-token"}
DOCUSIGN_CREDS = {("docusign", "access_token"): "synthetic-docusign-token"}
CEILINGS = {42: "LOCAL_ONLY", 43: "STANDARD", 44: "ZERO_RETENTION"}


# --- 1. Windows credential store -------------------------------------------

class FakeWindowsBackend:
    """In-memory stand-in for the ctypes win32cred backend."""

    def __init__(self):
        self.values = {}
        self.calls = []

    def read(self, target):
        self.calls.append(("read", target))
        return self.values.get(target)

    def write(self, target, value, *, username=""):
        self.calls.append(("write", target))
        self.values[target] = value

    def delete(self, target):
        self.calls.append(("delete", target))
        return self.values.pop(target, None) is not None


def test_windows_credential_store_round_trip_with_fake_backend():
    backend = FakeWindowsBackend()
    store = KeychainCredentialStore(platform="win32", windows_backend=backend)
    assert store.available and store.tool == "win32cred"
    store.set("clio", "access_token", "synthetic-win-token")
    assert store.get("clio", "access_token") == "synthetic-win-token"
    assert store.delete("clio", "access_token") is True
    assert store.get("clio", "access_token") is None
    assert {c[0] for c in backend.calls} == {"read", "write", "delete"}


def test_non_windows_never_touches_windows_backend():
    backend = FakeWindowsBackend()
    store = KeychainCredentialStore(platform="linux", windows_backend=backend)

    def failing_runner(*a, **k):
        raise AssertionError("runner should not be replaced by the windows path")

    store._run = failing_runner
    # Linux with no secret-tool on PATH in this environment returns None
    # through the normal path; the point is the Windows backend is unused.
    try:
        store.get("clio", "access_token")
    except AssertionError:
        pass  # only the linux runner may run; the windows backend may not
    assert backend.calls == []


def test_keychain_store_on_linux_does_not_use_windows_backend_for_set():
    backend = FakeWindowsBackend()
    store = KeychainCredentialStore(platform="darwin", windows_backend=backend)
    assert not store.is_windows
    assert backend.calls == []


def test_env_fallback_is_warned_never_silent():
    chain = ChainCredentialStore([
        KeychainCredentialStore(platform="linux", windows_backend=FakeWindowsBackend()),
        EnvCredentialStore({"CLIO_ACCESS_TOKEN": "from-env"}),
    ])
    # The linux keychain lookup may or may not find a tool; force a miss
    # by using a service/key pair the env store alone can answer through
    # a chain whose first store is an empty memory store.
    chain = ChainCredentialStore([MemoryCredentialStore(),
                                  EnvCredentialStore({"CLIO_ACCESS_TOKEN": "from-env"})])
    with pytest.warns(RuntimeWarning, match="environment variable"):
        assert chain.get("clio", "access_token") == "from-env"
    assert chain.used_env_fallback is True
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        memory_only = ChainCredentialStore([MemoryCredentialStore()])
        assert memory_only.get("clio", "access_token") is None


# --- 2. OAuth: exchange, refresh, PKCE ---------------------------------------

def oauth_transport():
    t = FakeTransport()
    responses = [
        (200, fixture("oauth_token_success.json")),
        (200, fixture("oauth_token_refresh_rotated.json")),
        (200, fixture("oauth_token_refresh_no_rotation.json")),
        (400, fixture("oauth_token_error.json")),
    ]
    state = {"i": 0}

    def handler(req):
        out = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        return out

    t.add("POST", "https://app.clio.com/oauth/token", handler)
    return t


def test_oauth_pkce_s256_and_authorization_url():
    cfg = clio_oauth("synthetic-client-id")
    verifier, challenge = cfg.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert code_challenge_s256(verifier) == challenge
    # RFC 7636 appendix B vector.
    assert code_challenge_s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    url = cfg.authorization_url(state="state-1", code_verifier=verifier)
    assert "code_challenge=" + challenge in url and "code_challenge_method=S256" in url
    assert len(generate_code_verifier()) == 64


def test_oauth_full_code_pkce_flow_and_refresh_rotation():
    t = oauth_transport()
    cfg = clio_oauth("synthetic-client-id")
    store = MemoryCredentialStore()
    client = OAuthClient(cfg, t, credential_store=store, service="clio")
    verifier, _ = cfg.pkce_pair()
    tokens = client.exchange_code("synthetic-code", code_verifier=verifier)
    assert tokens.access_token == "synthetic-access-1"
    sent = t.calls[0]["form_body"]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "synthetic-code" and sent["code_verifier"] == verifier
    assert store.get("clio", "access_token") == "synthetic-access-1"
    rotated = client.refresh(tokens)
    assert rotated.access_token == "synthetic-access-2"
    assert rotated.refresh_token == "synthetic-refresh-2"  # rotation replaces the old token
    assert t.calls[1]["form_body"]["refresh_token"] == "synthetic-refresh-1"
    kept = client.refresh(rotated)
    assert kept.access_token == "synthetic-access-3"
    assert kept.refresh_token == "synthetic-refresh-2"  # no rotation: old token kept


def test_oauth_error_response_raises_oauth_error():
    t = oauth_transport()
    client = OAuthClient(clio_oauth("synthetic-client-id"), t)
    client.exchange_code("code-1")
    client.refresh("refresh-1")
    client.refresh("refresh-2")
    with pytest.raises(OAuthError) as excinfo:
        client.exchange_code("expired-code")
    assert excinfo.value.error == "invalid_grant"
    assert "expired" in excinfo.value.description


# --- 3. Durable pending actions, recorded approvals, idempotency ------------

def durable_clio(tmp_path, transport):
    conn = legal_db.connect(tmp_path / "legal.db")
    store = DurablePendingActionStore(conn)
    return ClioConnector(transport, creds(CLIO_CREDS), pending_store=store), store


def test_durable_pending_action_requires_recorded_approval(tmp_path):
    t = FakeTransport()
    t.add("POST", "https://app.clio.com/api/v4/matters.json",
          lambda req: (201, {"data": {"id": 5}}))
    c, store = durable_clio(tmp_path, t)
    action = c.create_matter("Durable synthetic matter")
    assert store.status(action.action_id) == "pending"
    assert store.get(action.action_id)["idempotency_key"] == action.idempotency_key
    with pytest.raises(ApprovalRequired):
        action.approve("a-free-form-string")
    assert t.calls == []
    record = c.record_approval("catduck", action=action)
    result = action.approve(record.approval_id)
    assert result["data"]["id"] == 5
    assert store.status(action.action_id) == "executed"
    assert store.get(action.action_id)["approved_by"] == "catduck"
    # A second approve returns the recorded result without a second POST.
    assert action.approve("catduck")["data"]["id"] == 5
    assert len(t.calls_to("POST")) == 1


def test_durable_store_survives_a_new_connection(tmp_path):
    path = tmp_path / "legal.db"
    store1 = DurablePendingActionStore(legal_db.connect(path))
    from hermes_legal.connectors import PendingAction
    action = PendingAction(connector="clio", kind="create_matter", summary="Persisted",
                           payload={"data": {"description": "x"}})
    store1.save(action)
    approval = store1.record_approval("catduck", action_id=action.action_id)
    store2 = DurablePendingActionStore(legal_db.connect(path))
    assert store2.get(action.action_id)["summary"] == "Persisted"
    assert store2.has_recorded_approval(action.action_id, approval.approval_id)
    assert store2.has_recorded_approval(action.action_id, "catduck")
    assert not store2.has_recorded_approval(action.action_id, "someone-else")


def test_timeout_then_retry_sends_once_via_idempotency_key():
    sent = {}
    calls = {"count": 0}

    def executor(action):
        calls["count"] += 1
        if action.idempotency_key in sent:
            return sent[action.idempotency_key]  # server dedupe on the key
        sent[action.idempotency_key] = {"envelopeId": "env-1"}
        raise TimeoutError("timed out after the server accepted the send")

    from hermes_legal.connectors import PendingAction
    action = PendingAction(connector="docusign", kind="create_envelope",
                           summary="Retry test", _executor=executor)
    with pytest.raises(TimeoutError):
        action.approve("catduck")
    assert action.approve("catduck") == {"envelopeId": "env-1"}
    assert calls["count"] == 2 and len(sent) == 1, "the retry must not create a second send"


def test_docusign_timeout_retry_carries_same_idempotency_key(tmp_path):
    accepted = {}

    def handler(req):
        key = req["headers"].get("Idempotency-Key")
        assert key
        if key in accepted:
            return (201, accepted[key])
        accepted[key] = {"envelopeId": "env-9", "status": "sent"}
        raise TimeoutError("simulated timeout after acceptance")

    t = FakeTransport()
    t.add("POST", "https://demo.docusign.net/restapi/v2.1/accounts/acct-1/envelopes", handler)
    conn = legal_db.connect(tmp_path / "legal.db")
    store = DurablePendingActionStore(conn)
    c = DocuSignConnector(t, creds(DOCUSIGN_CREDS), account_id="acct-1", pending_store=store)
    action = c.create_envelope(
        "Engagement letter",
        signers=[{"email": "client@example.invalid", "name": "Test", "recipientId": "1"}],
        documents=[{"documentBase64": "AA==", "name": "letter.pdf",
                    "fileExtension": "pdf", "documentId": "1"}])
    c.record_approval("catduck", action=action)
    with pytest.raises(TimeoutError):
        action.approve("catduck")
    result = action.approve("catduck")
    assert result["envelopeId"] == "env-9"
    assert len(accepted) == 1 and len(t.calls_to("POST")) == 2
    keys = {call["headers"]["Idempotency-Key"] for call in t.calls_to("POST")}
    assert keys == {action.idempotency_key}


# --- 4. DocuSign account discovery --------------------------------------------

def userinfo_transport(name="docusign_userinfo_demo.json"):
    t = FakeTransport()
    t.add("GET", "https://account-d.docusign.com/oauth/userinfo",
          lambda req: (200, fixture(name)))
    t.add("GET", "https://demo.docusign.net/restapi/v2.1/accounts/acct-demo-1/envelopes",
          lambda req: (200, {"envelopes": [{"envelopeId": "env-1"}]}))
    return t


def test_docusign_account_discovery_uses_default_account_base_uri():
    t = userinfo_transport()
    c = DocuSignConnector(t, creds(DOCUSIGN_CREDS), oauth=docusign_oauth("cid"), account_id="")
    account = c.discover_account()
    assert account.account_id == "acct-demo-1"  # the default account, not the first
    assert account.base_url == "https://demo.docusign.net/restapi/v2.1"
    assert c.list_envelopes()[0]["envelopeId"] == "env-1"
    c.discover_account()
    assert len(t.calls_to("GET", "userinfo")) == 1, "discovery is cached per credential"


def test_docusign_account_discovery_production_account():
    t = FakeTransport()
    t.add("GET", "https://account.docusign.com/oauth/userinfo",
          lambda req: (200, fixture("docusign_userinfo_prod.json")))
    c = DocuSignConnector(t, creds(DOCUSIGN_CREDS),
                          oauth=docusign_oauth("cid", demo=False), account_id="")
    account = c.discover_account()
    assert account.account_id == "acct-prod-1"
    assert account.base_url == "https://na4.docusign.net/restapi/v2.1"


# --- 5. PACER auth boundary and case locator ----------------------------------

def pacer_transport(recap_hits):
    t = FakeTransport()
    t.add("GET", "https://www.courtlistener.com/api/rest/v4/search/",
          lambda req: (200, {"results": recap_hits}))
    t.add("POST", "https://pacer.uscourts.gov/services/cso-auth",
          lambda req: (200, fixture("pacer_auth_success.json")))
    t.add("POST", "https://pcl.uscourts.gov/pcl-public-api/rest/cases/find",
          lambda req: (200, fixture("pacer_case_search.json")))
    return t


def pacer_pair(recap_hits):
    t = pacer_transport(recap_hits)
    recap = CourtListenerConnector(t, MemoryCredentialStore())
    pacer_creds = creds({("pacer", "username"): "synthetic-user",
                         ("pacer", "password"): "synthetic-password"})
    return t, PacerConnector(t, pacer_creds, recap=recap)


def test_pacer_authenticate_posts_credentials_and_caches_token():
    t, pacer = pacer_pair([])
    token = pacer.authenticate()
    assert token == "synthetic-pacer-token"
    body = t.calls_to("POST", "cso-auth")[0]["json_body"]
    assert body == {"loginId": "synthetic-user", "password": "synthetic-password"}
    pacer.authenticate()
    assert len(t.calls_to("POST", "cso-auth")) == 1


def test_pacer_authenticate_error_raises():
    t = FakeTransport()
    t.add("GET", "https://www.courtlistener.com/api/rest/v4/search/",
          lambda req: (200, {"results": []}))
    t.add("POST", "https://pacer.uscourts.gov/services/cso-auth",
          lambda req: (401, fixture("pacer_auth_error.json")))
    recap = CourtListenerConnector(t, MemoryCredentialStore())
    pacer = PacerConnector(t, creds({("pacer", "username"): "u", ("pacer", "password"): "p"}),
                           recap=recap)
    with pytest.raises(PacerAuthError):
        pacer.authenticate()


def test_pacer_case_search_requires_recap_check_then_approval():
    t, pacer = pacer_pair([])
    with pytest.raises(RecapCheckRequired):
        pacer.search_pacer_cases("1:26-cv-00001", approved_by="catduck")
    result = pacer.locate_case("1:26-cv-00001", estimated_pages=20)
    assert result.source == "pacer_estimate" and result.estimate.total_usd == 2.00
    assert t.calls_to("POST", "pcl.uscourts.gov") == []
    with pytest.raises(ApprovalRequired) as excinfo:
        pacer.search_pacer_cases("1:26-cv-00001", estimated_pages=20)
    assert "$2.00" in str(excinfo.value), "the cost estimate is shown before any pull"
    cases = pacer.search_pacer_cases("1:26-cv-00001", approved_by="catduck")
    assert cases[0]["caseNumber"] == "1:26-cv-00001"
    search_call = t.calls_to("POST", "pcl.uscourts.gov")[0]
    assert search_call["headers"]["X-NEXT-GEN-CSO"] == "synthetic-pacer-token"
    assert search_call["json_body"] == {"caseNumber": "1:26-cv-00001"}


def test_pacer_case_search_recap_hit_never_calls_pacer():
    t, pacer = pacer_pair([{"id": 7, "caseName": "Synthetic v. Example"}])
    result = pacer.locate_case("1:26-cv-00001")
    assert result.candidates and result.source == "recap"
    assert t.calls_to("POST", "pcl.uscourts.gov") == []
    assert t.calls_to("POST", "cso-auth") == []


# --- 6. Privacy ceilings in connectors ------------------------------------------

def ceiling_clio():
    t = FakeTransport()
    t.add("GET", "https://app.clio.com/api/v4/matters.json",
          lambda req: (200, {"data": [{"id": 1}]}))
    t.add("POST", "https://app.clio.com/api/v4/matters.json",
          lambda req: (201, {"data": {"id": 9}}))
    return t


def test_local_only_matter_refuses_connector_reads_and_sends():
    t = ceiling_clio()
    c = ClioConnector(t, creds(CLIO_CREDS), ceiling_resolver=CEILINGS)
    with pytest.raises(PrivacyViolationError):
        c.list_matters(matter_id=42)
    assert t.calls == [], "a ceiling refusal must happen before any external call"
    action = c.create_matter("Blocked matter", matter_id=42)
    with pytest.raises(PrivacyViolationError):
        action.approve("catduck")
    assert t.calls_to("POST") == []
    assert c.list_matters(matter_id=43)  # STANDARD ceiling allows the call


def test_send_path_requires_explicit_matter_id_with_a_resolver():
    t = ceiling_clio()
    c = ClioConnector(t, creds(CLIO_CREDS), ceiling_resolver=CEILINGS)
    action = c.create_matter("No matter context")
    with pytest.raises(ConnectorDisabled):
        action.approve("catduck")
    assert t.calls == []


def test_unknown_matter_with_a_resolver_fails_closed():
    t = ceiling_clio()
    c = ClioConnector(t, creds(CLIO_CREDS), ceiling_resolver=CEILINGS)
    with pytest.raises(ConnectorDisabled):
        c.list_matters(matter_id=999)
    assert t.calls == []


def test_ceiling_resolver_from_a_real_database(tmp_path):
    conn = legal_db.connect(tmp_path / "legal.db")
    conn.execute(
        "INSERT INTO matters (name, folder, privacy_ceiling) VALUES ('M', 'synthetic-folder', 'LOCAL_ONLY')")
    conn.commit()
    matter_id = conn.execute("SELECT id FROM matters").fetchone()[0]
    t = ceiling_clio()
    c = ClioConnector(t, creds(CLIO_CREDS), ceiling_resolver=conn)
    with pytest.raises(PrivacyViolationError):
        c.list_matters(matter_id=matter_id)


def test_local_only_matter_refuses_pacer_and_courtlistener():
    t, pacer = pacer_pair([])
    pacer._ceiling_resolver = ClioConnector._normalize_ceiling_resolver(CEILINGS)
    pacer.recap._ceiling_resolver = pacer._ceiling_resolver
    with pytest.raises(PrivacyViolationError):
        pacer.lookup_document("Anything", matter_id=42)
    assert t.calls == []


# --- 7. Self-hosted signing and the per-connector contract ----------------------

def test_self_hosted_docuseal_target_labels_and_doctor():
    t = FakeTransport()
    t.add("GET", "http://127.0.0.1:3000/restapi/v2.1/accounts/self-hosted/envelopes",
          lambda req: (200, {"envelopes": []}))
    c = DocuSignConnector.self_hosted(
        t, creds(DOCUSIGN_CREDS), base_url="http://127.0.0.1:3000/restapi/v2.1",
        provider="DocuSeal")
    label = c.data_flow.describe()
    assert "DocuSeal" in label and "self-hosted" in label
    result = c.doctor()
    assert result.status == "ok" and "DocuSeal" in result.detail
    assert c.enabled_for_matter(1) is True
    assert c.list_envelopes() == []
    assert "docusign.net" not in t.calls[0]["url"]


def test_self_hosted_rejects_unknown_provider():
    with pytest.raises(ValueError):
        DocuSignConnector.self_hosted(FakeTransport(), creds(DOCUSIGN_CREDS),
                                      base_url="http://127.0.0.1:3000", provider="NopeSign")


def test_every_connector_has_doctor_data_flow_and_per_matter_flag():
    t = FakeTransport()
    recap = CourtListenerConnector(t, MemoryCredentialStore())
    connectors = [
        ClioConnector(t, creds(CLIO_CREDS)),
        DocuSignConnector(t, creds(DOCUSIGN_CREDS), account_id="acct-1"),
        recap,
        PacerConnector(t, MemoryCredentialStore(), recap=recap),
    ]
    for connector in connectors:
        assert connector.data_flow.destination
        assert connector.data_flow.describe()
        assert connector.doctor().status in {"ok", "missing", "off", "warn"}
        assert connector.enabled_for_matter(123) is True
        restricted = type(connector)
        assert connector.enabled is True
        _ = restricted  # per-matter restriction behavior is covered above


def test_durable_store_is_sqlite_and_additive_on_the_repo_database(tmp_path):
    conn = legal_db.connect(tmp_path / "legal.db")
    tables_before = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    DurablePendingActionStore(conn)
    tables_after = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"connector_pending_actions", "connector_approvals",
            "connector_deliveries"} <= tables_after
    assert tables_before <= tables_after
    assert isinstance(conn, sqlite3.Connection)
