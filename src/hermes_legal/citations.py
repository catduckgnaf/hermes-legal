"""Citation extraction, verification, Bluebook-style formatting, and the
Verify-All gate.

Design rule, from *Mata v. Avianca*: a model never asserts that a citation is
real. Extraction only finds citation-shaped text and marks it ``unverified``.
Only a resolver -- a real lookup against CourtListener, the Caselaw Access
Project, or govinfo -- can move a citation to ``exists`` or
``quote_verified``. No code path in this module presents extracted or
model-generated text as checked.

Statuses
--------
``unverified``
    Extracted (or supplied) but never looked up. This is the default and the
    only status extraction can produce.
``exists``
    A resolver found a matching authority.
``quote_verified``
    A resolver found the authority and the supplied quotation appears in
    the retrieved text.
``not_found``
    A resolver looked and found no matching authority.
``name_mismatch``
    A resolver found an authority at that reporter location, but it is a
    different case from the one the document names. This is the most common
    shape of an invented citation, so it blocks the gate.
``quote_not_verified``
    The authority was found, but a supplied quotation could not be confirmed
    in retrieved text. It blocks the gate.
``ambiguous``
    A resolver returned several candidate authorities for one citation, so
    no single match can be asserted. A human has to pick; until then it
    blocks the gate exactly like ``unverified``.
``attested``
    A citation class a resolver cannot cover (a statute, or a Westlaw,
    Lexis, or public-domain citation) was checked by a named human, and
    that check was recorded with who checked it, when, and from what
    source (see :class:`CitationAttestation`). Attestation never applies
    to an ordinary case citation, and never overrides a resolver's
    ``not_found``.
``history_unknown``
    The subsequent-history dimension of every result. Hermes Legal has no
    Shepard's or KeyCite, so history is always reported as unknown and the
    user interface must say so. It is a warning, never a verification: a
    citation whose history is unknown can still be ``exists``, and the
    Verify-All gate does not block on history alone (it would block every
    citation, because history is always unknown here).

Everything in this module is standard library only. Network access happens
only inside :class:`CourtListenerClient` (via ``urllib``), and only when a
caller explicitly verifies through it. Offline tests use recorded fixture
JSON; live calls belong in tests marked ``live`` only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

STATUSES = (
    "unverified", "exists", "quote_verified", "not_found", "history_unknown",
    "name_mismatch", "quote_not_verified", "ambiguous", "attested",
)

#: Statuses that mean the citation was actually checked: a resolver found
#: the authority, or a recorded human attestation covers it.
CHECKED_STATUSES = ("exists", "quote_verified", "attested")

#: Statuses that block the Verify-All gate. ``ambiguous`` blocks like
#: ``unverified``: several candidate matches are not a match.
BLOCKING_STATUSES = (
    "unverified", "not_found", "name_mismatch", "quote_not_verified", "ambiguous",
)

#: Shown wherever a verification result is presented.
HISTORY_DISCLAIMER = (
    "Subsequent history is unknown: Hermes Legal has no Shepard's or KeyCite, "
    "so a citation reported as exists or quote verified has not been checked "
    "for later reversal, overruling, or other subsequent history."
)

#: Environment variables consulted for a CourtListener token, in order.
COURTLISTENER_TOKEN_ENV = (
    "COURTLISTENER_API_TOKEN",
    "COURTLISTENER_TOKEN",
    "HERMES_LEGAL_COURTLISTENER_TOKEN",
)

COURTLISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4"

# ---------------------------------------------------------------------------
# Reporters
# ---------------------------------------------------------------------------

#: Canonical reporter abbreviations this module extracts and formats:
#: federal reporters, the regional reporters, and common state reporters.
#: The list is deliberately explicit -- an unlisted reporter is not extracted
#: rather than guessed at. ``U.S.C.`` is handled as a statute pattern, not a
#: case reporter.
REPORTERS: tuple[str, ...] = (
    # Federal
    "U.S.", "S. Ct.", "L. Ed. 2d", "L. Ed.",
    "F.4th", "F.3d", "F.2d", "F.",
    "F. Supp. 3d", "F. Supp. 2d", "F. Supp.",
    "F.R.D.", "F. App'x", "Fed. Appx.",
    "B.R.", "Fed. Cl.", "Ct. Cl.", "T.C.", "M.J.",
    "U.S.P.Q.2d", "U.S.P.Q.",
    # Regional
    "A.3d", "A.2d", "A.",
    "N.E.3d", "N.E.2d", "N.E.",
    "N.W.2d", "N.W.",
    "S.E.2d", "S.E.",
    "So. 3d", "So. 2d", "So.",
    "S.W.3d", "S.W.2d", "S.W.",
    "P.3d", "P.2d", "P.",
    # California and New York (the most subdivided state systems)
    "Cal. 5th", "Cal. 4th", "Cal. 3d", "Cal. 2d", "Cal.",
    "Cal. App. 5th", "Cal. App. 4th", "Cal. App. 3d", "Cal. App. 2d", "Cal. App.",
    "Cal. Rptr. 3d", "Cal. Rptr. 2d", "Cal. Rptr.",
    "N.Y.3d", "N.Y.2d", "N.Y.",
    "N.Y.S.3d", "N.Y.S.2d", "N.Y.S.",
    "A.D.3d", "A.D.2d", "A.D.",
    "Misc. 3d", "Misc. 2d", "Misc.",
    # Other common state reporters
    "Ill. 2d", "Ill.", "Ill. App. 3d", "Ill. App.",
    "Tex.", "Tex. App.",
    "Pa. Super.", "Pa. Commw.", "Pa.",
    "Ohio St. 3d", "Ohio St. 2d", "Ohio St.", "Ohio App. 3d", "Ohio App.",
    "Wash. 2d", "Wash.", "Wash. App. 2d", "Wash. App.",
    "Mass. App. Ct.", "Mass.",
    "Mich. App.", "Mich.",
    "Ga. App.", "Ga.",
    "N.C. App.", "N.C.",
    "Va. App.", "Va.",
    "Wis. 2d", "Wis.",
    "Ala.", "Ariz.", "Ark.", "Colo.", "Conn.", "Del.", "Fla.", "Idaho",
    "Ind.", "Iowa", "Kan.", "Ky.", "La.", "Md.", "Me.", "Minn.", "Miss.",
    "Mo.", "Mont.", "Neb.", "Nev.", "N.H.", "N.J. Super.", "N.J.", "N.M.",
    "N.D.", "Okla.", "Or.", "R.I.", "S.C.", "S.D.", "Tenn.", "Utah",
    "Vt.", "W. Va.", "Wyo.",
)


def _squash(text: str) -> str:
    """Collapse a reporter string for comparison: no spaces, lower case."""
    return re.sub(r"\s+", "", text).casefold()


_SQUASHED_TO_CANONICAL = {_squash(r): r for r in REPORTERS}


def normalize_reporter(raw: str) -> str:
    """Return the canonical abbreviation for a reporter string.

    Handles missing or extra spaces and periods spacing variants such as
    ``F.Supp.3d`` and ``S.Ct.``. Unknown reporters are returned with
    whitespace collapsed, unchanged in substance -- never guessed.
    """
    collapsed = re.sub(r"\s+", " ", raw.strip()).replace("\u2019", "'")
    return _SQUASHED_TO_CANONICAL.get(_squash(collapsed), collapsed)


def _reporter_pattern(reporter: str) -> str:
    pattern = re.escape(reporter)
    pattern = pattern.replace(r"\ ", r"\s+")
    # Allow the no-space variant (F.3d written F.3d is already tight; the
    # spaced forms such as "F. Supp. 3d" also appear as "F.Supp.3d").
    pattern = pattern.replace(r"\s+", r"\s*")
    # Word autocorrects F. App'x to a curly apostrophe.
    pattern = pattern.replace("'", "['\u2019]")
    return pattern


# Longest reporters first so "F. Supp. 3d" wins over "F." at the same spot.
_REPORTER_ALT = "|".join(
    _reporter_pattern(r) for r in sorted(REPORTERS, key=len, reverse=True)
)

# volume  reporter  page [, pincite | at pincite] [(court year)]
_CITE_RE = re.compile(
    r"\b(?P<volume>\d{1,4})\s+"
    r"(?P<reporter>" + _REPORTER_ALT + r")\s+"
    r"(?P<page>\d{1,5})"
    r"(?:\s*,\s*(?:at\s+)?(?P<pincite>\d{1,5}))?"
    r"(?:\s*\((?P<paren>[^)]{1,40})\))?"
)
# Public alias kept for compatibility with the original scaffold module.
CITE_RE = _CITE_RE

_STATUTE_RE = re.compile(
    r"\b(?P<title>\d{1,3})\s+U\.\s*S\.\s*C\.\s*"
    r"(?:§+\s*)?(?P<section>[\d]+(?:\.[\d]+)?(?:\([a-z0-9]+\))*)"
    r"(?:\s*\((?P<year>\d{4})\))?"
)

_CASE_NAME_RE = re.compile(
    r"(?P<name>[A-Z][A-Za-z0-9&.'\-, ]{1,80}?\s+v\.\s+[A-Z][A-Za-z0-9&.'\-, ]{1,60}?),\s*$"
)


# Citation-shaped text the parser cannot break into volume/reporter/page.
# These are never dropped: an authority the app cannot read must block the
# Verify-All gate, or an invented citation passes simply by being unusual.
_UNRECOGNIZED_RES = (
    # Westlaw and Lexis database citations.
    re.compile(r"\b\d{4}\s+(?:WL|U\.\s*S\.\s*(?:Dist\.|App\.)\s*LEXIS|[A-Z][A-Za-z.]*\s+LEXIS)\s+\d+\b"),
    # Public-domain citations, e.g. 2013 IL App (1st) 111279-U or 2019 OK 12.
    re.compile(r"\b(?:19|20)\d{2}\s+[A-Z]{2,4}(?:\s+App)?(?:\s+\(\d+[a-z]{2}\))?\s+\d+(?:-[A-Z])?\b"),
    # Volume, unknown reporter, page, then a year parenthetical.
    re.compile(r"\b\d{1,4}\s+(?:[A-Z][A-Za-z.'\u2019]*\s+){1,5}\d{1,5}(?:\s*,\s*\d{1,5})?\s+\([^)]{0,30}(?:19|20)\d{2}\)"),
    # A case name followed by anything that starts with a number.
    re.compile(r"\b[A-Z][\w.'\u2019&-]*\s+v\.\s+[A-Z][^,\n]{0,80},\s+\d[^.;\n]{0,40}"),
)


# ---------------------------------------------------------------------------
# Citation value type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Citation:
    """One extracted citation. Extraction sets no verification status."""

    raw: str
    volume: int | None = None
    reporter: str = ""
    page: int | None = None
    pincite: int | None = None
    court: str | None = None
    year: int | None = None
    case_name: str | None = None
    start: int = -1
    end: int = -1
    kind: str = "case"  # "case", "statute", or "unrecognized"
    section: str | None = None  # statute only: the U.S.C. section

    @property
    def normalized(self) -> str:
        """The canonical citation string, e.g. ``678 F. Supp. 3d 443``."""
        if self.kind == "unrecognized":
            return re.sub(r"\s+", " ", self.raw).strip()
        if self.kind == "statute":
            return f"{self.volume} U.S.C. § {self.section}"
        return f"{self.volume} {self.reporter} {self.page}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.normalized


def _parse_paren(paren: str | None) -> tuple[str | None, int | None]:
    if not paren:
        return None, None
    text = paren.strip().rstrip(")").strip()
    year_match = re.search(r"(\d{4})\s*$", text)
    year = int(year_match.group(1)) if year_match else None
    court = text[: year_match.start()].strip() if year_match else (text or None)
    return (court or None), year


_LEADING_SIGNAL_RE = re.compile(r"^(?:(?:See|Cf\.|But|Accord|Compare|Contra|also|see|e\.g\.|E\.g\.),?\s+)+")


def _case_name_before(text: str, start: int) -> str | None:
    window = text[max(0, start - 140):start]
    match = _CASE_NAME_RE.search(window)
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip()
    return _LEADING_SIGNAL_RE.sub("", name) or None


def extract_citations(text: str, *, include_unrecognized: bool = False) -> list[Citation]:
    """Extract citations from *text*, in document order.

    Finds federal reporters, regional reporters, common state reporters,
    and ``U.S.C.`` statute citations. Every returned citation is unverified
    by definition; use a resolver to check it. A reporter not listed in
    :data:`REPORTERS` is not extracted rather than guessed at.

    The Verify-All gate passes ``include_unrecognized=True`` to also receive
    citation-shaped text the parser cannot read, as ``kind="unrecognized"``,
    so that it blocks instead of treating that text as no citation at all.
    """
    found: list[Citation] = []
    for match in _CITE_RE.finditer(text):
        reporter = normalize_reporter(match.group("reporter"))
        court, year = _parse_paren(match.group("paren"))
        found.append(Citation(
            raw=match.group(0),
            volume=int(match.group("volume")),
            reporter=reporter,
            page=int(match.group("page")),
            pincite=int(match.group("pincite")) if match.group("pincite") else None,
            court=court,
            year=year,
            case_name=_case_name_before(text, match.start()),
            start=match.start(),
            end=match.end(),
            kind="case",
        ))
    for match in _STATUTE_RE.finditer(text):
        # A statute match inside a case citation span cannot happen (the
        # patterns are disjoint), so a plain merge by position is safe.
        found.append(Citation(
            raw=match.group(0),
            volume=int(match.group("title")),
            reporter="U.S.C.",
            page=None,
            year=int(match.group("year")) if match.group("year") else None,
            start=match.start(),
            end=match.end(),
            kind="statute",
            section=match.group("section"),
        ))
    spans = [(c.start, c.end) for c in found]
    for pattern in (_UNRECOGNIZED_RES if include_unrecognized else ()):
        for match in pattern.finditer(text):
            if any(match.start() < end and start < match.end() for start, end in spans):
                continue
            spans.append((match.start(), match.end()))
            found.append(Citation(raw=match.group(0), start=match.start(),
                                  end=match.end(), kind="unrecognized"))
    found.sort(key=lambda c: c.start)
    return found


def extract_all(text: str) -> list[str]:
    """Return the raw citation strings found in *text* (document order)."""
    return [c.raw for c in extract_citations(text)]


def extract(text: str) -> list[str]:
    """Backward-compatible alias for :func:`extract_all`."""
    return extract_all(text)


def parse_citation(text: str) -> Citation | None:
    """Parse a single citation string, or return ``None`` if unrecognized."""
    citations = extract_citations(text)
    return citations[0] if citations else None


# ---------------------------------------------------------------------------
# Bluebook-style formatting (deterministic, in code -- never by a model)
# ---------------------------------------------------------------------------

#: What the formatter does not do. Kept in code so docs and tests pin it.
FORMATTER_LIMITS: tuple[str, ...] = (
    "Covers case citations in the reporters listed in REPORTERS and "
    "U.S.C. statute citations only; books, articles, constitutions, "
    "rules, and unpublished or docket-number citations are returned "
    "unchanged rather than reformatted by guesswork.",
    "Normalizes volume, reporter abbreviation, spacing, first page, "
    "pincite, and the court-and-year parenthetical. It does not shorten "
    "case names, apply Bluebook Table T6 word abbreviations beyond the "
    "reporter table, or build short-form citations (Id., supra).",
    "A missing court or year is omitted, never invented. A year-only "
    "parenthetical is kept as a year-only parenthetical.",
    "Formatting is not verification: a formatted citation is still "
    "unverified until a resolver checks it.",
)


def format_citation(citation: Citation | str) -> str:
    """Format one citation deterministically, Bluebook style.

    Accepts a :class:`Citation` or a citation string (parsed first; an
    unrecognized string is returned unchanged). See :data:`FORMATTER_LIMITS`
    for exactly what this does and does not do.
    """
    cite = citation if isinstance(citation, Citation) else parse_citation(citation)
    if cite is None:
        return str(citation)
    if cite.kind == "unrecognized":
        return cite.raw
    if cite.kind == "statute":
        out = f"{cite.volume} U.S.C. § {cite.section}"
        if cite.year:
            out += f" ({cite.year})"
        return out
    parts: list[str] = []
    if cite.case_name:
        parts.append(f"{cite.case_name},")
    core = f"{cite.volume} {cite.reporter} {cite.page}"
    if cite.pincite:
        core += f", {cite.pincite}"
    parts.append(core)
    paren_bits = " ".join(b for b in (cite.court, str(cite.year) if cite.year else None) if b)
    if paren_bits:
        parts.append(f"({paren_bits})")
    return " ".join(parts)


#: Alias matching the legal_cite_format tool name.
format_bluebook = format_citation


def format_all(text: str) -> str:
    """Return *text* with every extracted citation replaced by its
    formatted form. Unrecognized text is left exactly as written."""
    citations = extract_citations(text)
    if not citations:
        return text
    out: list[str] = []
    cursor = 0
    for cite in citations:
        out.append(text[cursor:cite.start])
        # The case name sits before the matched span, so it stays where it
        # is in the text; formatting it again here would duplicate it.
        out.append(format_citation(replace(cite, case_name=None)))
        cursor = cite.end
    out.append(text[cursor:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Verification results and the resolver interface
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerificationResult:
    """The outcome of one resolver lookup.

    ``history_status`` is always ``history_unknown`` in this build; see
    :data:`HISTORY_DISCLAIMER`.
    """

    citation: str
    status: str = "unverified"
    source: str = ""
    detail: str = ""
    history_status: str = "history_unknown"
    matched_name: str | None = None
    source_url: str | None = None

    @property
    def checked(self) -> bool:
        """True only when a resolver found the authority, or a recorded
        human attestation covers a citation class a resolver cannot."""
        return self.status in CHECKED_STATUSES

    @property
    def blocks_gate(self) -> bool:
        return self.status in BLOCKING_STATUSES


class CitationResolver(Protocol):
    """A citation resolver: the only thing allowed to say a citation exists.

    Implementations must return ``unverified`` (never ``exists``) when a
    lookup could not be performed, for example on a network error.
    """

    name: str

    def verify(self, citation: Citation | str, quote: str | None = None) -> VerificationResult:
        ...


def _as_citation(citation: Citation | str) -> Citation | None:
    return citation if isinstance(citation, Citation) else parse_citation(str(citation))


def _display(citation: Citation | str) -> str:
    cite = _as_citation(citation)
    return cite.normalized if cite is not None else str(citation)


def _quote_in(quote: str, haystack: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()  # noqa: E731
    return bool(norm(quote)) and norm(quote) in norm(haystack)


class OfflineResolver:
    """A resolver backed by recorded data only. Performs no network access.

    ``records`` maps a normalized citation string (``678 F. Supp. 3d 443``)
    to a record dict with ``status`` (``exists`` or ``not_found``) and
    optional ``matched_name``, ``text`` (opinion text for quote checks),
    ``detail``, and ``source_url``. A citation with no record is
    ``unverified`` -- absence of a record is never reported as ``not_found``
    and never as ``exists``.
    """

    name = "offline-fixture"

    def __init__(self, records: Mapping[str, Mapping[str, Any]] | None = None,
                 source: str = "offline-fixture"):
        self._records = {str(k): dict(v) for k, v in (records or {}).items()}
        self.source = source

    @classmethod
    def from_fixture(cls, path: str | Path) -> "OfflineResolver":
        """Build from a recorded fixture JSON file.

        The file is either a mapping of citation to record, or a mapping
        with a ``records`` key holding that mapping.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        records = data.get("records", data) if isinstance(data, dict) else {}
        return cls(records, source=f"fixture:{Path(path).name}")

    def verify(self, citation: Citation | str, quote: str | None = None) -> VerificationResult:
        key = _display(citation)
        record = self._records.get(key)
        if record is None:
            return VerificationResult(
                citation=key, status="unverified", source=self.source,
                detail="No recorded lookup for this citation; it has not been checked.")
        status = str(record.get("status", "unverified"))
        if status not in STATUSES:
            status = "unverified"
        detail = str(record.get("detail", ""))
        if quote and status == "exists" and record.get("text"):
            if _quote_in(quote, str(record["text"])):
                status = "quote_verified"
                detail = detail or "Quotation found in the recorded opinion text."
            else:
                detail = detail or "Citation exists; the quotation was not found in the recorded text."
        return VerificationResult(
            citation=key, status=status, source=self.source, detail=detail,
            matched_name=record.get("matched_name"),
            source_url=record.get("source_url"))


