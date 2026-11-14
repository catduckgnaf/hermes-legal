# Citations: verification, formatting, and the Verify-All gate

Hermes Legal never lets a model assert that a citation is real. That is the
anti-*Mata v. Avianca* design: in that case six invented opinions drew a
$5,000 sanction. Here, extraction finds citation-shaped text, a resolver
checks it against a real corpus, deterministic code formats it, and a gate
blocks the document until every citation has actually been checked.

## The three tools

| Tool | What it does | What it never does |
|---|---|---|
| `legal_cite_extract` | Finds citations in text: federal reporters, regional reporters, common state reporters, and `U.S.C.` statutes | It never marks anything as checked; extracted citations are `unverified` |
| `legal_cite_check` | Verifies a citation through a resolver (CourtListener for cases and govinfo for U.S.C. statutes today; a Caselaw Access Project resolver plugs into the same interface) | It never reports a failed or skipped lookup as a result |
| `legal_cite_format` | Formats a citation deterministically, Bluebook style, in code | Formatting is not verification; a formatted citation is still `unverified` until a resolver checks it |

## Statuses

- `unverified` — extracted or supplied, never looked up. The default.
- `exists` — a resolver found a matching authority.
- `quote_verified` — a resolver found the authority and the supplied
  quotation appears in the retrieved text.
- `not_found` — a resolver looked and found no matching authority. An
  invented citation reports `not_found`.
- `ambiguous` — a resolver returned several candidate authorities for one
  citation, so no single match can be asserted. It blocks the Verify-All
  gate exactly like `unverified` until a human determines which candidate,
  if any, is the cited authority.
- `quote_not_verified` — the authority was found, but a supplied
  quotation could not be confirmed in the retrieved opinion or statute
  text. It blocks the gate.
- `attested` — a citation class a resolver cannot cover (a Westlaw,
  Lexis, or public-domain citation), or a statute that could not be
  looked up, was checked by a named human and that check was recorded:
  who checked it, when, and from what source. Attestations are persisted
  in the `citation_attestations` table (`record_attestation` /
  `load_attestations` in `hermes_legal.citations`) and are recorded from
  the command line with `legal cite-attest` (see below). An attestation
  is never accepted for an ordinary case citation, and it never upgrades
  a citation a resolver returned as `not_found`.
- `history_unknown` — the subsequent-history dimension of every result.

**Subsequent history is always unknown here.** Hermes Legal has no
Shepard's or KeyCite, so a citation reported as `exists` or
`quote_verified` has not been checked for later reversal, overruling, or
other subsequent history, and the interface must say so wherever a result
is shown. A network or server failure is reported as `unverified` with the
error named — never as `not_found` and never as `exists`.

## CourtListener resolver

The CourtListener client uses the citation-lookup API over the standard
library HTTP stack. Set a free CourtListener token in the environment —
`COURTLISTENER_API_TOKEN`, `COURTLISTENER_TOKEN`, or
`HERMES_LEGAL_COURTLISTENER_TOKEN` are read, in that order. The token is
read from the environment only; it is not a settings value, has no Web UI
field, and is never written to a matter file. Verification sends only the
citation text, which matters for the privacy tiers: on a LOCAL-ONLY matter,
do not run a network resolver until the matter's tier allows that data to
leave the device.

Offline development and CI use recorded fixture JSON through the same
parsing code. Live calls happen only in tests marked `live`, which the
default test run excludes.

`legal cite-check` runs this resolver when a token is configured in the
environment, and reports each citation with the status the resolver
returned; a response with several clusters reports `ambiguous`, never a
match on the first cluster. With no token configured, `legal cite-check`
runs no resolver at all: it stays fully offline and reports every citation
as `unverified`. The resolver is injectable in code
(`main(argv, cite_resolver=...)`) so tests never need a network or a token.

Citation-lookup clusters carry no opinion text, so a quotation cannot be
checked from the lookup response alone. When a quotation is supplied and
the single matched cluster points at an opinion (through its
`sub_opinions` references), the client fetches that opinion's text from
the opinion API before judging the quote: present in the fetched text is
`quote_verified`, absent is the distinct `quote_not_verified` status, and
an opinion that cannot be fetched leaves the citation `exists` at the
client level while the shared resolver checks still block the gate on the
unconfirmed quotation.

## govinfo statute resolver

