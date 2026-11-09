"""Offline connector tests. All HTTP runs against FakeTransport with
synthetic sandbox accounts; no test touches the network."""
import pytest

from hermes_legal.connectors import (
    ApprovalRequired, ClioConnector, ConnectorDisabled, CostEstimate,
    CourtListenerConnector, DocuSignConnector, EnvCredentialStore, FakeTransport,
    MemoryCredentialStore, PacerConnector, RecapCheckRequired, TokenSet,
    clio_oauth, docusign_oauth,
)


def creds(values):
    store = MemoryCredentialStore()
    for (service, key), value in values.items():
        store.set(service, key, value)
    return store


CLIO_CREDS = {("clio", "access_token"): "synthetic-clio-token"}
DOCUSIGN_CREDS = {("docusign", "access_token"): "synthetic-docusign-token"}


def clio_fake():
    t = FakeTransport()
    t.add("GET", "https://app.clio.com/api/v4/matters.json",
          lambda req: (200, {"data": [{"id": 1, "description": "Synthetic matter"}]}))
    t.add("GET", "https://app.clio.com/api/v4/matters/",
          lambda req: (200, {"data": {"id": 7, "description": "One matter"}}))
    t.add("GET", "https://app.clio.com/api/v4/contacts.json",
          lambda req: (200, {"data": [{"id": 2, "first_name": "Test"}]}))
    t.add("GET", "https://app.clio.com/api/v4/calendar_entries.json",
          lambda req: (200, {"data": [{"id": 3, "name": "Hearing"}]}))
    t.add("GET", "https://app.clio.com/api/v4/bills.json",
          lambda req: (200, {"data": [{"id": 4, "total": "100.00"}]}))
    t.add("POST", "https://app.clio.com/api/v4/matters.json",
          lambda req: (201, {"data": {"id": 99, "description": req["json_body"]["data"]["description"]}}))
    return t


# --- framework ----------------------------------------------------------

def test_fake_transport_refuses_unregistered_requests():
    with pytest.raises(AssertionError):
        FakeTransport().request("GET", "https://example.invalid/anything")


def test_env_credential_fallback():
    store = EnvCredentialStore({"CLIO_ACCESS_TOKEN": "from-env"})
    assert store.get("clio", "access_token") == "from-env"
    assert store.get("clio", "missing") is None


def test_doctor_reports_missing_credentials_and_off():
    c = ClioConnector(clio_fake(), MemoryCredentialStore())
    result = c.doctor()
    assert result.status == "missing" and "access_token" in result.detail
    off = ClioConnector(clio_fake(), creds(CLIO_CREDS), enabled=False)
    assert off.doctor().status == "off"


def test_doctor_ok_and_data_flow_label():
    c = ClioConnector(clio_fake(), creds(CLIO_CREDS))
    result = c.doctor()
    assert result.status == "ok"
    assert "Clio" in c.data_flow.describe()


def test_per_matter_enable_flag_blocks_other_matters():
    c = ClioConnector(clio_fake(), creds(CLIO_CREDS), enabled_matters={42})
    assert c.list_matters(matter_id=42)
    with pytest.raises(ConnectorDisabled):
        c.list_matters(matter_id=43)


def test_restricted_connector_fails_closed_without_matter_id():
    t = clio_fake()
    c = ClioConnector(t, creds(CLIO_CREDS), enabled_matters={42})
    assert c.enabled_for_matter(None) is False
    with pytest.raises(ConnectorDisabled):
        c.list_matters()
    assert t.calls == [], "a fail-closed check must happen before any request"
    with pytest.raises(ConnectorDisabled):
        c.list_contacts(matter_id=None)


def test_unrestricted_connector_still_allows_calls_without_matter_id():
    c = ClioConnector(clio_fake(), creds(CLIO_CREDS))
    assert c.enabled_for_matter(None) is True
    assert c.list_matters()


