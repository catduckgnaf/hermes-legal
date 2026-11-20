# Hermes Legal

### Your matters, on your computer, with an AI agent that shares nothing by default.

**Name.** The product is **Hermes Legal**. The repository and package keep the
derived identifier forms of that name: `hermes-legal`, `hermes_legal`,
`HERMES_LEGAL_*` — the same name in kebab, snake and upper-snake case.

A local-first app for legal work, inspired by
[hermes-finance](https://github.com/apelabs-dev/hermes-finance) — the same
pattern (a local app, an MCP server, and one shared set of agent tools),
rebuilt for law instead of money, and for **document editing instead of
coding**.

Hermes is designed for coding. Legal work is different: the document *is* the
work product, the file in the folder *is* the record, and the contents are
privileged. So Hermes Legal is designed around four rules:

1. **Local by default.** Matters, documents and the database live in a local
   SQLite file and ordinary folders on your own computer. The default AI tier
   is **LOCAL-ONLY**: the model runs on your machine and *nothing leaves the
   device*.
2. **Documents first.** Open a file or a folder and work on it: DOCX compare
   and redlines with real Word track changes, Bates stamping across a
   production and true PDF redaction (both on PdfCraft), contract review
   against a playbook, and a citation checker with a Verify-All gate.
3. **Writes ask first.** A write tool changes nothing on its own: it saves a
   pending action that a named person must approve at an interactive terminal
   before anything runs — and write proposals are refused outright in
   scheduled or unattended runs.
4. **No invented authority.** A citation is shown as *exists / quote verified /
   history unknown* from a real resolver (CourtListener today), never asserted
   by the model. That is the anti-*Mata v. Avianca* design.

> **Not a fork.** This repository was built new, using hermes-finance as
> architectural inspiration. No hermes-finance code was copied. Both projects
> are AGPL-3.0. Hermes Agent itself (Nous Research) is MIT and is a separate
> project.

## No Hermes plugin

There is **no Hermes plugin** for Hermes Legal, and none is planned. An
earlier plugin adapter was decided against and is being removed; do not
install it or depend on it. The supported agent surface is the MCP server
plus the shared `legal_*` tool set described below, reached through the
`legal` CLI or any MCP client.

## Desktop client: in development

A lightweight desktop client is in development in `desktop/`: a Tauri 2
shell with a plain HTML, CSS and JavaScript frontend that connects to a
Hermes agent over its API server, the same way the Android client apps do
(sessions, streaming chat, and approval prompts when the server supports
them). **Windows first, Linux later.** CI builds unsigned Windows installers
and tests the client against a mock server; it has not been verified
against a live Hermes server and there is no signed release yet. Until
there is, the CLI, the MCP server and `legal serve` are the supported ways
to use Hermes Legal. The v1 core below targets Linux and Windows; macOS is not
part of v1.

## Status: what works today

Every row below was checked against the code on `main`. "Working" means the
code path exists and is covered by the offline test suite. "Scaffold" means
only a stub or packaging files exist.

| Surface | Status | Notes |
|---|---|---|
| Matter workspaces (`legal matter open/list/recent/documents`) | Working | A matter is an ordinary folder (or one file, whose folder becomes the matter). Documents are listed live from disk, never copied into a separate store. Opening takes a snapshot; a guarded write that would overwrite an external edit writes a conflict copy instead. |
| `legal` CLI (`doctor`, `status`, `demo`, `matter`, `models`, `tools`, `tool`, `actions`, `ask`, `ai-log`) | Working | Covered by the offline test suite. `legal doctor` runs offline and exits non-zero only when a required item is missing; optional integrations are reported but do not fail the run. `legal ask` answers from a matter using only a model server on this computer (loopback enforced) and needs one running. |
| Document tools: `doc-compare`, `doc-redline` | Working | Deterministic, no model involved. Compare is paragraph-level. A redline is a new DOCX with real `w:ins` / `w:del` track changes by `hermes-legal (AI - unverified)`; it works on top-level body paragraphs — tables are preserved in place and their text is not redlined — and it never overwrites an existing file. |
| PDF tools: `bates-plan`, `bates-stamp`, `redact`, `redact-verify` | Working | Redaction and Bates stamping run on [PdfCraft](https://github.com/storytold/pdfcraft) (`pdfcraft-cli`, installed separately; `legal doctor` reports it) plus the optional `pdf` extra (`pypdf`). `redact` cuts the phrases out of the page content with the layout kept, removes hidden information, rewrites the file in full, and writes nothing unless an independent pypdf re-extraction and a byte search both find no phrase. Text that exists only inside an image is not found (run OCR on scans first). `bates-stamp` numbers one sequence across several files and never overwrites; without PdfCraft it uses a pypdf overlay. `redact --engine rebuild` works without PdfCraft but keeps only the text layer. `redact-verify` re-checks any PDF. |
| Citations: extraction and formatting | Working | Extraction and Bluebook-style formatting run offline, with the project's own parser and no model. Extraction by itself verifies nothing, and every extracted citation is reported as unverified. |
| Citation verification and the Verify-All gate | Working | A real CourtListener resolver client and a Caselaw Access Project (`CaselawAccessClient`) resolver exist in `citations.py`. `legal cite-check` uses them when a CourtListener or CAP token is set in the environment; otherwise the command stays offline and reports every citation as unverified. Live checks need a token and network and are excluded from the offline suite. The Verify-All gate blocks while any citation is unverified, not found or ambiguous, and history is always reported as unknown. U.S.C. statutes are checked against govinfo at the exact section cited; a section govinfo does not have stays unverified. On a LOCAL_ONLY matter (`--matter-id` or `--privacy-ceiling`) no lookup leaves the device, and `legal cite-attest` records a human check for a statute, Westlaw, Lexis or public-domain citation. |
| Playbooks | Working | Markdown playbooks (NDA, MSA and employment samples in `playbooks/`, plus a fictional demo contract) are parsed at review time; review splits a contract into clauses and returns findings tied to clauses. Keyword checks only — a clean result is not assurance that a clause is acceptable. |
| Deadlines | Working | Extraction returns candidates only and writes nothing. Calculation loads versioned Federal Rules of Civil Procedure rule data files and shows the rule and the arithmetic. Only a named human can confirm a candidate or calculation into a stored deadline (filing deadlines need two different confirmers), and only confirmed deadlines export to an `.ics` file. The starter rule files are a small set of examples, not a complete rule library. |
| Spine: one shared tool set, dispatch and approvals | Working | Tools are defined once in `tooldefs.py` (18 `legal_*` definitions). Every surface goes through `dispatch.py`, which enforces the privacy ceiling, the approval flow and the unattended refusal in one place. 16 of the 18 tools have implementations today (see the next row). |
| Agent tools (`legal_*`) | Working, in part | Implemented: `legal_matter_list`, `legal_matter_get`, `legal_doc_search`, `legal_doc_read`, `legal_doc_compare`, `legal_cite_extract`, `legal_cite_check`, `legal_cite_format`, `legal_playbook_review`, `legal_doc_redline`, `legal_chronology`, `legal_deadline_extract`, `legal_deadline_calc`, `legal_intake_summary`, `legal_time_log`, `legal_efile_bundle` (prepares a bundle for a person to file; it never files). Defined but not built yet, and they say so (`not_implemented`) instead of returning a plausible empty result: `legal_transcribe`, `legal_sync`. Unbuilt tools are not advertised to agents. |
| MCP server (`legal mcp serve`) | Working | A standard-library MCP server over stdio: initialize, ping, tool list and tool calls. Read tools are listed by default. Write tools are listed only after a person runs `legal mcp allow-writes on`, and even then a call only saves a pending action for approval. |
| Connectors (Clio, DocuSign, CourtListener / RECAP, PACER) | Working, in part | A shared connector contract (doctor check, data-flow label, per-matter enable flag, credentials only through a credential store, read-only by default, writes as pending actions) plus these four connectors exist, with offline tests against fake transports. PACER pulls require a RECAP check first and a named human approval. The wider P0/P1/P2 list under Connections is the roadmap, not the shipped set. |
| `legal serve` (local dashboard) | Working | A standard-library web dashboard on 127.0.0.1 with a new random token every launch: matters, documents, deadlines, citation status, the pending-actions queue and a local-model Ask box, all through `dispatch.py`. Approving or rejecting needs a typed confirmation and a server started from an interactive terminal, the same rule as the CLI. A non-loopback bind needs `--allow-non-loopback` and prints a warning. |
| Desktop app | In development | The client described above. Tested against a mock Hermes server and built unsigned for Windows in CI; not yet verified against a live Hermes server, and installers from CI are not a release. |

## Quickstart

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/catduckgnaf/hermes-legal.git
cd hermes-legal
uv sync
uv run legal doctor     # offline: checks editors, local models, integrations
uv run legal demo       # builds a synthetic demo matter (fictional client, no real data)
uv run legal matter list
uv run legal cite-check "Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)"
```

With no CourtListener token configured, that last command runs offline: it
extracts and formats the citation, reports it as unverified, and the
Verify-All gate blocks. That is the honest answer, not an error.

Open one of your own folders as a matter when you are ready:

```sh
uv run legal matter open <folder-or-file>
uv run legal matter documents 1
uv run legal tools
uv run legal tool legal_matter_list --args '{}'
```

### Run the MCP server

```sh
uv run legal mcp serve              # stdio; read tools only by default
uv run legal mcp allow-writes on    # also list write tools; calls still only propose actions
uv run legal actions list           # review pending actions
```

Approving is the only way a proposed write runs, and it needs an interactive
terminal: `legal actions approve <id> --by <your name>`.

## The privacy tiers (the whole point)

| Tier | What leaves your device | Training on your data | Default |
|---|---|---|---|
| **LOCAL-ONLY** | Nothing. Model, embeddings, OCR and transcription all run on-device. | Impossible — there is no recipient. | **Default for every matter** |
| **ZERO-RETENTION** | The prompt and the chunks you approve, over TLS, to a named provider | Contractually no | Opt in, per matter |
| **STANDARD** | Same, to a no-training paid API (typically up to 30 days of abuse/safety logs) | No | Opt in, per matter |
| **Consumer chat accounts** | Everything pasted | May train | **Blocked for client work** |

A matter set to LOCAL-ONLY cannot call a cloud model even if you ask it to.
On an agent surface (MCP), matter content is returned only when the operator
has declared the agent's tier in `HERMES_LEGAL_AGENT_TIER` and that tier fits
the matter's ceiling; when the tier is undeclared, no matter content is
returned at all. A send through a cloud tier produces a pre-send preview of
exactly what would go out. The full catalog, with the models that run at each
hardware level, is in [docs/models.md](docs/models.md).

## Connections

Offered as bring-your-own-credential connectors, each with a `legal doctor`
check, read-only by default, and writes as pending actions. Shipped today:
the connector framework and the Clio, DocuSign, CourtListener / RECAP and
PACER connectors (see Status above). The rest of this list is the priority
roadmap:

- **P0:** local folders, CourtListener / RECAP, govinfo / eCFR, Microsoft Graph
  (OneDrive, Outlook, calendar), Google Workspace, IMAP email, calendar / .ics,
  Ollama and LM Studio (local models)
- **P1:** Clio, DocuSign and Documenso, PACER (RECAP-first, so you check the free
  archive before paying per page), Dropbox / Box, NetDocuments, Stripe /
  QuickBooks, Filevine, local transcription (Whisper)
- **P2:** PracticePanther, Smokeball, iManage, Ironclad / Juro, Adobe Sign,
  LawPay, UniCourt / Trellis, Notion / Slack, state e-filing bundle prep

Westlaw and Lexis offer no public API for third-party AI applications, so
Hermes Legal does not build on them — it verifies against open corpora instead
and says so honestly. Full table: [docs/integrations.md](docs/integrations.md).

## Documentation

- [Getting started](docs/getting-started.md) — install, the demo matter and
  matter workspaces
- [Architecture](docs/architecture.md) — the package, the database and the
  shared tool set
- [Agent tools](docs/agent-tools.md) — the `legal_*` tools, dispatch and
  approvals
- [Document editing](docs/document-editing.md) — DOCX redlines, Bates
  stamping and PDF redaction, with their limits
- [Citations](docs/citations.md) — verification, formatting and the
  Verify-All gate
- [Deadlines](docs/deadlines.md) — candidates, human confirmation and rule
  calculation
- [Playbooks](docs/playbooks.md) — the playbook format and the clause review
- [Models and privacy tiers](docs/models.md) — the provider catalog by tier
- [Integrations](docs/integrations.md) — the connector contract and the
  priority list
- [Security](docs/security.md) — the privacy and safety design

## Repository layout

```text
src/hermes_legal/    the app: cli, db, matters, citations, deadlines,
                     playbooks, providers, tooldefs, dispatch, mcp_server,
                     serve (dashboard), connectors
playbooks/           sample playbooks and the fictional demo contract
demo_matter/         the synthetic demo matter (fictional client)
docs/                MkDocs site: architecture, security, models, integrations
tests/               offline suite; live checks are marked and excluded by default
scripts/             check.py gates, contribution and spelling checkers
desktop/             the desktop client in development (Tauri 2 shell,
                     plain JavaScript frontend, mock-server tests)
.github/             issue forms, PR template and workflows
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Prose uses American spelling, tests
run offline by default, and a pull request is not done until its description
passes the contribution checker in `scripts/check_contribution.py`.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE). This matters for legal work: anyone
who runs a modified Hermes Legal as a network service must offer their users the
source. Local models are downloaded at your request rather than bundled, so each
model keeps its own license, which the model picker shows.

## A necessary warning

Hermes Legal is a tool for legal work, not a lawyer. It does not provide legal
advice, it must not be described as an "AI lawyer," and every citation, deadline
and document it produces needs a qualified human to verify it before it is filed,
sent or relied on. ABA Formal Opinion 512 (2024) is built into the design rather
than left to a disclaimer page: see [docs/security.md](docs/security.md).