#: FixtureResolver reads better at call sites that load recorded JSON.
FixtureResolver = OfflineResolver


# ---------------------------------------------------------------------------
# CourtListener client (stdlib urllib; token from the environment)
# ---------------------------------------------------------------------------

Opener = Callable[..., Any]


class CourtListenerClient:
    """Verify citations against the CourtListener citation-lookup API.

    The token is read from the environment (see
    :data:`COURTLISTENER_TOKEN_ENV`) unless passed explicitly. HTTP uses
    ``urllib`` only. ``opener`` is injectable so offline tests can replay
    recorded fixture JSON through the exact parsing path production uses;
    production callers leave it as ``urllib.request.urlopen``.

    A network or HTTP failure returns ``unverified`` with the error in
    ``detail`` -- a failed lookup is never reported as ``not_found`` and
    never as ``exists``.
    """

    name = "courtlistener"

    def __init__(self, token: str | None = None, *,
                 base_url: str = COURTLISTENER_BASE_URL,
                 opener: Opener | None = None, timeout: float = 15.0):
        if token is None:
            for env_name in COURTLISTENER_TOKEN_ENV:
                token = os.environ.get(env_name) or None
                if token:
                    break
        self._token = token
        self.base_url = base_url.rstrip("/")
        self._opener = opener or urllib.request.urlopen
        self.timeout = timeout

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    def _request_json(self, path: str, *, data: bytes | None = None) -> Any:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Token {self._token}"
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers,
            method="POST" if data is not None else "GET")
        with self._opener(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def lookup(self, citation: Citation | str) -> Any:
        """POST the citation text to citation-lookup; return parsed JSON."""
        text = citation.raw if isinstance(citation, Citation) else str(citation)
        data = urllib.parse.urlencode({"text": text}).encode("utf-8")
        return self._request_json("/citation-lookup/", data=data)

    def verify(self, citation: Citation | str, quote: str | None = None) -> VerificationResult:
        key = _display(citation)
        try:
            payload = self.lookup(citation)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return VerificationResult(
                    citation=key, status="not_found", source=self.name,
                    detail="CourtListener returned 404 for this citation.")
            return VerificationResult(
                citation=key, status="unverified", source=self.name,
                detail=f"CourtListener lookup failed (HTTP {exc.code}); the citation was not checked.")
        except Exception as exc:  # network, DNS, malformed JSON, timeout
            return VerificationResult(
                citation=key, status="unverified", source=self.name,
                detail=f"CourtListener lookup could not be completed ({type(exc).__name__}); "
                       "the citation was not checked.")
        return parse_courtlistener_lookup(payload, citation, quote=quote)


def parse_courtlistener_lookup(payload: Any, citation: Citation | str,
                               quote: str | None = None) -> VerificationResult:
    """Parse a CourtListener citation-lookup response into a result.

    Handles the documented response shape: a list of per-citation objects
    with ``status`` (200 when found, 404 when not) and ``clusters`` (the
    matched opinion clusters). Also accepts a bare mapping with
    ``clusters`` or ``results`` so recorded fixtures and the search API
    shape parse through the same path. An unrecognized or empty payload
    is ``unverified``, never ``exists``.
    """
    key = _display(citation)
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            items = payload["results"]
        else:
            items = [payload]
    clusters: list[dict[str, Any]] = []
    status_code: int | None = None
    error_message = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("status"), int):
            status_code = item["status"]
        error_message = error_message or str(item.get("error_message") or "")
        raw_clusters = item.get("clusters")
        if isinstance(raw_clusters, list):
            clusters.extend(c for c in raw_clusters if isinstance(c, dict))
    if len(clusters) > 1:
        # Several candidate authorities are not a match on the first one.
        # Name none of them: a human has to pick, and the gate fails closed.
        return VerificationResult(
            citation=key, status="ambiguous", source=CourtListenerClient.name,
            detail=(f"CourtListener returned {len(clusters)} opinion clusters for "
                    "this citation; a human must determine which one, if any, is "
                    "the cited authority. It is not treated as a match."))
    if clusters:
        first = clusters[0]
        matched_name = first.get("case_name") or first.get("case_name_full")
        source_url = first.get("absolute_url")
        if source_url and not str(source_url).startswith("http"):
            source_url = "https://www.courtlistener.com" + str(source_url)
        status = "exists"
        detail = "Matched a CourtListener opinion cluster."
        if quote:
            texts = " ".join(
                str(c.get("text") or c.get("snippet") or "") for c in clusters)
            if texts.strip() and _quote_in(quote, texts):
                status = "quote_verified"
                detail = "Matched a CourtListener opinion cluster and the quotation was found in the retrieved text."
            elif texts.strip():
                detail = "Matched a CourtListener opinion cluster; the quotation was not found in the retrieved text."
        return VerificationResult(
            citation=key, status=status, source=CourtListenerClient.name,
            detail=detail, matched_name=matched_name,
            source_url=str(source_url) if source_url else None)
    if status_code == 404:
        return VerificationResult(
            citation=key, status="not_found", source=CourtListenerClient.name,
            detail=error_message or "CourtListener found no matching citation.")
    return VerificationResult(
        citation=key, status="unverified", source=CourtListenerClient.name,
        detail=error_message or "CourtListener returned no match data; the citation was not checked.")


