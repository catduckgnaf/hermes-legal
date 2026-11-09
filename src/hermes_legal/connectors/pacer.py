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
                 pacer_base_url: str = "https://pacer.uscourts.gov", **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.recap = recap
        self.pacer_base_url = pacer_base_url.rstrip("/")
        self._recap_candidates: tuple | None = None  # None until a RECAP check runs

    def required_credentials(self):
        return ("username", "password")

    def estimate_cost(self, pages: int) -> CostEstimate:
        if pages < 0:
            raise ValueError("pages cannot be negative")
        return CostEstimate(pages=pages)

    def lookup_document(self, query: str, *, estimated_pages: int = 10, matter_id=None) -> LookupResult:
        """RECAP first. A hit is a candidate only; a miss returns an estimate only."""
        self.require_enabled(matter_id)
        hits = self.recap.search_recap(query, matter_id=matter_id)
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
        self.require_enabled(matter_id)
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
        resp = self.transport.request("GET", f"{self.pacer_base_url}/documents/{document_id}",
                                      headers=headers)
        if not resp.ok:
            raise RuntimeError(f"pacer: fetch failed with HTTP {resp.status}")
        return resp.data
