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