# ---------------------------------------------------------------------------
# Recorded human attestation (for citation classes no resolver covers)
# ---------------------------------------------------------------------------

#: Citation classes a resolver cannot cover, so a recorded human
#: attestation is the only check available: statutes (no statute resolver
#: yet), and Westlaw, Lexis, and public-domain citations.
ATTESTATION_CLASSES = ("statute", "westlaw", "lexis", "public_domain")


def _parse_any(citation: Citation | str) -> Citation | None:
    if isinstance(citation, Citation):
        return citation
    found = extract_citations(str(citation), include_unrecognized=True)
    return found[0] if found else None


def attestation_class(citation: Citation | str) -> str | None:
    """The attestation class of *citation*, or ``None`` when attestation
    is not accepted for it.

    Only statutes and the unrecognized database and public-domain shapes
    qualify. An ordinary case citation in a listed reporter returns
    ``None``: it must be checked by a resolver, never by attestation.
    """
    cite = _parse_any(citation)
    if cite is None:
        return None
    if cite.kind == "statute":
        return "statute"
    if cite.kind != "unrecognized":
        return None
    raw = cite.normalized
    if re.search(r"\bWL\b", raw):
        return "westlaw"
    if "LEXIS" in raw.upper():
        return "lexis"
    if _UNRECOGNIZED_RES[1].search(raw):
        return "public_domain"
    return None


