# Integrations

Every connector follows the same contract: a `legal doctor` check, bring your
own credentials in the OS keychain, read-only by default, writes as pending
actions, per-matter enable/disable, and a data-flow label stating what leaves
the device and to whom.

| Integration | API | Priority |
|---|---|---|
| Local folders and files | Native | P0 |
| CourtListener / RECAP (Free Law Project) | Public REST, free token | P0 |
| govinfo, eCFR, Congress.gov | Public, api.data.gov key | P0 |
| Microsoft Graph (OneDrive, Outlook, calendar, Word files) | Public, OAuth 2.0 | P0 |
| Google Workspace (Drive, Gmail, Calendar) | Public, OAuth 2.0 | P0 |
| IMAP / SMTP email | Standard | P0 (sending always approval-gated) |
| Calendar and deadline rules, .ics export | Local data files + OAuth | P0 |
| Ollama / LM Studio | Local | P0 |
| Clio | Public REST, OAuth 2.0 — first practice-management target | P1 |
| DocuSign; Documenso / DocuSeal (open, self-hostable) | Public REST, OAuth 2.0 | P1 |
| PACER | Public, per-page fees — always check RECAP first | P1 |
| Dropbox / Box | Public, OAuth 2.0 | P1 |
| NetDocuments, Filevine | Partner / customer gated | P1 |
| Stripe, QuickBooks Online | Public | P1 (never handle card data or trust accounting locally) |
| PracticePanther, Smokeball, iManage, Ironclad, Juro, Adobe Sign, LawPay, UniCourt | Partner or enterprise gated | P2 |
| State e-filing | No public third-party API; EFSP certification required | P2, bundle prep only |
| Westlaw, Lexis | **No public API for third-party AI apps** | Link-out and export ingestion only |

## Connector framework (issue #8)

`hermes_legal.connectors` implements the contract above in code:

- `BaseConnector` — doctor check (`ok` / `missing` / `off` / `warn`; `off`
  never fails the run), a `DataFlowLabel` stating what leaves the device
  and to whom, a per-matter enable flag (`enabled_matters`; when a
  connector is restricted to specific matters, a call with no
  `matter_id` fails closed instead of skipping the check), and writes
  queued as `PendingAction` objects. A pending action performs no
  network call; only `approve(approved_by)` with a named human runs it.
  Every connector — Clio, DocuSign, CourtListener/RECAP, and PACER —
  carries all three contract pieces: its doctor check, its data-flow
  label, and the per-matter enable/disable flag.
- Privacy ceilings — when a connector is configured with a ceiling
  resolver (a callable, a mapping, or the matters database), it
  consults the matter's privacy ceiling, using the providers tier
  ordering, before any external call. A connector that sends data off
  the device is refused for a `LOCAL_ONLY` matter, an unknown matter
  fails closed, and a send with no explicit `matter_id` is refused
  when a resolver or a per-matter restriction is configured — there
  is no silent all-matters default on the send path.
- Credentials — read only through a credential store: the OS keychain
  first (`security` on macOS, `secret-tool` on Linux, and the Windows
  Credential Manager on Windows, through `ctypes`/win32cred with no
  new dependency), with an environment fallback (`CLIO_ACCESS_TOKEN`
  and similar) for tests and headless runs. The environment fallback
  is explicit and warned (a warning naming the variable, never its
  value), never silent. Connectors never write plaintext secrets to
  disk.
- OAuth — `OAuthClient` performs the authorization-code exchange and
  the refresh grant through the injectable transport, with PKCE
  (S256) support: `OAuthConfig.pkce_pair()` mints a verifier and
  challenge, the authorization URL carries the challenge, and the
  exchange sends the verifier. A refreshed token set keeps the new
  refresh token when the provider rotates it and keeps the old one
  when it does not; an OAuth error response raises `OAuthError`.
- Pending actions, durably — `DurablePendingActionStore` persists
  pending actions in SQLite (it can add its tables to the local
  database opened through the repo database module). An approval must
  be recorded first (`record_approval`); `approved_by` is accepted
  only when it matches that recorded approval, by approval id or by
  the recorded approver name — a free-form string is rejected. Every
  action carries an idempotency key, sent as the `Idempotency-Key`
  header and recorded with the delivery, so a retry after a timeout
  returns the recorded result instead of sending a second time.
- Transport — all HTTP goes through an injectable transport
  (`UrllibTransport` in production, `FakeTransport` in tests and sandbox
  checks). Tests run fully offline against synthetic accounts.

## P1 connectors

| Connector | Reads | Writes |
|---|---|---|
| Clio (`ClioConnector`, REST v4, OAuth 2.0 via `clio_oauth`) | Matters, contacts, calendar entries, bills — list calls follow `meta.paging.next` and return every page, not only the first | Create matter / contact — pending actions only |
| DocuSign (`DocuSignConnector`, REST v2.1, OAuth 2.0 via `docusign_oauth`) | Envelope list and status; the account base URI is discovered, not hard-coded: `discover_account()` reads the account (userinfo) endpoint, selects the default account's `base_uri` and `account_id` (demo/sandbox accounts resolve to the demo host), and caches the result per credential | Envelope creation is a pending action only; approving it is the send decision — nothing is sent before that |
| CourtListener / RECAP (`CourtListenerConnector`) | Free RECAP docket and document search | None |
| PACER (`PacerConnector`) | Approved document pull only; case search by case number through the PACER Case Locator, after authentication | Paid paths stay behind the RECAP-first rule: a RECAP check through `lookup_document` must first return a candidate for a document pull (a search hit is a candidate, not the confirmed document), a miss returns a cost estimate only ($0.10 per page, $3.00 per-document cap), and a pull requires a named human approval. Case Locator search follows the same shape: `locate_case` checks RECAP first and returns an estimate on a miss, and `search_pacer_cases` refuses without that prior check and a named approval, showing the estimate first |

PACER authentication uses the PACER authentication service
(`authenticate()` posts the configured username and password and keeps
only the returned token in memory) and the Case Locator search sends
that token. This is the live-auth boundary: no live PACER credentials
exist for this project, so the auth and case-locator shapes are
verified against fixtures only, and live verification with a real
PACER account remains outstanding.

Documenso and DocuSeal are the open, self-hostable signing alternatives,
recorded in `hermes_legal.connectors.docusign.OPEN_ALTERNATIVES`. A
self-hosted target that accepts a DocuSign-shaped envelope payload can
be configured by base URL alone through
`DocuSignConnector.self_hosted(..., base_url=..., provider="DocuSeal")`
(or `"Documenso"`): no DocuSign cloud host is contacted, and the
data-flow label and doctor check name the self-hosted provider and its
configured address instead. Their native REST shapes differ from
DocuSign, so a dedicated native client for Documenso or DocuSeal
remains follow-up work.
