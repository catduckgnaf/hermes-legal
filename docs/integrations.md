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
- Credentials — read only through a credential store: the OS keychain
  first (`security` on macOS, `secret-tool` on Linux), with an
  environment fallback (`CLIO_ACCESS_TOKEN` and similar) for tests and
  headless runs. Connectors never write plaintext secrets to disk.
- Transport — all HTTP goes through an injectable transport
  (`UrllibTransport` in production, `FakeTransport` in tests and sandbox
  checks). Tests run fully offline against synthetic accounts.

## P1 connectors

| Connector | Reads | Writes |
|---|---|---|
| Clio (`ClioConnector`, REST v4, OAuth 2.0 via `clio_oauth`) | Matters, contacts, calendar entries, bills — list calls follow `meta.paging.next` and return every page, not only the first | Create matter / contact — pending actions only |
| DocuSign (`DocuSignConnector`, REST v2.1, OAuth 2.0 via `docusign_oauth`) | Envelope list and status | Envelope creation is a pending action only; approving it is the send decision — nothing is sent before that |
| CourtListener / RECAP (`CourtListenerConnector`) | Free RECAP docket and document search | None |
| PACER (`PacerConnector`) | Approved document pull only | Paid pull: a RECAP check through `lookup_document` must first return a candidate (a search hit is a candidate, not the confirmed document), a miss returns a cost estimate only ($0.10 per page, $3.00 per-document cap), and a pull requires a named human approval |

Documenso and DocuSeal are the open, self-hostable signing alternatives;
their REST shape differs from DocuSign, so they are recorded in
`hermes_legal.connectors.docusign.OPEN_ALTERNATIVES` for a dedicated
client rather than emulated through the DocuSign client.