@dataclass(frozen=True)
class CitationAttestation:
    """A recorded human check of a citation a resolver cannot cover:
    who checked it, when, and from what source."""

    citation: str
    attested_by: str
    source: str
    attested_at: str = ""
    matter_id: int | None = None

    @property
    def citation_class(self) -> str | None:
        return attestation_class(self.citation)


def record_attestation(conn, citation: Citation | str, *, attested_by: str,
                       source: str, matter_id: int | None = None,
                       attested_at: str | None = None) -> CitationAttestation:
    """Persist an attestation in the ``citation_attestations`` table of a
    database opened with :func:`hermes_legal.db.connect`.

    Raises :class:`ValueError` when who or what source is missing, or when
    the citation is not in a class attestation covers -- an ordinary case
    citation can never be attested into the gate.
    """
    who = (attested_by or "").strip()
    what_source = (source or "").strip()
    if not who:
        raise ValueError("an attestation must name who checked the citation")
    if not what_source:
        raise ValueError("an attestation must name the source the citation was checked in")
    cite = _parse_any(citation)
    if cite is None or attestation_class(cite) is None:
        raise ValueError(
            "attestation is only accepted for statutes and Westlaw, Lexis, or "
            f"public-domain citations; {citation!r} must be checked by a resolver")
    when = attested_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO citation_attestations"
        " (matter_id, citation, citation_class, attested_by, attested_at, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (matter_id, cite.normalized, attestation_class(cite), who, when, what_source))
    conn.commit()
    return CitationAttestation(
        citation=cite.normalized, attested_by=who, source=what_source,
        attested_at=when, matter_id=matter_id)


