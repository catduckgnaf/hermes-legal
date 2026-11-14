"""PACER with a RECAP-first rule, plus the CourtListener/RECAP client.

The rule is structural, not a warning label:

1. :meth:`PacerConnector.lookup_document` always searches the free
   RECAP archive (via CourtListener) first.
2. A RECAP search hit is a candidate, not the document: a search
   result may match without being the document sought, so a hit is
   reported in ``LookupResult.candidates`` and never as a confirmed
   document.
3. On a miss the caller gets a cost estimate only.
4. :meth:`PacerConnector.fetch_from_pacer` refuses to run unless a
   RECAP check through :meth:`lookup_document` on the same connector
   first returned at least one candidate, and it also requires
   ``approved_by`` naming a human, because PACER charges per page.

PACER fee facts used for the estimate: $0.10 per page, capped at
$3.00 per document, with the quarterly waiver threshold of $30. The
estimate states these assumptions so a human can judge it before
approving any pull.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import ApprovalRequired, BaseConnector, DataFlowLabel

COURTLISTENER_BASE = "https://www.courtlistener.com/api/rest/v4"
PACER_PER_PAGE_USD = 0.10
PACER_PER_DOCUMENT_CAP_USD = 3.00
PACER_QUARTERLY_WAIVER_USD = 30.00
# PACER authentication (CSO) and Case Locator (PCL) service shapes.
# Live verification against a real PACER account remains outstanding:
# no live PACER credentials exist for this project, so every call here
# runs through the injectable transport and stops at that boundary.
PACER_AUTH_URL = "https://pacer.uscourts.gov/services/cso-auth"
PACER_CASE_LOCATOR_BASE = "https://pcl.uscourts.gov/pcl-public-api/rest"


class PacerAuthError(RuntimeError):
    """Raised when the PACER authentication service rejects a login."""


@dataclass(frozen=True)
class CostEstimate:
    pages: int
    per_page_usd: float = PACER_PER_PAGE_USD
    cap_usd: float = PACER_PER_DOCUMENT_CAP_USD

    @property
    def total_usd(self) -> float:
        return round(min(self.pages * self.per_page_usd, self.cap_usd), 2)

    def describe(self) -> str:
        return (f"Estimated PACER cost: ${self.total_usd:.2f} "
                f"({self.pages} page(s) at ${self.per_page_usd:.2f}/page, "
                f"capped at ${self.cap_usd:.2f} per document; "
                f"fees at or under ${PACER_QUARTERLY_WAIVER_USD:.2f} per quarter are waived).")


class RecapCheckRequired(RuntimeError):
    """Raised when a PACER fetch is attempted without a prior RECAP
    check, through ``lookup_document``, that returned a candidate."""


@dataclass(frozen=True)
class LookupResult:
    source: str  # "recap" or "pacer_estimate"
    found: bool  # True only for a confirmed document; a search hit never sets it
    documents: tuple = ()  # Confirmed documents only; search hits go in candidates
    candidates: tuple = ()  # RECAP search hits: possible matches, not confirmed documents
    estimate: CostEstimate | None = None
    note: str = ""


class CourtListenerConnector(BaseConnector):
    """Free Law Project CourtListener / RECAP archive search."""

    name = "courtlistener"
    data_flow = DataFlowLabel(
        destination="CourtListener / RECAP (courtlistener.com, Free Law Project)",
        data_sent="docket and document search terms",
        data_received="public docket and RECAP document records",
    )

    def __init__(self, transport, credentials=None, *, base_url: str = COURTLISTENER_BASE, **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.base_url = base_url.rstrip("/")

    def required_credentials(self):
        return ()  # Search works without a token; a token only raises rate limits.

    def doctor(self):
        if not self.enabled:
            from .base import DoctorResult
            return DoctorResult(self.name, "off", "disabled by setting; off never fails the run")
        from .base import DoctorResult
        return DoctorResult(self.name, "ok", self.data_flow.describe())

    def search_recap(self, query: str, matter_id=None):
        self.require_enabled(matter_id)
        headers = {"Accept": "application/json"}
        token = self.credential("api_token")
        if token:
            headers["Authorization"] = f"Token {token}"
        resp = self.transport.request("GET", f"{self.base_url}/search/",
                                      headers=headers, params={"q": query, "type": "r"})
        if not resp.ok:
            raise RuntimeError(f"courtlistener: search failed with HTTP {resp.status}")
        data = resp.data or {}
        return data.get("results", []) if isinstance(data, dict) else list(data)


class PacerConnector(BaseConnector):
    """PACER access gated behind a RECAP check and a cost estimate."""

    name = "pacer"
    data_flow = DataFlowLabel(
        destination="PACER (pacer.uscourts.gov) — only after a RECAP miss and human approval",
        data_sent="case and document identifiers for an approved pull",
        data_received="filed documents billed per page",
    )

    def __init__(self, transport, credentials=None, *, recap: CourtListenerConnector,
                 pacer_base_url: str = "https://pacer.uscourts.gov",
                 auth_url: str = PACER_AUTH_URL,
                 case_locator_base_url: str = PACER_CASE_LOCATOR_BASE, **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.recap = recap
        self.pacer_base_url = pacer_base_url.rstrip("/")
        self.auth_url = auth_url
        self.case_locator_base_url = case_locator_base_url.rstrip("/")
        self._recap_candidates: tuple | None = None  # None until a RECAP check runs
        self._recap_checked = False
        self._auth_token: str | None = None  # in memory only; never written to disk

    def required_credentials(self):
        return ("username", "password")

    # -- authentication (live boundary: a real PACER account) -----------------
    def authenticate(self, matter_id=None) -> str:
        """Request a PACER auth token from the CSO authentication service.

        Sends the configured username and password once, keeps only
        the returned token in memory, and returns it. This is the
        live-auth boundary: with no live PACER credentials the method
        is exercised only against fixture transports in tests.
        """
        self.require_enabled(matter_id)
        if self._auth_token:
            return self._auth_token
        username = self.require_credential("username")
        password = self.require_credential("password")
        resp = self.transport.request(
            "POST", self.auth_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json_body={"loginId": username, "password": password})
        data = resp.data if isinstance(resp.data, dict) else {}
        token = data.get("nextGenCSO") or data.get("token") or data.get("auth_token")
        if not resp.ok or not token:
            detail = data.get("errorDescription") or data.get("error") or f"HTTP {resp.status}"
            raise PacerAuthError(f"pacer: authentication failed: {detail}")
        self._auth_token = str(token)
        return self._auth_token

    def _auth_headers(self, matter_id=None) -> dict:
        return {"Accept": "application/json",
                "X-NEXT-GEN-CSO": self.authenticate(matter_id=matter_id)}

    # -- case locator -----------------------------------------------------------
    def locate_case(self, case_number: str, *, estimated_pages: int = 10, matter_id=None) -> LookupResult:
        """RECAP first for a case number; a miss returns an estimate only.

        No PACER Case Locator call happens here. The returned estimate
        is what a human sees before approving
        :meth:`search_pacer_cases`.
        """
        self.require_enabled(matter_id)
        hits = self.recap.search_recap(case_number, matter_id=matter_id)
        self._recap_checked = True
        self._recap_candidates = tuple(hits)
        if hits:
            return LookupResult(source="recap", found=False, candidates=tuple(hits),
                                note="RECAP search returned candidate(s) that may match; "
                                     "a search hit is a candidate, not the confirmed case. "
                                     "PACER was not contacted and no fee applies.")
        estimate = self.estimate_cost(estimated_pages)
        return LookupResult(source="pacer_estimate", found=False, estimate=estimate,
                            note="Not in RECAP. " + estimate.describe() +
                                 " No PACER pull has been made; a human must approve one explicitly.")

    def search_pacer_cases(self, case_number: str, *, approved_by: str | None = None,
                           estimated_pages: int = 10, matter_id=None):
        """Paid Case Locator search by case number, behind the RECAP gate.

        Refused unless a RECAP check ran first (through
        :meth:`locate_case` or :meth:`lookup_document`) and a named
        human approved after seeing the cost estimate. Authenticates
        through :meth:`authenticate` when no token is cached.
        """
        self.require_enabled(matter_id, send=True)
        if not self._recap_checked:
            raise RecapCheckRequired(
                "PACER case search refused: no RECAP check has been run on this "
                "connector; run locate_case first so the free archive is checked "
                "before any paid path")
        if not approved_by or not str(approved_by).strip():
            raise ApprovalRequired(
                "PACER charges per page: pass approved_by naming the human who approved "
                + self.estimate_cost(estimated_pages).describe())
        resp = self.transport.request(
            "POST", f"{self.case_locator_base_url}/cases/find",
            headers=self._auth_headers(matter_id),
            json_body={"caseNumber": case_number})
        if not resp.ok:
            raise RuntimeError(f"pacer: case search failed with HTTP {resp.status}")
        data = resp.data or {}
        if isinstance(data, dict):
            return data.get("cases", data)
        return data

    def estimate_cost(self, pages: int) -> CostEstimate:
        if pages < 0:
            raise ValueError("pages cannot be negative")
        return CostEstimate(pages=pages)

    def lookup_document(self, query: str, *, estimated_pages: int = 10, matter_id=None) -> LookupResult:
        """RECAP first. A hit is a candidate only; a miss returns an estimate only."""
        self.require_enabled(matter_id)
        hits = self.recap.search_recap(query, matter_id=matter_id)
        self._recap_checked = True
        self._recap_candidates = tuple(hits)
        if hits:
            return LookupResult(source="recap", found=False, candidates=tuple(hits),
                                note="RECAP search returned candidate(s) that may match; "
                                     "a search hit is a candidate, not the confirmed document. "
                                     "PACER was not contacted and no fee applies.")
        estimate = self.estimate_cost(estimated_pages)
        return LookupResult(source="pacer_estimate", found=False, estimate=estimate,
                            note="Not in RECAP. " + estimate.describe() +
                                 " No PACER pull has been made; a human must approve one explicitly.")

    def fetch_from_pacer(self, document_id: str, *, estimated_pages: int = 10,
                         approved_by: str | None = None, matter_id=None):
        """Paid pull. Refused without a prior RECAP candidate and approval."""
        self.require_enabled(matter_id, send=True)
        if not self._recap_candidates:
            if self._recap_candidates is None:
                detail = "no RECAP check has been run on this connector"
            else:
                detail = "the RECAP check found no candidate"
            raise RecapCheckRequired(
                f"PACER fetch refused: {detail}; run lookup_document first and "
                "only fetch when RECAP returns a candidate")
        if not approved_by or not str(approved_by).strip():
            raise ApprovalRequired(
                "PACER charges per page: pass approved_by naming the human who approved "
                + self.estimate_cost(estimated_pages).describe())
        headers = {"Accept": "application/json"}
        if self._auth_token:
            headers["X-NEXT-GEN-CSO"] = self._auth_token
        resp = self.transport.request("GET", f"{self.pacer_base_url}/documents/{document_id}",
                                      headers=headers)
        if not resp.ok:
            raise RuntimeError(f"pacer: fetch failed with HTTP {resp.status}")
        return resp.data