CourtListener citation lookup does not cover statutes, so `U.S.C.`
citations are resolved by `GovInfoClient` against govinfo. Existence is
checked at section granularity through the govinfo link service
(`/link/uscode/<title>/<section>`), which resolves only when that
section exists, and the result names the title's package id from the
govinfo package API (`USCODE-<edition>-title<N>`). A resolved section is
`exists` (or `quote_verified` / `quote_not_verified` when a quotation is
supplied); the link service's 404 is `not_found`; any other failure is
`unverified`, never a guess. An API key is read from `GOVINFO_API_KEY` or
`HERMES_LEGAL_GOVINFO_API_KEY` when configured; the link service works
without one. `legal cite-check` wires the two resolvers together through
a router — cases to CourtListener, statutes to govinfo — whenever a
CourtListener token or a govinfo key is configured, so a brief mixing
cases and statutes can pass Verify-All on evidence.

## LOCAL_ONLY matters and the lookup preview

Citation lookups send citation strings off the device. On a LOCAL_ONLY
matter they are blocked, never silently sent: a resolver wrapped in
`CeilingGuardedResolver` (at the citations layer) returns `unverified`
with the block reason and performs no lookup at all, and an unrecognized
ceiling blocks the same way. The recorded human attestation is the way
through for the citation classes it covers. `legal cite-check
--privacy-ceiling LOCAL_ONLY` (or `--matter-id <id>`, which reads the
matter's stored ceiling and its recorded attestations) enforces this
from the command line, and its output carries a `lookup_preview` — the
citation-lookup counterpart of the provider pre-send preview — listing
exactly which citation strings would be sent, to which resolver, under
which ceiling, with `would_send` empty when the lookup is blocked. The
agent dispatch path already refuses citation lookups on LOCAL_ONLY
matters the same way.

## Recording an attestation

```text
legal cite-attest "42 U.S.C. § 1983" --by "catduck" --source "United States Code (govinfo)"
legal cite-attest "2019 WL 4639462" --by "catduck" --source "Westlaw" --matter-id 3
```

`legal cite-attest` writes through the existing attestation store: it
records who checked the citation, when (stamped by the store), and the
source it was checked in, for a statute, Westlaw, Lexis, or public-domain
citation. It refuses an ordinary case citation — those must be checked
by a resolver — and refuses a missing who or source.

## Reporter list: why eyecite and reporters-db are not dependencies (yet)

The design notes describe extraction as "eyecite-style", and replacing
the hand-written reporter list with eyecite and reporters-db was
evaluated for this build. The decision is to keep the hand-written list
for now, on this evidence: the package metadata on current main declares
zero runtime dependencies (`dependencies = []`, with only an optional
PDF extra), and `hermes_legal.citations` is documented as standard
library only; resolving eyecite 2.7.8 and reporters-db 3.2.67 pulls in
seven packages, including the compiled `lxml` and `pyahocorasick` wheels
and `courts-db`, which would end the zero-dependency design for the
whole application, not just this module. Eyecite's citation model also
differs from this module's (its spans, statute handling, and resource
citations do not cover the unrecognized Westlaw, Lexis, and
public-domain shapes the Verify-All gate must fail closed on), so a swap
is a rewrite of the extraction and gate tests, not a list replacement.
What remains, if the dependency call is ever revisited: adopt eyecite
behind the existing `extract_citations` interface as an optional extra,
prove the gate's unrecognized-citation coverage against it first, and
only then retire the hand-written list.

## Bluebook-style formatter limits

The formatter is deterministic code, not a model. Its limits are stated in
`hermes_legal.citations.FORMATTER_LIMITS` and summarized here:

- It covers case citations in the reporters the extractor knows, plus
  `U.S.C.` statute citations. Books, articles, constitutions, rules, and
  docket-number citations are returned unchanged rather than reformatted
  by guesswork.
- It normalizes volume, reporter abbreviation, spacing, first page,
  pincite, and the court-and-year parenthetical. It does not shorten case
  names, apply every Bluebook abbreviation table, or build short-form
  citations (`Id.`, `supra`).
- A missing court or year is omitted, never invented.

## The Verify-All gate

`verify_all_gate` (and `assert_verify_all`, which raises and names the
offenders) blocks export, print, and filing-bundle preparation while any
citation in the document is `unverified`, `not_found`, or `ambiguous`. The verdict names
each blocking citation. A document whose citations all report `exists` or
`quote_verified` passes, as does one whose only unchecked citations carry
a recorded human attestation for a class a resolver cannot cover
(statutes, Westlaw, Lexis, and public-domain citations); a document with no citations passes. History
being unknown warns but does not block on its own, because history is
unknown for every citation in this build — blocking on it would block
everything while adding no information.