def load_attestations(conn, matter_id: int | None = None) -> dict[str, CitationAttestation]:
    """Load persisted attestations as a mapping of normalized citation to
    attestation, ready to pass to the Verify-All gate."""
    if matter_id is None:
        rows = conn.execute(
            "SELECT citation, attested_by, attested_at, source, matter_id"
            " FROM citation_attestations ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT citation, attested_by, attested_at, source, matter_id"
            " FROM citation_attestations WHERE matter_id = ? ORDER BY id",
            (matter_id,)).fetchall()
    return {
        row[0]: CitationAttestation(
            citation=row[0], attested_by=row[1], source=row[3],
            attested_at=row[2] or "", matter_id=row[4])
        for row in rows
    }


def _apply_attestation(citation: Citation | str, result: VerificationResult,
                       attestation: CitationAttestation | None) -> VerificationResult:
    """Let a recorded attestation stand in for a resolver, narrowly.

    Only an ``unverified`` result for a citation in an attestation class
    can become ``attested``. A resolver's ``not_found`` is never upgraded,
    for any citation, and neither is any other resolver verdict.
    """
    if attestation is None or result.status != "unverified":
        return result
    if attestation_class(citation) is None:
        return result
    return VerificationResult(
        citation=result.citation, status="attested", source="human-attestation",
        detail=(f"Attested by {attestation.attested_by} at "
                f"{attestation.attested_at or 'an unrecorded time'} from "
                f"{attestation.source}: a human checked this citation in a "
                "source a resolver cannot cover."))


