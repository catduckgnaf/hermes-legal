# Hermes Legal

### Your matters, on your computer, with an AI agent that shares nothing by default.

**Name.** The product is **Hermes Legal**. The repository, package and plugin keep
the derived identifier forms of that name: `hermes-legal`, `hermes_legal`,
`HERMES_LEGAL_*` — the same name in kebab, snake and upper-snake case.

A local-first desktop for legal work, inspired by
[hermes-finance](https://github.com/apelabs-dev/hermes-finance) — the same pattern
(a local app, a Hermes plugin, an MCP server, and one shared set of agent tools),
 rebuilt for law instead of money, and for **document editing instead of coding**.

Hermes is designed for coding. Legal work is different: the document *is* the work
product, the file in the folder *is* the record, and the contents are privileged.
So Hermes Legal is designed around four rules:

1. **Local by default.** Matters, documents and the database live in a local
   SQLite file and ordinary folders on your own computer. The default AI tier is
   **LOCAL-ONLY**: the model runs on your machine and *nothing leaves the device*.
2. **Documents first.** Open a file or a folder and work on it: DOCX editing with
   real Word track changes, PDF annotation, Bates stamping and true redaction,
   contract review against a playbook, and a citation checker that verifies a
   citation exists before it can enter a document.
3. **Writes ask first.** Filing, sending, signing and any other change that leaves
   the app is an approval card, never a silent action — and is refused outright in
   scheduled or unattended runs, exactly as in hermes-finance.
4. **No invented authority.** A citation is shown as *exists / quote verified /
   history unknown* from a real resolver (CourtListener, Caselaw Access Project,
   govinfo), never asserted by the model. That is the anti-*Mata v. Avianca* design.

> **Not a fork.** This repository was built new, using hermes-finance as
> architectural inspiration. No hermes-finance code was copied. Both projects are
> AGPL-3.0. Hermes Agent itself (Nous Research) is MIT and is a separate project;
> Hermes Legal plugs into it the same way hermes-finance does.

## Platforms

**Linux and Windows first.** macOS is a fast follow, not part of v1.
The standalone desktop is Tauri 2 with a Python sidecar (see
[docs/desktop.md](docs/desktop.md)); the Hermes plugin and the local dashboard
ship first, so v1 is usable on all three operating systems through Hermes while
the native installers are built.

- Linux: AppImage, `.deb`, and Flatpak
- Windows: signed NSIS/MSI installer, `winget` manifest

## Quickstart

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/catduckgnaf/hermes-legal.git
cd hermes-legal
uv sync
uv run legal doctor     # offline: checks editors, local models, integrations
uv run legal demo       # builds a synthetic demo matter (fictional client, no real data)
uv run legal serve      # scaffold only: prints a notice and serves nothing yet (see Status below)
uv run legal matter list
uv run legal cite-check "Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)"
```

## Status: what works today

| Surface | Status | Notes |
|---|---|---|
| `legal` CLI: `doctor`, `status`, `demo`, `matter`, `models`, `tools` | Working | Covered by the offline test suite. `legal doctor` exits non-zero when a required item is missing; optional integrations are reported but do not fail the run. |
| Document tools: `doc-compare`, `doc-redline`, `bates-plan`, `redact-verify` | Working | Deterministic, no model involved. `bates-plan` plans labels only and stamps nothing. |
| Citations: `cite-check` extraction and formatting | Working | Extraction and formatting run offline. The CLI runs no resolver, so it reports every citation as unverified. |
| Citation verification against CourtListener | Working, live only | A real resolver client exists in `citations.py`; its checks are marked `live`, need a token and network, and are excluded from the offline suite. |
| Agent tools (`legal_*` definitions in `tooldefs.py`) | Partial | 18 tools are defined; only `legal_doc_compare` and `legal_doc_redline` have a mapped implementation today. The rest are definitions awaiting implementations. |
| Connectors (Clio, DocuSign, PACER) | Partial | A shared connector contract plus first connectors exist with offline tests; the P0/P1 list under Connections is the roadmap, not the shipped set. |
| `legal serve` (local dashboard) | Scaffold | A stub: it prints a notice and binds nothing. There is no dashboard yet. |
| MCP server | Scaffold | `mcp_server.py` is a stub (module docstring and the tool import only) and the `mcp` dependency is optional; no MCP server runs yet. |
| Hermes plugin | Scaffold | `plugin.yaml` and the usage skill ship, but the adapter module is a docstring-only stub with no tool registration code yet. |
| Desktop app (Tauri 2) | Scaffold | Shell configuration, a placeholder page and packaging files exist; installers are not built yet. |

## The privacy tiers (the whole point)

| Tier | What leaves your device | Training on your data | Default |
|---|---|---|---|
| **LOCAL-ONLY** | Nothing. Model, embeddings, OCR and transcription all run on-device. | Impossible — there is no recipient. | **Default for every matter** |
| **ZERO-RETENTION** | The prompt and the chunks you approve, over TLS, to a named provider | Contractually no | Opt in, per matter |
| **STANDARD** | Same, to a no-training paid API (typically up to 30 days of abuse/safety logs) | No | Opt in, per matter |
| **Consumer chat accounts** | Everything pasted | May train | **Blocked for client work** |

A matter set to LOCAL-ONLY cannot call a cloud model even if you ask it to.
Every Ask shows the tier badge and a pre-send preview of exactly what would go
out. The full catalog, with the models that run at each hardware level, is in
[docs/models.md](docs/models.md).

## Connections

Offered as bring-your-own-credential connectors, each with a `legal doctor`
check, read-only by default, and writes as pending actions:

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

## Install as a Hermes plugin

The plugin is an adapter over a trusted local checkout, exactly as in
hermes-finance: it loads `src/hermes_legal/tooldefs.py` from that checkout, opens
the database read-only, never creates a missing database, and reads keys only
from Hermes.

```sh
git clone https://github.com/catduckgnaf/hermes-legal.git
cd hermes-legal && uv sync
export HERMES_LEGAL_APP_DIR="$PWD"
uv run legal doctor
hermes plugins install 'https://github.com/catduckgnaf/hermes-legal.git#hermes_plugin' --no-enable
hermes plugins validate hermes_plugin
hermes plugins enable hermes-legal
```

## Repository layout (mirrors Print Handy and hermes-finance)

```text
src/hermes_legal/    the app: cli, db, matters, citations, providers, tooldefs
hermes_plugin/       the thin Hermes adapter (plugin.yaml, usage skill, report jobs)
desktop/             Tauri 2 shell and Linux / Windows packaging
docs/                MkDocs site: architecture, security, models, integrations
tests/               offline suite; the demo matter is synthetic and fictional
scripts/             check.py gates, contribution and spelling checkers
.github/             issue forms, PR template and workflows, as in Print Handy
```

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