def test_oauth_config_shape_and_state_requirement():
    cfg = clio_oauth("synthetic-client-id")
    assert cfg.validate() == []
    url = cfg.authorization_url(state="state-123")
    assert "client_id=synthetic-client-id" in url and "state=state-123" in url
    with pytest.raises(ValueError):
        cfg.authorization_url(state="")
    ds = docusign_oauth("synthetic-client-id")
    assert ds.scopes == ("signature",) and "signature" in ds.authorization_url(state="s")


def test_token_set_requires_access_token():
    assert TokenSet.from_response({"access_token": "x"}).access_token == "x"
    with pytest.raises(ValueError):
        TokenSet.from_response({})


# --- Clio ---------------------------------------------------------------

def test_clio_reads_against_sandbox_fake():
    t = clio_fake()
    c = ClioConnector(t, creds(CLIO_CREDS))
    assert c.list_matters()[0]["description"] == "Synthetic matter"
    assert c.get_matter(7)["id"] == 7
    assert c.list_contacts()[0]["id"] == 2
    assert c.list_calendar_entries()[0]["name"] == "Hearing"
    assert c.list_bills()[0]["id"] == 4
    assert all(call["headers"]["Authorization"] == "Bearer synthetic-clio-token"
               for call in t.calls)


def test_clio_write_is_pending_until_approved():
    t = clio_fake()
    c = ClioConnector(t, creds(CLIO_CREDS))
    action = c.create_matter("New synthetic matter")
    assert t.calls_to("POST") == [], "creating a pending action must not POST"
    with pytest.raises(ApprovalRequired):
        action.approve("")
    result = action.approve("catduck")
    assert result["data"]["id"] == 99 and len(t.calls_to("POST")) == 1
    with pytest.raises(RuntimeError):
        action.approve("catduck")


def clio_paged_fake():
    t = FakeTransport()
    next_url = "https://app.clio.com/api/v4/matters.json?page_token=page-2"

    def matters(req):
        if "page_token=page-2" in req["url"]:
            return (200, {"data": [{"id": 3, "description": "Third matter"}],
                          "meta": {"paging": {}}})
        return (200, {"data": [{"id": 1, "description": "First matter"},
                               {"id": 2, "description": "Second matter"}],
                      "meta": {"paging": {"next": next_url}}})

    t.add("GET", "https://app.clio.com/api/v4/matters.json", matters)
    return t


def test_clio_list_follows_meta_paging_next_until_exhausted():
    t = clio_paged_fake()
    c = ClioConnector(t, creds(CLIO_CREDS))
    matters = c.list_matters()
    assert [m["id"] for m in matters] == [1, 2, 3]
    assert len(t.calls_to("GET", "matters.json")) == 2


def test_clio_list_stops_on_a_paging_cycle_instead_of_looping():
    t = FakeTransport()
    url = "https://app.clio.com/api/v4/contacts.json"
    t.add("GET", url,
          lambda req: (200, {"data": [{"id": 2}],
                             "meta": {"paging": {"next": url}}}))
    c = ClioConnector(t, creds(CLIO_CREDS))
    with pytest.raises(RuntimeError):
        c.list_contacts()


# --- DocuSign -------------------------------------------------------------

def docusign_fake():
    t = FakeTransport()
    t.add("GET", "https://demo.docusign.net/restapi/v2.1/accounts/acct-1/envelopes/env-9",
          lambda req: (200, {"status": "completed"}))
    t.add("GET", "https://demo.docusign.net/restapi/v2.1/accounts/acct-1/envelopes",
          lambda req: (200, {"envelopes": [{"envelopeId": "env-9", "status": "completed"}]}))
    t.add("POST", "https://demo.docusign.net/restapi/v2.1/accounts/acct-1/envelopes",
          lambda req: (201, {"envelopeId": "env-new", "status": req["json_body"]["status"]}))
    return t


def test_docusign_envelope_creation_sends_nothing_until_approved():
    t = docusign_fake()
    c = DocuSignConnector(t, creds(DOCUSIGN_CREDS), account_id="acct-1")
    action = c.create_envelope(
        "Engagement letter",
        signers=[{"email": "client@example.invalid", "name": "Test Client", "recipientId": "1"}],
        documents=[{"documentBase64": "AA==", "name": "letter.pdf",
                    "fileExtension": "pdf", "documentId": "1"}])
    assert t.calls == [], "envelope creation as a pending action must make no network call"
    assert action.payload["status"] == "sent"
    result = action.approve("catduck")
    assert result["envelopeId"] == "env-new" and len(t.calls_to("POST")) == 1