# ---------------------------------------------------------------------------
# Verify one, verify all, and the gate
# ---------------------------------------------------------------------------

_NAME_STOPWORDS = frozenset({
    "a", "an", "and", "al", "co", "company", "corp", "corporation", "et", "for",
    "in", "inc", "incorporated", "limited", "llc", "llp", "ltd", "lp", "of", "on",
    "plc", "re", "the", "to", "v", "vs",
})


def _name_tokens(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.casefold())) - _NAME_STOPWORDS


def case_names_match(cited: str, matched: str) -> bool:
    """True when each party in *cited* shares a significant word with *matched*."""
    matched_tokens = _name_tokens(matched)
    sides = [_name_tokens(side) for side in re.split(r"\s+v\.?\s+", cited, maxsplit=1)]
    sides = [side for side in sides if side]
    return bool(sides) and all(side & matched_tokens for side in sides)


def _resolve(citation: Citation | str, resolver: CitationResolver,
             quote: str | None) -> VerificationResult:
    """Run the resolver, then apply the checks every resolver must pass.

    Finding something at a reporter location is not enough: it has to be the
    case the document names, and a supplied quotation has to be confirmed.
    An unrecognized citation is never sent to a resolver.
    """
    cite = _as_citation(citation)
    if cite is not None and cite.kind == "unrecognized":
        return VerificationResult(
            citation=cite.normalized, status="unverified", source="none",
            detail="This citation format cannot be checked automatically; "
                   "verify it by hand or remove it.")
    result = resolver.verify(citation, quote=quote)
    if result.status not in CHECKED_STATUSES:
        return result
    if cite is not None and cite.case_name and result.matched_name \
            and not case_names_match(cite.case_name, result.matched_name):
        return replace(result, status="name_mismatch", detail=(
            f"The document cites {cite.case_name!r}, but this reporter location "
            f"is {result.matched_name!r}."))
    if quote and result.status != "quote_verified":
        return replace(result, status="quote_not_verified", detail=(
            result.detail or "The quotation could not be confirmed in retrieved text."))
    return result


