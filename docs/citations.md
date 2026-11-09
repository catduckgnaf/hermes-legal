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
| `legal_cite_check` | Verifies a citation through a resolver (CourtListener today; Caselaw Access Project and govinfo resolvers plug into the same interface) | It never reports a failed or skipped lookup as a result |
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
- `attested` — a citation class a resolver cannot cover (a statute, or a
  Westlaw, Lexis, or public-domain citation) was checked by a named human
  and that check was recorded: who checked it, when, and from what source.
  Attestations are persisted in the `citation_attestations` table
  (`record_attestation` / `load_attestations` in
  `hermes_legal.citations`). An attestation is never accepted for an
  ordinary case citation, and it never upgrades a citation a resolver
  returned as `not_found`.
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