def test_docusign_reads_and_validation():
    t = docusign_fake()
    c = DocuSignConnector(t, creds(DOCUSIGN_CREDS), account_id="acct-1")
    assert c.get_envelope_status("env-9") == "completed"
    assert c.list_envelopes()[0]["envelopeId"] == "env-9"
    with pytest.raises(ValueError):
        c.create_envelope("x", signers=[], documents=[{"documentId": "1"}])


# --- PACER / RECAP --------------------------------------------------------

def recap_fake(hits):
    t = FakeTransport()
    t.add("GET", "https://www.courtlistener.com/api/rest/v4/search/",
          lambda req: (200, {"results": hits}))
    t.add("GET", "https://pacer.uscourts.gov/documents/",
          lambda req: (200, {"document_id": "doc-1", "pages": 12}))
    return t


def pacer_pair(hits):
    t = recap_fake(hits)
    recap = CourtListenerConnector(t, MemoryCredentialStore())
    pacer = PacerConnector(t, MemoryCredentialStore(), recap=recap)
    return t, pacer


def test_recap_hit_never_contacts_pacer():
    t, pacer = pacer_pair([{"id": 5, "caseName": "Synthetic v. Example"}])
    result = pacer.lookup_document("Synthetic v. Example")
    assert result.source == "recap" and result.estimate is None
    assert t.calls_to("GET", "pacer.uscourts.gov") == []


def test_recap_hit_is_a_candidate_not_the_document():
    t, pacer = pacer_pair([{"id": 5, "caseName": "Synthetic v. Example"}])
    result = pacer.lookup_document("Synthetic v. Example")
    assert result.candidates == ({"id": 5, "caseName": "Synthetic v. Example"},)
    assert result.documents == () and not result.found
    assert "candidate" in result.note


def test_fetch_from_pacer_refused_without_any_recap_check():
    t, pacer = pacer_pair([{"id": 5, "caseName": "Synthetic v. Example"}])
    with pytest.raises(RecapCheckRequired):
        pacer.fetch_from_pacer("doc-1", estimated_pages=12, approved_by="catduck")
    assert t.calls_to("GET", "pacer.uscourts.gov") == []


def test_recap_miss_returns_estimate_only_and_fetch_stays_refused():
    t, pacer = pacer_pair([])
    result = pacer.lookup_document("Missing v. Case", estimated_pages=50)
    assert result.source == "pacer_estimate" and not result.found
    assert result.candidates == () and result.documents == ()
    assert result.estimate.total_usd == 3.00  # 50 pages hit the per-document cap
    assert t.calls_to("GET", "pacer.uscourts.gov") == []
    with pytest.raises(RecapCheckRequired):
        pacer.fetch_from_pacer("doc-1", estimated_pages=12, approved_by="catduck")
    assert t.calls_to("GET", "pacer.uscourts.gov") == []


def test_fetch_from_pacer_after_recap_candidate_still_needs_approval():
    t, pacer = pacer_pair([{"id": 5, "caseName": "Synthetic v. Example"}])
    pacer.lookup_document("Synthetic v. Example")
    with pytest.raises(ApprovalRequired):
        pacer.fetch_from_pacer("doc-1", estimated_pages=12)
    assert t.calls_to("GET", "pacer.uscourts.gov") == []
    data = pacer.fetch_from_pacer("doc-1", estimated_pages=12, approved_by="catduck")
    assert data["document_id"] == "doc-1"


def test_pacer_cost_estimate_math():
    assert CostEstimate(pages=10).total_usd == 1.00
    assert CostEstimate(pages=100).total_usd == 3.00
    assert CostEstimate(pages=0).total_usd == 0.00
    assert "$1.00" in CostEstimate(pages=10).describe()