def verify_citation(citation: Citation | str, resolver: CitationResolver,
                    quote: str | None = None,
                    attestation: CitationAttestation | None = None) -> VerificationResult:
    """Verify one citation through *resolver*. Without a resolver there is
    no verification -- callers must pass one explicitly. A recorded
    *attestation* is applied under the narrow rules of
    :func:`_apply_attestation`."""
    return _apply_attestation(citation, _resolve(citation, resolver, quote), attestation)


@dataclass(frozen=True)
class VerifyAllResult:
    """All results for a document plus the gate verdict."""

    results: tuple[VerificationResult, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def blocked_citations(self) -> tuple[str, ...]:
        return tuple(r.citation for r in self.results if r.blocks_gate)

    @property
    def allowed(self) -> bool:
        """True when nothing blocks: every citation exists or is quote
        verified. A document with no citations is allowed."""
        return not self.blocked_citations

    @property
    def message(self) -> str:
        if self.allowed:
            if not self.results:
                return "Verify-All: no citations found; nothing blocks."
            return ("Verify-All: every citation was checked and found. "
                    + HISTORY_DISCLAIMER)
        names = ", ".join(self.blocked_citations)
        return (f"Verify-All blocked: citation(s) not verified (unverified, not found, or ambiguous): {names}. "
                "Export, print, and filing-bundle preparation are blocked until "
                "each named citation is verified or removed. " + HISTORY_DISCLAIMER)


def verify_all(text_or_citations: str | Iterable[Citation | str],
               resolver: CitationResolver | None = None,
               quotes: Mapping[str, str] | None = None,
               attestations: Mapping[str, CitationAttestation] | None = None) -> VerifyAllResult:
    """Verify every citation in a document text or an iterable of citations.

    With no resolver, every citation is ``unverified`` -- extraction alone
    never checks anything, so a resolver-less Verify-All always blocks a
    document that contains citations. ``quotes`` maps a normalized citation
    string to a quotation to check for ``quote_verified``. ``attestations``
    maps a normalized citation string to a recorded human attestation (see
    :class:`CitationAttestation`), accepted only for citation classes a
    resolver cannot cover and never over a ``not_found``.
    """
    if isinstance(text_or_citations, str):
        citations: list[Citation | str] = list(
            extract_citations(text_or_citations, include_unrecognized=True))
    else:
        citations = list(text_or_citations)
    results: list[VerificationResult] = []
    for cite in citations:
        key = _display(cite)
        quote = (quotes or {}).get(key)
        if resolver is None:
            result = VerificationResult(
                citation=key, status="unverified", source="none",
                detail="No resolver was supplied; the citation has not been checked.")
        else:
            result = _resolve(cite, resolver, quote)
        results.append(_apply_attestation(cite, result, (attestations or {}).get(key)))
    warnings: list[str] = []
    if results:
        warnings.append(HISTORY_DISCLAIMER)
    return VerifyAllResult(results=tuple(results), warnings=tuple(warnings))


@dataclass(frozen=True)
class GateResult:
    """The Verify-All gate verdict for export, print, or bundle prep."""

    allowed: bool
    blocked_citations: tuple[str, ...] = ()
    results: tuple[VerificationResult, ...] = ()
    message: str = ""


class CitationGateError(RuntimeError):
    """Raised by :func:`assert_verify_all` when the gate blocks."""

    def __init__(self, gate: GateResult):
        super().__init__(gate.message)
        self.gate = gate


def verify_all_gate(
    text_or_results: str | Iterable[Citation | str] | Iterable[VerificationResult],
    resolver: CitationResolver | None = None,
    quotes: Mapping[str, str] | None = None,
    attestations: Mapping[str, CitationAttestation] | None = None,
) -> GateResult:
    """The Verify-All gate: blocks on unverified or not found citations.

    Accepts document text, citations, or precomputed verification results.
    The gate blocks export, print, and filing-bundle preparation while any
    citation is ``unverified``, ``not_found``, or ``ambiguous``, and the
    verdict names each blocking citation. ``exists`` and ``quote_verified``
    pass, and so does ``attested`` for the citation classes a resolver
    cannot cover. ``history_unknown`` is reported as a warning and never
    blocks on its own, because history is unknown for every citation in
    this build.
    """
    items = list(text_or_results) if not isinstance(text_or_results, str) else None
    if items is not None and items and all(isinstance(i, VerificationResult) for i in items):
        results = tuple(
            _apply_attestation(i.citation, i, (attestations or {}).get(i.citation))
            for i in items)  # type: ignore[arg-type]
        combined = VerifyAllResult(
            results=results,
            warnings=(HISTORY_DISCLAIMER,) if items else ())
    else:
        combined = verify_all(
            text_or_results,  # type: ignore[arg-type]
            resolver=resolver, quotes=quotes, attestations=attestations)
    return GateResult(
        allowed=combined.allowed,
        blocked_citations=combined.blocked_citations,
        results=combined.results,
        message=combined.message)


def assert_verify_all(
    text_or_results: str | Iterable[Citation | str] | Iterable[VerificationResult],
    resolver: CitationResolver | None = None,
    quotes: Mapping[str, str] | None = None,
    attestations: Mapping[str, CitationAttestation] | None = None,
) -> GateResult:
    """Return the gate verdict, or raise :class:`CitationGateError` naming
    every blocking citation when the gate blocks."""
    gate = verify_all_gate(text_or_results, resolver=resolver, quotes=quotes,
                           attestations=attestations)
    if not gate.allowed:
        raise CitationGateError(gate)
    return gate


__all__ = [
    "ATTESTATION_CLASSES", "BLOCKING_STATUSES", "CHECKED_STATUSES", "CITE_RE",
    "COURTLISTENER_BASE_URL",
    "COURTLISTENER_TOKEN_ENV", "Citation", "CitationAttestation", "CitationGateError",
    "CitationResolver", "CourtListenerClient", "FORMATTER_LIMITS",
    "FixtureResolver", "GateResult", "HISTORY_DISCLAIMER", "OfflineResolver",
    "REPORTERS", "STATUSES", "VerificationResult", "VerifyAllResult",
    "assert_verify_all", "attestation_class", "case_names_match", "extract",
    "extract_all", "extract_citations",
    "format_all", "format_bluebook", "format_citation", "load_attestations",
    "normalize_reporter",
    "parse_citation", "parse_courtlistener_lookup", "record_attestation",
    "verify_all",
    "verify_all_gate", "verify_citation",
]
