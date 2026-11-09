# hermes-legal — Foundation Research Report
**Date:** 2026-11-09 (America/New_York) · **Status:** Foundation document for a new open-source project, *fork-in-spirit, NOT a code fork* of Hermes / hermes-finance · **Targets:** Linux + Windows desktop first
**Method:** Primary repos opened live 2026-11-09; all other claims via web index, cross-checked across ≥2 sources where pricing/privacy mattered. Pricing in legal tech is mostly quote-only — figures labelled *Published / Reported / Quote-only* accordingly. Do not treat reported prices as list prices.

---

## Executive Summary

1. **The gap is real and empty.** No incumbent combines: (a) document-editing-first desktop, (b) local-folder / local-file work, (c) local-only inference by default, (d) open source, (e) no seat minimum, (f) matter-scoped workspaces. A July 2026 competitor survey concluded the cell *“one-click local desktop app + legal-specific + mechanically verified page/span citations + free/open-core — is empty as of mid-2026”* [https://github.com/janderswag/docuchat.app/blob/HEAD/docs/council/2026-07-07-reports/competitor-landscape.md]. Relativity Server (on-prem) is *sunsetting — no new matters after Jan 1, 2028, gen AI cloud-only* — same source — stranding privacy-first demand. Robin AI was dismantled (services to Scissero Dec 2025; ~18-person tech team acqui-hired by Microsoft into Word Jan 2026) and now ships as Microsoft Legal Agent in Word gated behind M365 Copilot / E7 at $99/user/mo [https://www.iqdoc.app/blog/what-the-model-labs-built-for-legal].
2. **Mirror hermes-finance, not Hermes Desktop's code.** hermes-finance is the cleanest template: Python 3.12 + SQLite + vanilla-JS dashboard, a thin Hermes plugin adapter (`hermes_plugin/` + `src/hermes_finance/tooldefs.py`), 16 typed tools, MCP server, read-only-by-default with *approval-gated writes*, a `doctor` CLI, secrets never read from disk by the plugin, and three AI modes (Hermes model / MCP / bring-your-own OpenAI-compatible endpoint incl. Ollama/LM Studio). hermes-legal should copy that *contract* exactly, swapping finance objects for matters/documents/citations/deadlines.
3. **Privacy is the product.** ABA Formal Opinion 512 (29 July 2024) requires informed client consent — boilerplate is *not* sufficient — before putting representation information into a *self-learning* tool, under Model Rules 1.1, 1.6, 1.4, 1.5, 5.1/5.3, 3.3 [https://blog.promise.legal/ai-ethics-compliance-law-firms-2026/]. A LOCAL-ONLY default makes that analysis radically simpler. Cloud must be opt-in per matter, labelled ZERO-RETENTION vs STANDARD, with what-leaves-the-device shown *before* send.
4. **Document editing is the hard problem, not chat.** TipTap/ProseMirror/Lexical do **not** round-trip DOCX track changes as native OOXML `w:ins/w:del` — theirs is JSON-based, paid-extension territory [https://pdfTron.com/capabilities/docx-editor/comparison/tiptap]. For DOCX-centric legal work the credible open stacks are: **ONLYOFFICE Docs (AGPL-3.0, OOXML-native) embedded/served locally, or LibreOffice/Collabora (MPL-2.0 / LibreOffice core) headless + native**, plus a *programmatic* DOCX layer (python-docx / docx-rs + direct OOXML patching) for AI redlines that must survive in Word. Build v1 editing around files on disk, not a proprietary JSON doc model.
5. **Recommended shell: Electron for v1 if you must interoperate with Hermes Desktop, Tauri 2 for the standalone hermes-legal product.** Hermes Agent's own desktop is Electron (`apps/desktop/`, in-app self-update, macOS/Linux/Windows) [https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5]. Tauri is 10–30× smaller ( ~3–10 MB vs 85–150 MB), ~½ RAM, Rust core, system WebView [https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/] — attractive for solo/small-firm PCs and for bundling ONLYOFFICE/LibreOffice sidecars, but WebView2/WebKitGTK rendering variance hurts DOCX fidelity testing. **Decision rule in §7:** standalone product → Tauri 2 + Python sidecar (mirrors hermes-finance); literal Hermes Desktop plugin page → ship the plugin + web dashboard first, desktop shell second. Do not block v1 on the shell.
6. **v1 should NOT try to be Clio + Westlaw + Everlaw.** v1 = local matter workspaces, first-class folder opening, DOCX/PDF editing + true redlines, clause/playbook review, citation *verification* (not just formatting) against CourtListener/CAP/govinfo, deadline extraction, and local RAG over the matter — all offline-capable. Practice-management sync (Clio), e-signature (DocuSign/Documenso), and e-discovery at scale are P1/P2 plugins.

---

## Findings

### 1. Hermes Ecosystem

#### 1.1 Nous Research Hermes Agent — core
- **What:** *“The self-improving AI agent built by Nous Research… built-in learning loop — creates skills from experience, improves them during use, nudges itself to persist knowledge, searches its own past conversations”*; MIT License; 261,923 stars, 58,295 forks, created 2025-07-22 — **verified live** [https://github.com/NousResearch/hermes-agent].
- **Model-agnostic routing:** *“Use any model — Nous Portal, OpenRouter, OpenAI, your own endpoint… Switch with `hermes model` — no lock-in.”* Providers in `agent/*_adapter.py` (anthropic, bedrock, gemini, codex, vertex), `plugins/model-providers/`, credential pools + fallback, separate auxiliary LLM for side tasks [https://github.com/moikapy/lich/blob/HEAD/wiki/raw/audits/2026-09-23-hermes-vs-lich.md]. Also Ollama / vLLM / LM Studio self-hosted endpoints [https://www.ithub.directory/agent-frameworks/hermes-agent].
- **Memory:** Bounded `MEMORY.md` (2,200 chars) + `USER.md` (1,375 chars) in `~/.hermes/memories/`, frozen snapshot at session start; FTS5 session search with LLM summarisation; pluggable providers via `agent/memory_provider.py` (Honcho, mem0, supermemory, hindsight, etc.) [same Lich audit; https://www.ithub.directory/agent-frameworks/hermes-agent].
- **Skills:** Procedural memory. A skill = `<skills>/[category/]<name>/SKILL.md` (YAML frontmatter) + optional `references/ templates/ scripts/ assets/`; agentskills.io-compatible, progressive disclosure, agent-created + curator-graded/pruned on a cycle, `hermes curator lock` in v0.23.0 [https://www.ithub.directory/agent-frameworks/hermes-agent].
- **Tools / execution:** 6–7 terminal backends (local, Docker, SSH, Modal, Daytona, Vercel Sandbox, Singularity/Apptainer), cron scheduler, subagent delegation, MCP client *and* server (`tools/mcp_tool.py`, `hermes mcp-serve`), gateway to Telegram/Discord/Slack/WhatsApp/Signal/CLI/TUI/desktop from one process [https://github.com/NousResearch/hermes-agent].
- **State:** `~/.hermes/` (POSIX) / `%LOCALAPPDATA%\hermes` (Windows): `config.yaml`, `.env`, memories, skills, SQLite session store (`state.db`) [https://www.ithub.directory/agent-frameworks/hermes-agent].
- **⚠️ Legal translation:** Hermes memory/skills learning loop is a *liability* if copied naively for law: cross-matter leakage is exactly what Opinion 512 warns about (information from one client surfacing in another's work, even inside one firm). hermes-legal must make memory/skills **matter-scoped by default, cross-matter only by explicit opt-in, never self-learning on client content**.

#### 1.2 Hermes Desktop
- Official desktop is in the monorepo at `apps/desktop/` — **Electron**, *“a real native app, not a terminal wrapper… one-click install, in-app self-update, drag-and-drop files into chat, inline model picker, concurrent multi-profile sessions”*, macOS/Linux/Windows, v0.16.0 “Surface Release” 2026-06-05 built in ~100 PRs [https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5]. Can connect to a *remote* Hermes gateway over WebSocket with OAuth or username/password. Nix/Home Manager packaging exists (`programs.hermes-agent.desktop.enable`, `HERMES_DESKTOP_HERMES`) [https://github.com/NousResearch/hermes-agent/pull/91797].
- There is **no separate “Hermes Desktop by ApeLabs” product** in sources found: ApeLabs (`apelabs-dev`) is a prolific Hermes *plugin* author (hermes-finance, hermes-mock-review) listed in the Hermes Marketplace / plugin catalogs [https://hermes-plugins.korchasa.dev/ ; https://hermesatlas.com/ecosystem/]. Treat “ApeLabs Hermes” = plugin ecosystem, not the shell vendor. Desktop plugin model is now dual: *desktop components* (one app, Settings ▸ Plugins) vs *agent components* (per-profile, Capabilities ▸ Plugins, like Skills/Tools/MCP), with a curated SHA-pinned plugin catalog [https://github.com/NousResearch/hermes-agent/pull/97005].
- Desktop plugins can add a page + dashboard API: e.g. agent-station adds route `/agent-station`, mounts `dashboard/plugin_api.py` at `/api/plugins/agent-station/`, reads `state.db` read-only (SQLite `mode=ro`) [https://github.com/NousResearch/hermes-agent/pull/140760]. **This is the exact pattern for a Legal page.**

#### 1.3 hermes-finance — the template to mirror — VERIFIED LIVE
Source: [https://github.com/apelabs-dev/hermes-finance] opened 2026-11-09.
- **Identity:** *“Self-hosted personal-finance dashboard: Plaid bank sync, categories, budgets and rules, with agent tools that stay read-only unless you approve a change.”* 46 stars, 6 forks, 47 commits, created 2026-10-24, **License: AGPL-3.0** (note: Hermes Agent itself is MIT — do not confuse them; a hermes-legal that copies finance *code* inherits AGPL, one that copies only its *architecture* does not).
- **Stack:** Python 3.12+ (`uv`, `pyproject.toml`, `.python-version`), **SQLite** (`finance.db`, 0600 file in 0700 dir), **Vanilla JS + Chart.js** dashboard (no React build), pytest, MkDocs Material. Repo: `src/hermes_finance/` (app + `tooldefs.py`), `hermes_plugin/` (adapter), `tests/`, `docs/`, `scripts/`, `demo/`.
- **Data sources / integrations:** Plaid (banks, Trial = max 10 Items *for life*, app counts slots and refuses duplicates), Alpaca (investments, live only), Carfax (car values), Redfin (home values), OFX/QFX/CSV import, manual accounts. Each integration has a section in README + `finance doctor` line.
- **The three AI modes (copy this verbatim in spirit):**
  1. **Hermes plugin** — native tools + usage skill + optional cron report jobs (`hermes finance crons`); Ask panel delegates to Hermes's configured model so *“the app never sees a model key”*; writes show Hermes approval prompt in plain words; **scheduled/unattended runs refuse writes**.
  2. **MCP server** — `finance mcp` (stdio) or `/mcp` on `finance serve`, any MCP client; **read-only by default**, writes only as *pending actions* approved in Settings after `finance mcp allow-writes on`.
  3. **API key / BYO endpoint** — any OpenAI-compatible endpoint (OpenRouter, OpenAI, **local Ollama or LM Studio**); app is its own harness, max 6 tool rounds, deadline + monthly spend cap; key in app secrets file; *“your questions and the data the tools read go to that provider”* — disclosed in README.
- **Tool contract:** 16 `finance_*` tools in `tooldefs.py`; *“A read tool returns exactly what the matching `finance <command> --json` prints.”* CLI, dashboard, MCP and agent all share one implementation — no divergent logic.
- **Plugin install / security:** `hermes plugins install 'https://github.com/<owner>/hermes-finance.git#hermes_plugin' --no-enable`, then `validate` / `doctor --ci` / `enable`; plugin loads `tooldefs.py` from a trusted local checkout (`HERMES_FINANCE_APP_DIR`), does **not** download the app, opens DB **read-only and never creates a missing DB**, reads keys **only from Hermes** (never `secrets.env` / `.env` directly in plugin mode). Standalone secrets at `~/.config/hermes-finance/secrets.env` (0600). `finance doctor` runs offline, exit 1 if an integration is missing, `off` ≠ missing.
- **Dashboards:** Overview / Transactions / Budgets / Accounts / net-worth history, Ask panel, Settings → integrations, first-run wizard (This computer only vs network, demo/sandbox mode with synthetic data requiring no account/key).

#### 1.4 How a Legal plugin mirrors Finance
| Finance | Legal analogue |
|---|---|
| `finance.db` (SQLite) | `legal.db` per install + one folder per matter (files stay as files) |
| Plaid sync (read, approval to refresh) | CourtListener/PACER sync, DMS sync (read, approval to file/send) |
| 16 `finance_*` tools | ~16 `legal_*` tools (§ Recommended Architecture) |
| Budgets/rules/categories | Playbooks/clause libraries/deadline rules |
| Net-worth dashboard | Matter dashboard: deadlines, docs, citations-needing-verification |
| Writes ask first; unattended = no writes | **Filing, sending, e-signing, billing = always ask first; unattended = never** |
| Demo with synthetic data | Demo matter with synthetic (fictional) client — essential for screenshots/tests without privilege risk |
| `finance doctor` | `legal doctor` — checks Ollama, editors, APIs, keychain, *and warns if a STANDARD-tier model is set on a privileged matter* |

### 2. Legal AI Competitive Landscape 2024–2026

**Market shape:** Only 4 of 35 products publish a list price; legal AI seats run *“roughly $150–$1,200 a seat a month. Seat minimums, not list price, usually decide the bill”* [https://www.trylegal.ai/upgraded.html]. Custom build on Claude/GPT APIs was costed *cheaper over 3 years* than Harvey/Legora/CoCounsel/Lexis in one calculator [https://www.layer3labs.io/tools/legal-ai-cost-calculator] — the economic opening for open-source local.

| Product | What it does | Pricing (basis) | Privacy / training | Integrations / gap for hermes-legal |
|---|---|---|---|---|
| **Harvey** | Firm-wide agents, Vault (multi-doc), Knowledge (research), Word add-in, Agent Builder in Word (Sep 2026) | Quote-only; reported $100–200/seat/mo at scale, $800–1,200 small pilots, firm access from ~$50k/yr, median ~$175k/yr; 20–25 seat min reported; $11B valuation Mar 2026 [layer3labs; trylegal; theairankings] | No training on inputs/outputs/docs unless customer asks; model providers must offer ZDR + no-training; Azure-hosted, SOC 2 II, ISO 27001/27701/42001 [https://www.prometheusconsulting.ai/guide/harvey-ai-review] | Lexis/Wolters/EDGAR/EUR-Lex/DMS connectors. **Gap:** enterprise-only, data leaves firm, no local, no Linux desktop, no solo price. |
| **CoCounsel (Thomson Reuters)** | Research/drafting/review/depo prep grounded in Westlaw + Practical Law; CoCounsel Legal (Aug 2025) + Deep Research | Reported ~$225 Core, ~$550 with Westlaw; configurator solo $104–$639/user/mo depending on bundle [https://spellbook.com/briefs/cocounsel-alternatives]; [layer3labs] | Enterprise terms, no-training (per vendor) | Began as **Casetext** (founded 2013, CoCounsel GPT-4 Mar 2023), acquired **$650M cash, closed 17 Aug 2023**, standalone Casetext retired 1 Apr 2025 [https://www.theaicemetery.com/casetext/]. **Gap:** bundle lock-in — value requires Westlaw subscription. |
| **Lexis+ AI → Lexis+ with Protégé (Feb 2026)** | Conversational research grounded in Lexis corpus, Shepard's citator, Protégé Work agentic multi-step (due diligence, playbook review) | Reported $125–275 add-on *on top of* Lexis+; combined ~$175–300/user/mo [layer3labs; aimadefor] | Enterprise, grounded + Shepard's verification | **Gap:** same bundle problem; no local/offline; Shepard's/KeyCite are the moat hermes-legal *cannot* replicate — must integrate/verify via open citators + CourtListener citation graph instead and say so honestly. |
| **Westlaw AI / Westlaw Advantage** | See CoCounsel — now the content layer, KeyCite | Base ~$100–200 + AI add-on (reported) | As above | No public API for third-party AI (see §5). |
| **Spellbook** | Contract drafting/redlining **inside Word**, clause generation, market benchmarking (2,000+ standards) | Quote-only; reported $99–350/user/mo [https://rankite.com/blog/best-ai-contract-review-software] | Markets ZDR with OpenAI+Anthropic [docuchat survey] | Most accessible incumbent for small firms. **Gap:** Word-only (no Linux), cloud, per-seat. |
| **Robin AI** | Was: contract review + CLM | Was ~$300+/seat | — | **Defunct as standalone** (see Exec Summary). Lesson: standalone contract-AI economics are brutal; don't VC-price hermes-legal. |
| **LegalOn** | In-house review vs attorney-drafted playbooks, Word/web | Reported $3,000–8,000/yr (team) | Cloud | Playbooks are the feature to copy *as open templates*. |
| **Luminance** | Portfolio contract review/diligence, anomaly detection; on-prem offered for residency deals | Quote; enterprise “hundreds of thousands/yr” (unverified) [docuchat] | On-prem option distinguishes it | **Gap:** enterprise sales cycle only. |
| **Kira (Litera)** | M&A due-diligence clause extraction at scale | Quote; reported $30k–100k+/yr | Cloud/enterprise | Now inside Litera suite with drafting/proofreading. |
| **Relativity / RelativityOne + aiR** | eDiscovery review, aiR for Review/Privilege/Case Strategy (bundled into RelativityOne early 2026) | Per-GB; UK G-Cloud list £7/GB/mo hosting reported | Cloud gen-AI only going forward | Server sunset 2028 (above). **Gap:** no small-matter, local, cheap review tool. |
| **Everlaw** | Cloud eDiscovery, depo + review/writing assistants (Oct–Nov 2025, folded into base) | Per-GB, quote; analyst ~$18–35/GB/mo | Cloud only, FedRAMP | Same gap as Relativity, friendlier UX. |
| **DISCO** | eDiscovery + case management, Cecilia AI | Per-GB, quote | Cloud | — |
| **Clio Duo → Clio Manage AI / Clio Work (Vincent AI)** | Practice mgmt + AI: deadline extraction, invoice gen, matter summaries, drafting; Clio Work = vLex 1B-doc corpus + agentic (Apr 2026) | Manage **Published $49 EasyStart / $89 Essentials / $119 Advanced / $149 Complete** per user/mo annual; Draft +$49, Work reported $199–399 [https://mukuldewangan.com/clio-analysis.html; trylegal] | Cloud SaaS, SOC 2 II | 250+ integrations, public REST API — **the #1 integration target**. Gap: full AI value requires migrating the firm *into* Clio. |
| **PracticePanther** | Practice mgmt, intake, billing for small firms | ~$49–89/user/mo reported | Cloud | Basic API + Zapier only (§5). |
| **Smokeball** | Practice mgmt + auto time capture + document assembly | Quote/bundled | Cloud/desktop hybrid | Public API appears limited [https://supergood.ai/blog/why-integrations-are-the-backbone-of-legal-crm-value-and-what-it-means-for-your-firm/]. |
| **Filevine** | Litigation/PI case mgmt, Lead Docket intake, Vinesign | Quote | Cloud | Documented API, ecosystem-oriented access. |
| **NetDocuments + ndAI** | Cloud DMS, matter profiling, ndAI drafting/research apps | Reported ~$50–65/user/mo, 3–5 seat min | Cloud DMS | API/partner-gated. |
| **iManage Work** | Enterprise DMS/knowledge/email mgmt for large firms | Quote only (~$35–150+ estimates too wide to rely on) | Cloud/on-prem legacy | Partner API. The large-firm DMS duopoly (with NetDocuments) — integrate, don't replace. |
| **DocuSign** | eSignature + IAM/CLM | **Published:** eSignature $30–45/user/mo; API Starter $50/mo annual (40 env/mo) [trylegal; §5] | Cloud | Public API — P1. Open alternative: Documenso/DocuSeal (AGPL). |
| **Ironclad** | Enterprise CLM, workflow, Salesforce | Platform contracts reported $30k–150k+ | Cloud | API exists, enterprise-gated. |
| **Juro** | Self-serve CLM for in-house, browser-native editor | Quote/per-seat | Cloud | Browser editor model is instructive, not DOCX-native. |
| **LawPay** | Legal payments, trust/IOLTA-compliant processing | % + per-seat via Clio etc. | Cloud | API via partner; Stripe is the open-dev path. |
| **CourtListener / RECAP (Free Law Project)** | Free opinions/dockets/judges, RECAP PACER archive | **Free** (API free tier, membership for higher limits) | Public data | **P0.** See §8. |
| **Fastcase → vLex** | Research library; Fastcase merged into vLex, now powers Clio Work/Vincent | Bundled | Cloud | No open API. |
| **Paxton** | Standalone research/drafting, all 50 states, single seat, month-to-month | **Published $499/user/mo or $2,999/yr** [https://www.nexlaw.ai/compare/] | Cloud | Proves solo willingness to pay — and the price ceiling hermes-legal undercuts at $0. |
| **Alexi** | Litigation memos/research for firms | Reported tiers ~$499–949/mo (2023 reporting, stale — verify) | Cloud | — |
| **BriefCatch / WordRake / PerfectIt / Litera (Drafting)** | Word add-ins: legal writing editing, plain-English, consistency/proofreading, compare/clean | Per-seat, mostly quote/small published | Mostly local-ish Word add-ins (varies) | **Closest philosophical cousins:** narrow, Word-native, lawyer-trusted. hermes-legal should ship BriefCatch-like *deterministic* checks (no LLM needed) in v1 — cheap trust-builder. |
| **Anthropic Claude for Legal (May 2026) + Microsoft Legal Agent in Word (Apr 2026)** | Lab-direct: 20+ MCP connectors (DocuSign, Ironclad, iManage, NetDocuments, Everlaw, Relativity, CoCounsel…), 12 open-source practice-area plugins; MS Legal Agent = playbook review + tracked-change redlines in Word | Claude legal SKU: no disclosed price; MS: M365 Copilot / E7 $99/user/mo [iqdoc] | Per lab terms (§6) | **Strategic threat + opportunity:** the labs are giving away connectors/plugins. hermes-legal should *consume* MCP connectors and agentskills.io skills rather than rebuilding them, and differentiate on local/desktop/files. CourtListener is a free Justice Partner connector in Claude's program [iqdoc]. |

**What solo / small-firm / pro-se / legal-aid users lack (synthesis):**
- Anything priced for 1–5 lawyers without a 10–25 seat minimum, a Westlaw/Lexis bundle, or a sales call. Paxton at $499/mo and Clearbrief at $300/mo solo are the *floor* for standalone tools [docuchat survey].
- Linux support (Word add-ins assume Windows/Mac Word), offline work (court/country connectivity), and tools for *their own files* rather than a vendor cloud DMS.
- Pro-se / legal-aid: guided document assembly (Docassemble, §8), deadline calculators, plain-language explanations — with UPL-safe guardrails. Charlotin data: of 2,241 hallucination decisions by Oct 2026, **1,292 involved self-represented people vs 886 lawyers** [https://www.brillnexsystems.com/blogs/ai-for-law-firms] — pro-se users are the highest-risk, least-served group.
- Trust: a tool that *shows* its sources page-and-span and refuses to invent a citation is missing at free/open tier.

### 3. Legal Workflows That Matter — Ranked for a Desktop Assistant

Ranking criteria: frequency × time saved × local/desktop advantage × feasibility without proprietary data.

| Rank | Workflow | v1? | Notes |
|---|---|---|---|
| 1 | **Document drafting/editing in DOCX/PDF** (open folder → edit → save as file) | **P0** | The product. Templates, styles, numbering, TOC, mail-merge from matter data. |
| 2 | **Redlining / track changes / document compare** | **P0** | Must emit real `w:ins/w:del`. Compare = deterministic diff first, LLM explains second. |
| 3 | **Contract review vs playbook** | **P0** | Playbook = YAML/Markdown rules + clause library, checked clause-by-clause with rationale comments (mirrors MS Legal Agent / LegalOn). |
| 4 | **Citation checking + Bluebook formatting** | **P0** | eyecite extraction → CourtListener/CAP lookup → exists? supports proposition? still good law? (flag: no Shepard's/KeyCite — label as *existence + history check, not citator*). Bluebook (22nd ed. 2025) formatting is deterministic code, not LLM. |
| 5 | **Matter/case workspace + local research (RAG over matter docs)** | **P0** | Cited Q&A with page/span citations; chronology generation (Vals task where CoCounsel scored 78.0 vs lawyer 80.2 [spellbook alternatives]). |
| 6 | **Deadlines / docketing / calendaring rules** | **P0-lite** | Extract dates from PDFs/orders, compute under court rules (FRCP etc. as data files), export .ics / sync calendar. *Never* auto-file. Liability-sensitive: show rule + computation. |
| 7 | **Client intake + document automation / clause libraries** | P1 | Docassemble-style interviews → DOCX/PDF; clause library with fallbacks. |
| 8 | **Legal research (case law/statutes/regs)** | P1 | Via CourtListener, govinfo, eCFR, CAP APIs (§8) — not a scraped proprietary corpus. Deep-research agent over *retrieved* sources only. |
| 9 | **Transcription / deposition prep** | P1 | Local Whisper (whisper.cpp/faster-whisper) — a privacy showcase: audio never leaves device. Summaries, depo outlines, transcript search. |
| 10 | **E-discovery / document review (small matters)** | P1-lite | Ingest, OCR, dedupe, Bates, privilege-flagging, TAR-lite ranking for matters < ~50k docs. Explicitly not Relativity-scale. |
| 11 | **Time / billing** | P1 via integration | Build timers + export, sync to Clio/LawPay/Stripe/QuickBooks — don't rebuild trust accounting in v1 (IOLTA errors are malpractice-grade). |
| 12 | **E-signature** | P1 via integration | DocuSign API or local Documenso/DocuSeal. |
| 13 | **E-filing (PACER / state)** | P2, assist-only | Prepare filing bundles, check local rules/format, hand off to official portal. Direct filing APIs mostly don't exist for third parties; PACER is per-page fee, RECAP-first lookup saves money (§8). |
| 14 | **Due diligence** | P2 | Kira-style extraction as a batch skill over a folder — same tech as (10), larger scale. |
| 15 | **Legal hold / privilege log** | P2 | Hold notices, privilege log generation from review codes. Privilege *determinations* stay human. |

Cross-cutting for every workflow: **privilege/confidentiality tagging per matter, ethical-wall flag, audit log (who/what model saw what, when), legal-hold preservation, and a verification checklist before anything leaves the app.**

### 4. Document Editing Stack

#### 4.1 The central fact
DOCX = OOXML zip of XML. Track changes = `<w:ins>` / `<w:del>` elements with author/date; comments = separate part; numbering/styles/headers/footers are separate parts that naive converters drop. *“With Tiptap, header and footer content does not consistently translate on import… track changes stay JSON-based rather than becoming OOXML-compatible revisions”* and DOCX/track-changes/comments are **paid extensions** on an MIT core [https://pdfTron.com/capabilities/docx-editor/comparison/tiptap]. Same structural warning applies to Lexical (Meta, MIT, minimal core, no DOCX model), Slate (custom model), and ProseMirror directly. CKEditor 5 has genuine Track Changes/Comments/Revision History + Word/PDF export, but as commercial premium features [search result, sourceforge/ckeditor description in § search].

#### 4.2 Comparison
| Editor | License | DOCX fidelity | Track changes | Desktop embed | Verdict |
|---|---|---|---|---|---|
| **ONLYOFFICE Docs / Desktop Editors** | AGPL-3.0 (community conn. limit 20 for server; desktop free) | **Excellent — OOXML is native format**, round-trips with minimal loss [https://massivegrid.com/blog/nextcloud-office-replacing-google-docs-sheets/] | Yes, native | Desktop app exists (Win/Linux); Docs server via Docker/WOPI; plugin API + AI-plugin architecture (connect Ollama/vLLM/OpenAI etc.) | **P0 choice for in-app editing.** AGPL implications must be accepted or commercial licence bought. |
| **LibreOffice Writer** | MPL-2.0 | Very good; ODF-native, converts to OOXML (occasional shifts in complex docs) [massivegrid] | Yes (can drop odd comment in shared DOCX per reviews) | Native Win/Linux, headless `soffice` for conversion, UNO API | **P0 for conversion/rendering + fallback editor** (“Open in LibreOffice/Word”). Best DOCX→PDF fidelity available open-source. |
| **Collabora Online / CODE** | MPL-2.0 (LibreOffice core) | As LibreOffice, via WOPI in browser | Yes | Server (Docker) + WebView | P1 if multi-user co-editing is needed; heavy for a solo desktop v1. |
| **TipTap / ProseMirror** | MIT core, paid DOCX/track-changes ext. | Secondary/export only | JSON, not `w:ins/w:del` | Excellent in Electron/Tauri | Use for **notes/memos/markdown surfaces inside the app**, never as the DOCX of record. |
| **Lexical / Slate** | MIT | None native | Build-your-own | Excellent | Same as above; Lexical good for the Ask/chat composer. |
| **CKEditor 5 premium** | Commercial | Good paste-from-Word, export | Yes (paid) | Good | Fallback if ONLYOFFICE AGPL is unacceptable and budget exists. |
| **Apryse (PDFTron) DOCX Editor** | Commercial | Edits OOXML directly, native revisions | Yes | JS SDK | Commercial benchmark for fidelity; not open. |

#### 4.3 PDF + OCR + utilities
- **Render/extract: PDF.js** (Mozilla, Apache-2.0) — *“can render and extract but not author”*; **author/edit: pdf-lib** (MIT) — *“structural edits: pages, annotations, form fields… cannot render”* — the standard pairing is PDF.js → canvas/extract, pdf-lib → write [https://rominur.com/EditPDF_Paper.html]. Nutrient (ex-PSPDFKit) is the commercial high-end alternative.
- **True redaction warning:** drawing a black box ≠ redaction. Pages must be rebuilt/rasterised or content streams removed — filings have been de-redacted repeatedly [rominur]. hermes-legal redaction must remove underlying text and warn + verify by re-extracting text.
- **Bates stamping, page numbers, watermarks:** trivial with pdf-lib (draw text per page, e.g. `DOC-000001`) [https://github.com/sukumarc/openpdf/blob/HEAD/README.md].
- **OCR: Tesseract** (Apache-2.0) native for desktop speed; tesseract.js (WASM) is *“slower than native… 300-page scan 5+ min”* in browser [https://dev.to/magictoolshub/how-i-built-a-112-tool-pdf-toolkit-that-never-uploads-your-files-g4j]. Bundle native Tesseract + poppler (`pdftotext/pdfimages`) as sidecars; offer PaddleOCR/EasyOCR as optional Python plugins later.
- **DOCX programmatic layer:** python-docx for styles/tables/templates + **direct OOXML patching** (zip + lxml) for redlines/comments/bookmarks — this, not the visual editor, is where the AI writes. Every AI edit = a tracked change attributed to “hermes-legal (AI — unverified)” until a human accepts it.
- **Templates/mail merge:** docxtpl (Jinja in DOCX) or docx-mailmerge from matter JSON; templates stored as ordinary .docx in the matter/template folder — lawyers can edit them in Word.

**Recommended stack (Linux+Windows):** Files on disk as source of truth → ONLYOFFICE Desktop/Docs (local) for visual DOCX editing + LibreOffice headless for PDF conversion/fidelity check → TipTap/Lexical only for internal notes → PDF.js + pdf-lib for PDF work → native Tesseract for OCR → python-docx/OOXML patcher for AI redlines. Ship a “fidelity test corpus” (numbering, footnotes, tables, tracked changes, comments) in CI on both OSes.

### 5. Legal Integrations & APIs / Connections

Feasibility key: **Public** = self-serve developer signup; **Partner** = approval/partner program; **Gated** = customer/enterprise contract needed; **None** = no third-party AI API.

| Integration | Public API? | Auth | Feasibility for OSS desktop |
|---|---|---|---|
| **CourtListener / RECAP** | **Yes, REST v4** | Token (free account); free tier tight — MCP design notes 5/min, 50/hr, 125/day published, higher with membership/commercial [https://github.com/cyanheads/courtlistener-mcp-server/blob/HEAD/docs/design.md] | **P0.** BYO-token, aggressive local caching, bulk data for offline. |
| **PACER** | Yes (CM/ECF + PACER APIs, per-page fees $0.10, $3 doc cap, quarterly fee waiver <$30) | PACER account | P1, RECAP-first (check free archive before buying), cost estimator before any pull. |
| **govinfo / eCFR / Congress.gov / Regulations.gov** | Yes, public APIs | API key (api.data.gov for some) | **P0** — free, authoritative primary law. |
| **UniCourt / Trellis / Docket Alarm** | Yes, commercial | API key / contract | P2, BYO-key plugins. |
| **State e-filing (Tyler Odyssey eFileCA/TX etc., File & ServeXpress)** | Mostly **no public third-party API**; vendor EFSP certification required | EFSP | P2 assist-only (bundle prep), do not promise filing. |
| **Clio (Manage/Grow/Draft)** | **Yes — mature public REST API, 200–280 app ecosystem** [https://supergood.ai/blog/why-integrations-are-the-backbone-of-legal-crm-value-and-what-it-means-for-your-firm/] | OAuth 2.0 | **P0/P1 — first practice-mgmt integration.** Read matters/contacts/calendar/billing; writes approval-gated. |
| **PracticePanther** | Basic API + Zapier | API key/OAuth (approved access) [https://pearsign.com/integrations] | P1, expect shallower coverage. |
| **Smokeball** | Limited public documentation | Partner/production permission | P2, partner-gated — design connector interface, ship when access granted. |
| **Filevine** | Documented API, ecosystem-oriented | Partner OAuth | P1/P2. |
| **NetDocuments** | Yes, partner/customer-gated (ndAPI) | OAuth 2.0 | P1 for firms on NetDocs; per-user BYO credentials. |
| **iManage Work** | Yes (Work API / SDK), partner-gated | OAuth 2.0 | P1/P2, enterprise users only. |
| **SharePoint / OneDrive / M365 / Outlook / Word add-ins** | **Yes — Microsoft Graph** | OAuth 2.0 / MSAL | **P0.** Files, mail, calendar in one connector. Word add-in (Office.js) is a *separate* later product — desktop-first v1 reads/writes the same files via Graph/local sync folder. |
| **Google Drive/Docs/Gmail/Calendar** | **Yes — Workspace APIs** | OAuth 2.0 | **P0.** Note Docs→DOCX export fidelity loss; prefer Drive file sync. |
| **Dropbox / Box** | Yes, public | OAuth 2.0 | P1 — simple file connectors, reuse local-folder logic on synced folders for free. |
| **DocuSign eSignature** | **Yes** — REST v2.1, free sandbox, OAuth 2.0 (auth-code+PKCE or JWT grant), Go-Live review, 3,000 req/hr/account [https://www.anchorterminal.com/tools/docusign] | OAuth/JWT | **P1.** Also ship **Documenso/DocuSeal (AGPL, self-hostable)** as the local/open option. |
| **Adobe Sign** | Yes | OAuth (integration keys Enterprise-only) | P2. |
| **Ironclad / Juro** | Yes, enterprise-gated | API key/OAuth | P2 BYO-key. |
| **Westlaw / Lexis** | **No public AI/research API for third-party apps** (Thomson Reuters/Lexis expose APIs to enterprise/partner products e.g. CoCounsel/Lexis Connect, not self-serve OSS) | Contract | **Do not build on these.** Link-out + bring-your-own-export ingestion only. This restriction is itself a selling point for open corpora. |
| **Email (IMAP/SMTP, Gmail, Outlook)** | Yes | OAuth (Gmail/Graph) / app passwords (IMAP) | **P0** read + draft; **sending always approval-gated.** |
| **Calendars / deadline calc** | Graph/Google/CalDAV + .ics | OAuth | **P0.** Deadline *rules* ship as versioned data with court source + “verify against local rules” warning. |
| **LawPay / Stripe / QuickBooks** | LawPay: partner API; **Stripe: public**; QuickBooks Online: public Intuit API | OAuth/API key | P1: Stripe + QBO first (self-serve), LawPay via partner/Clio. Never handle card data locally. |
| **Zoom / Teams transcription** | Yes (cloud recording/transcript APIs) + local files | OAuth | P1: local-file transcription (Whisper) first — no API needed; cloud connectors BYO. |
| **Notion / Slack** | Yes, public | OAuth/API key | P2 — notifications/notes sync only, never privileged content by default (warn). |
| **Anthropic MCP connectors for legal** | 20+ connectors exist in Claude for Legal (DocuSign, Ironclad, iManage, NetDocuments, Everlaw…) [iqdoc] | Per connector | **Consume via MCP** where licensing allows instead of reimplementing — hermes-legal is an MCP client like Hermes. |

**Connector architecture rule (from hermes-finance):** every connector = `doctor` check + BYO credentials in OS keychain + read-only default + pending-action writes + per-matter enable/disable + a data-flow label (what leaves device, to whom).

### 6. Privacy-First & Local Models — The Core Differentiator

#### 6.1 Tier table the app must show users (ship this UI verbatim in spirit)

| Tier | What leaves the device | Training on your data | Retention | Consent posture under Opinion 512 |
|---|---|---|---|---|
| **LOCAL-ONLY** | **Nothing.** Model, embeddings, OCR, transcription all on-device; network can be off. | Impossible (no recipient) | Only your files/logs, under your control | Simplest: no disclosure to a third-party self-learning tool. Still log model + version for competence (Rule 1.1). **Default for all privileged matters.** |
| **ZERO-RETENTION (ZDR)** | Prompts + retrieved chunks you approve, over TLS, to named provider/region | Contractually **no** | Provider contractually retains **none / abuse-logs excluded or minimised** — varies, see 6.3; safety-classifier results may still be kept (Anthropic) | Document provider + terms + date checked in matter log; informed consent recommended; verify current terms — they change. |
| **STANDARD (no-training API)** | Same as ZDR | **No** on paid APIs (OpenAI since 1 Mar 2023, Anthropic commercial, Vertex/Bedrock) | Typically up to **30 days** abuse/safety logs (OpenAI, Anthropic default; Anthropic API log retention reported dropping to 7 days Sep 2025 — verify) | Informed consent if tool is “self-learning” in 512's sense; read terms per 512. |
| **⛔ CONSUMER CHAT (Free/Plus/Pro personal accounts)** | Everything pasted | **May train by default / opt-out or opt-in depending on provider+date** (OpenAI consumer may train unless opt-out; Anthropic consumer training choice introduced Aug 2025, up to 5-yr de-identified retention if allowed) [https://www.roguedigital.ai/insights/where-your-data-goes-chatgpt-claude] | 30 days if training off, longer if on | **Block in hermes-legal.** Feb 2026 *Heppner* (S.D.N.Y.): consumer Claude chats held neither privileged nor work product, partly because consumer privacy policy allowed third-party disclosure [https://jazz.security/dlp-explained/dlp-basics/can-lawyers-put-client-information-into-chatgpt-or-claude/]. Personal-account use is the #1 real-world leak (34% of firm professionals use unauthorised AI tools — Thomson Reuters Future of Professionals 2026, cited there). |

UI requirements: tier badge on every Ask/send action, per-matter ceiling (a matter set to LOCAL-ONLY *cannot* call cloud even if the user tries), a pre-send preview listing exactly which chunks/files go out, and an exportable matter AI-log.

#### 6.2 Fully local runtimes
| Runtime | License / notes |
|---|---|
| **Ollama** | MIT, CLI + local OpenAI-compatible API, Win/Linux/Mac, one-command pulls, bundles llama.cpp; Ollama *Cloud* is a separate ZDR-claimed service — keep distinct in UI [https://www.exploreai.directory/collections/privacy-first-ai-tools] |
| **LM Studio** | Free for home+work since July 2025, **closed source**, GUI model browser + local server on :1234, shows fit vs RAM [exploreai; https://kompanion.online/en/local-llm-macbook-2026-lm-studio-ollama-jan/] |
| **llama.cpp** | MIT C/C++, GGUF, the engine under most local tools; best for bundling as a sidecar so users need install nothing else |
| **Jan** | Apache-2.0, open GUI, auditable — good recommendation for compliance-sensitive users [kompanion] |
| **GPT4All** | MIT app + models vary; easy onboarding, weaker tool-calling — P2 support via its OpenAI-compatible server |

**Bundling recommendation:** hermes-legal ships with **llama.cpp/Ollama detection + guided install**, not with weights. Default suggested downloads by hardware (6.4). Embeddings local too: `nomic-embed-text` / `bge-small/m3` / `mxbai` via same runtime (ONNX sentence-transformers fallback) — a cloud embedding call leaks as much as a chat call.

#### 6.3 Zero-retention / no-training cloud (verify terms at integration time — snapshot Oct–Nov 2026)
- **Anthropic (Claude API / Team / Enterprise):** Commercial terms bar training on customer content; API default retention ~30 days (7-day log reporting varies by source — flag discrepancy), **ZDR available subject to approval**, does not cover Team/Enterprise *product interfaces* the same way as API, safety-classifier results retained even under ZDR [https://dev.to/ostrafile/we-dont-train-on-your-data-is-not-zero-retention-1kk6; https://www.januscompliance.co.uk/blog/gdpr-compliant-llm-api-openai-vs-anthropic-vs-google-2026]. Strongest general-model drafting quality per legal rankings; Claude business tiers *“never used for model training”* [theairankings].
- **OpenAI API:** No training since 1 Mar 2023; abuse logs up to 30 days; **ZDR + Modified Abuse Monitoring by prior approval for eligible endpoints**; EU/UK residency for eligible customers [roguedigital; januscompliance].
- **Azure OpenAI:** No training; abuse monitoring opted-out/limited for approved customers; data stays in tenant/region options; ZDR-equivalent via Limited Access application [https://www.developersdigest.tech/blog/which-ai-apis-train-on-your-data].
- **AWS Bedrock:** No training; model-dependent retention, **self-serve zero-retention mode** reported; in-region processing — good default ZDR recommendation alongside Azure.
- **Google Vertex AI:** No training without permission, EU multi-region options, ZDR subject to conditions; **contrast Google AI Studio / unpaid Gemini API, which differs on training/retention (55-day abuse logs on paid Developer API)** — hermes-legal must only offer Vertex, never AI Studio free tier, for client work [januscompliance].
- **OpenRouter:** Itself does not store prompts by default; **per-provider variance is the trap** — its provider table flags Trains / Retention / ZDR per endpoint (Together, Bedrock, Azure, Fireworks, Groq listed Zero retention; OpenAI listed Retains prompts) [https://openrouter.ai/providers]. hermes-legal must enforce **ZDR-only routing + provider allowlist** in code, not just link the settings page.
- **Together / Fireworks / Groq:** Together: no training, but **stored by default — admin must switch storage off** to get ZDR (self-serve). Fireworks: not retained by default for open models (Response API `store=True` exception). Groq: no training by contract, **not retained by default, self-serve ZDR** [developersdigest; https://meetily.ai/blog/which-ai-providers-train-on-your-data/]. Good for fast open-model inference (Qwen/Llama) as a ZDR tier.
- **Venice / Proton Lumo / Brave etc.:** Consumer privacy-chat products with no-training / no-log claims but **consumer terms, no DPA/BAA, no API suitable for firm integration** — mention in docs as personal-use only, do not integrate for client matters in v1. (No primary terms verified in this run — see Could Not Verify.)
- **Confidential computing / TEE:** Phala and similar GPU-TEE inference appear in OpenRouter's zero-retention provider set; Apple Private Cloud Compute and Azure Confidential Computing / NVIDIA H100/H200 CC modes exist as platforms. **Assessment: promising, not yet a v1 dependency** — no major legal vendor was found offering TEE inference under a law-firm DPA in this run. Design the provider interface so a TEE endpoint (attestation URL + verification) can be added as just another ZDR provider.

#### 6.4 Best local LLMs for legal drafting/reasoning (2025–2026 snapshot)
Legal work = long documents, precise language, instruction-following, *low confabulation tolerance*. No local model is citation-safe without verification (§6.5). Sizes at Q4_K_M (standard Ollama quant, ~0.5–0.6 GB/B params + KV headroom):

| Hardware | Run this | Legal use |
|---|---|---|
| 8 GB RAM, no GPU | Qwen3 4B / Gemma 3–4 E4B / Llama 3.2 3B (~3–5 GB) | Summaries, classification, intake triage only. Warn: weak drafting. |
| 16 GB RAM / 8 GB VRAM | **Qwen3 8B / Llama 3.1–3.3 8B (~5–6.8 GB)**, Mistral 7B/Nemo | Default minimum. ~50–80 tok/s on RTX 4060-class [https://www.promptquorum.com/local-llms/local-llm-hardware-guide?trk=article-ssr-frontend-pulse_little-text-block] |
| 16–24 GB / 12 GB VRAM | Qwen3 14B / Phi-4 14B (~9–10 GB), Gemma 12B | Noticeably better drafting/reasoning; sweet spot for laptops. |
| 32 GB RAM / 16 GB VRAM | Mistral Small 24B (~14–16 GB), Qwen3 30B-A3B MoE (tight) | Strong contract review first-pass. |
| 24 GB VRAM (3090/4090/5090) / 32–36 GB unified | **Qwen3 32B / Qwen3.6 27B (Apache-2.0, ~18–21 GB), DeepSeek-R1 distill 32B, Gemma 27–31B** | **Recommended “quality local” tier** — closest to usable associate-level first drafts [https://localaimaster.com/blog/ai-hardware-requirements-2025-complete-guide; https://llmhardware.io/vram-calculator] |
| 48 GB+ VRAM / 64–128 GB unified | Llama 3.3 70B (~40–44 GB Q4), Qwen 72B-class, gpt-oss-120b (96 GB) | Best local reasoning; Llama 4 Scout needs ~55–67 GB for all experts despite 17B active [llmhardware] |
| Long-context special | Llama 4 Scout (10M-token claim, MoE) / Qwen3 262K-context variants | Whole-deal-room ingestion — but context ≠ comprehension; chunk + cite anyway. |

Licences matter for redistribution: **Qwen (Apache-2.0 for most Qwen3), Mistral (Apache-2.0), DeepSeek (MIT/model licence), Gemma (Gemma terms, now Apache-2.0 for Gemma 4 per 2026 reporting — verify per release), Phi (MIT), Llama (Llama Community Licence — not OSI, 700M-user cap + AUP)**. hermes-legal should *download on user request* rather than bundle weights, sidestepping most licence friction, and display each model's licence in the picker. Sources: [https://aithinkerlab.com/best-local-llm-models-privacy-dev/; https://typilot.com/blog/how-much-ram-to-run-local-llm].

#### 6.5 Ethics, privilege, hallucination — non-negotiable guardrails
- **ABA Formal Opinion 512 (29 July 2024):** Rules **1.1** competence (understand capabilities/limitations, verify output independently), **1.6** confidentiality + 1.6(c) reasonable efforts (informed consent for self-learning tools; boilerplate insufficient), **1.4** communication, **1.5** fees (don't bill learning time / AI-inflated time), **5.1/5.3** supervision of nonlawyers *and tools/vendors*, **3.3** candour (never submit unverified citations) [promise.legal; https://www.enclaveservers.com/research/whitepapers/aba-opinion-512-client-confidentiality/]. State guidance: Florida Op. 24-1 (research retention/sharing/self-learning first), California Practical Guidance (judgment cannot be delegated), plus court-by-court AI disclosure/certification orders (e.g. D. Haw.) — hermes-legal should ship a **jurisdiction/order tracker as data**, not hardcode.
- **Privilege waiver risk:** disclosure to a third party without confidentiality obligations can waive privilege/work-product; *Heppner* (above) turned on consumer terms. Local-only + DPA/ZDR providers + matter AI-log are the mitigation story.
- **Hallucination evidence:** Stanford/Yale Magesh et al., *Hallucination-Free?* (2024, J. Empirical Legal Studies 2025): RAG legal tools (Lexis+ AI, Westlaw AI-Assisted Research, Ask Practical Law) hallucinated on **17–33%** of queries, GPT-4 43%; Dahl et al. found 58–88% on case-specific questions for general models [https://www.brillnexsystems.com/blogs/ai-for-law-firms]. Charlotin database: **1,783 filings** (July 2026 count) rising to **2,241 decisions** (29 Oct 2026) [theairankings; brillnex].
- **Mata v. Avianca, No. 22-cv-1461 (S.D.N.Y. 22 June 2023):** six invented opinions (Varghese, Martinez, etc.), lawyers asked ChatGPT if they were real and believed it; **$5,000 joint sanction** + letters to client and falsely-named judges; court: *“nothing inherently improper about using a reliable AI tool”* — the sanction was for standing by fakes. Followed by *Park v. Kim* (2d Cir. 2024) and many standing orders [brillnex; https://www.tuput.com/blog/ai-hallucination-explained-with-the-court-cases-where-lawyers-were-sanctioned-for-fake-citations/].
- **Product consequences (build these):** (1) No citation enters a document without a resolver check (eyecite → CourtListener/CAP) showing *exists / quote-verified / subsequent history unknown*; (2) “Verify all” checklist gate before export/print/file-prep; (3) AI text visually marked until accepted; (4) UPL disclaimer — tool for licensed professionals + legal information (not advice) mode for pro-se, no “AI lawyer” claims (FTC vs DoNotPay, $193k settlement 2024, is the cautionary tale); (5) conflicts/ethical-wall warning if a skill/memory would cross matters.

### 7. Desktop Architecture for Linux + Windows

| Dimension | Electron | Tauri 2 | Other |
|---|---|---|---|
| Bundle / RAM / start | 85–150 MB installer, 150–300 MB idle, 1–3 s [https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/] | 2.5–10 MB, 30–50 MB idle, <0.5–1 s; system WebView (WebView2 Win, WebKitGTK Linux) | Flutter desktop (good widgets, weak web-editor embed), .NET MAUI (Windows-strong, Linux weak), Qt/PySide (native, slower web AI UI) — all worse fits for ONLYOFFICE/web-editor + Hermes-ecosystem reuse |
| Rendering consistency | **Identical Chromium everywhere** — decisive for DOCX/PDF fidelity QA | Varies by OS WebView version; Linux WebKitGTK lags | — |
| Backend language | Node (Python sidecar still needed for Hermes-style plugins) | **Rust core** + any sidecar; capabilities/permission model is security-by-default | — |
| Hermes alignment | **Hermes Desktop itself is Electron** — shared code, plugin pages, updater patterns | Divergent; you'd maintain your own shell anyway as a standalone product | — |
| Auto-update | electron-updater, mature; Hermes ships in-app self-update | Tauri updater (signed bundles, smaller diffs ~2 MB in one benchmark [https://www.buildr.sh/posts/electron-is-a-tax]) | — |
| Windows signing | EV/OV code-signing cert + SmartScreen reputation; MSIX/Store + winget manifests supported (Hermes ships MSIX option) | Same cert requirement; NSIS/MSI WiX bundles built-in | Budget for a cert + Azure Trusted Signing / SignPath (OSS) from day 1 — unsigned legal software on Windows is a non-starter. |
| Linux packaging | AppImage/deb/rpm via electron-builder; Flatpak possible (Chromium sandbox friction) | **AppImage, deb, rpm, Flatpak** via Tauri bundler; smaller artefacts, WebKitGTK dependency must be declared | Ship **AppImage + .deb + Flatpak** (Flathub needs network-permission justification for Ollama/cloud — document it). |

**Recommendation:**
- **If hermes-legal lives inside Hermes Desktop:** ship as a Hermes plugin + dashboard app first (Python, like hermes-finance) — zero shell decision, instant distribution to existing Hermes users on all OSes.
- **If hermes-legal is a standalone desktop product (the mission's premise): Tauri 2 + React/TS frontend + Python sidecar** (the hermes-finance codebase pattern, managed with `uv`, communicating over localhost HTTP/MCP) **+ Rust only for OS integration** (file watching, keychain, single-instance, protocol handler `hermes-legal://`). Rationale: bundle/RAM on modest small-firm hardware, Rust capability sandbox for privileged files, and the Python ecosystem (eyecite, python-docx, Docassemble, Whisper) is where legal tooling lives — Electron would still need that sidecar, paying Chromium's cost for less security model. **Mitigation for WebView variance:** all document *rendering of record* happens in ONLYOFFICE/LibreOffice/PDF.js pinned versions, not in raw WebView layout; add a visual-regression corpus per OS.
- **File/folder opening (P0 UX):** OS file associations for `.docx/.pdf/.hlegal-matter`, drag-drop, “Open Folder as Matter”, recent matters, deep-link from Clio/Graph, watch folder for changes (with conflict copies, never silent overwrite). Files remain *the user's files in the user's folders* — no import-into-proprietary-store requirement.
- **Credential storage:** OS-native only — Windows DPAPI/Credential Manager, Linux Secret Service (libsecret/gnome-keyring/KWallet) via Tauri keyring plugin / Python `keyring`; **never** plaintext `.env` for cloud tokens in the standalone app (hermes-finance's 0600 secrets file is acceptable for self-hosted server mode, not the desktop default). Encrypt `legal.db` option with SQLCipher.
- **Offline-first storage:** SQLite (WAL) for matters/metadata/audit + **SQLite FTS5 + sqlite-vec** for search: *“SQLite-vec when the app already stores data in SQLite and corpus is small enough for exact search… pre-v1, ANN in alpha”*; **LanceDB** if/when a matter exceeds ~100k chunks (built-in hybrid BM25+vector with RRF, Lance files on disk) [https://dev.to/ashish_mishra_26/whats-the-sqlite-equivalent-for-full-text-and-vector-search-38i8; https://www.agentic-pulse.dev/blog/2026-09-22-lancedb-vs-sqlite-vec-vs-chroma-benchmark-2026/]. Local embeddings: bge-small/e5-small ONNX (~100–200 MB, CPU <100 ms/chunk) or Ollama embeddings. Single-file DB = trivial backup/export/deletion (data-protection win).

### 8. Open-Source Legal Tech Precedents

| Project | What / licence | Use in hermes-legal |
|---|---|---|
| **CourtListener + RECAP (Free Law Project, nonprofit)** | Largest free US corpus: **9M+ opinions**, RECAP = *“largest open collection of federal court documents/dockets, hundreds of millions of docket entries”*, judges, oral arguments, financial disclosures; Django, open source; APIs + webhooks + bulk data, 100M+ API requests served [https://free.law/; https://github.com/vaquill-ai/awesome-legaltech/blob/HEAD/README.md] | P0 research/verification backend + MCP servers already exist (multiple CourtListener MCP implementations, BYO-key). |
| **Juriscraper (Free Law Project)** | Python library scraping **400+ courts** + PACER for opinions/oral arguments/dockets | Pattern/library if a jurisdiction needs a scraper; respect court ToS/robots. |
| **eyecite + reporters-db (Free Law Project)** | Extracts/resolves citations in any text using thousands of reporters; citation lookup API parses a block and verifies each cite | **P0 — embed directly (Python).** This is the anti-Mata engine. Pair with CourtListener Citation Lookup + CAP. |
| **Docassemble (Jonathan Pyle, GPL)** + Suffolk LIT Lab Document Assembly Line | Expert-system interviews → DOCX/PDF assembly, e-filing pilots, legal-aid standard | P1 interview engine (run as sidecar service) *or* reimplement its interview YAML pattern natively for desktop; don't fork GPL into an MIT core without licence planning. |
| **Caselaw Access Project (Harvard LIL, case.law)** | All published US decisions digitised from Harvard's collection; text CC0 / public domain; API with per-day case limits historically | Verification + quote-checking source; bulk for offline historical corpus. |
| **govinfo (GPO) / eCFR / OLRC US Code (USLM XML)** | Authenticated US Code, CFR, Federal Register, US Reports, court opinions collections; public domain (17 USC §105) | P0 primary-law sources with version history [http://openjurist.org/attributions]. |
| **Free Law Reporter / OpenJurist / Google Scholar case law** | Free case-law access points | Link-out fallbacks, not APIs to depend on. |
| **Lemma / others named in mission** | No verifiable project matching “Lemma” as a major open legal platform was found in this run (name is overloaded in math/AI) — see Could Not Verify. Vaquill awesome-legaltech lists newer entrants incl. a self-hostable legal AI agent fork of OpenCode with *“matter-scoped private workspaces, cited document Q&A, tracked-change DOCX redlines”* [awesome-legaltech] — the closest direct competitor/precedent; study it before building. | Track awesome-legaltech as the ecosystem registry. |
| **Open datasets summary** | CourtListener bulk (Public Domain Mark), CAP (CC0), govinfo/eCFR/US Code (public domain) — redistribution terms are clean, unlike scraped Westlaw/Lexis headnotes (copyrighted; *Thomson Reuters v. ROSS* (3d Cir.) training-data litigation makes this a live risk area [trylegal]) | Ship an *optional offline primary-law pack* (opinions + code + regs) — a feature no cloud vendor can match for air-gapped work. |

**Licence planning for the whole project:** Hermes Agent MIT + hermes-finance AGPL-3.0 + ONLYOFFICE AGPL-3.0 + Docassemble GPL + LibreOffice MPL-2.0 + Llama Community Licence cannot be casually combined into one binary. **Recommended:** hermes-legal core **AGPL-3.0** (consistent with finance + ONLYOFFICE, deters closed SaaS capture, allows commercial dual-licensing later) *or* Apache-2.0 core with AGPL components as separate processes/plugins. Decide with counsel *before* accepting contributions; add a CLA/DCO policy at repo creation. This report is not legal advice on licensing.

---

## Recommended v1 Feature Set + Plugin Architecture (mirroring hermes-finance)

### Architecture
```
hermes-legal/
  src/hermes_legal/
    tooldefs.py        # ~16 legal_* tools — single source of truth (CLI == MCP == agent)
    cli.py             # legal serve | doctor | matter | cite-check | deadline | sync …
    db.py              # SQLite (legal.db) + FTS5 + sqlite-vec
    matters/           # matter = folder + metadata; files stay as files
    docx/              # python-docx + OOXML patcher (w:ins/w:del, comments)
    pdf/               # PDF.js/pdf-lib bridge, Bates, true redaction, OCR (Tesseract)
    citations/         # eyecite + CourtListener/CAP/govinfo resolvers + Bluebook formatter
    providers/         # LOCAL / ZDR / STANDARD model router with per-matter ceiling
    connectors/        # clio/ graph/ google/ docusign/ courtlistener/ … (doctor + BYO key)
  hermes_plugin/       # thin Hermes adapter (plugin.yaml + __init__.py registering tools/skill/dashboard)
  skills/              # SKILL.md packs: litigation, contracts, intake, depo-prep… (agentskills.io)
  dashboard/           # Vanilla JS or React: Matters, Documents, Deadlines, Citations, Ask
  tests/ demo_matter/  # synthetic fictional matter — no real client data ever in repo
  docs/ (MkDocs)
```
**Tools (v1, read = R, approval-write = W):** `legal_matter_list/get (R)`, `legal_doc_read/search (R)`, `legal_doc_redline (W)`, `legal_doc_compare (R→W)`, `legal_cite_extract/check (R)`, `legal_cite_format (W)`, `legal_playbook_review (R)`, `legal_chronology (R)`, `legal_deadline_extract/calc (R)`, `legal_transcribe (local, R)`, `legal_intake_summary (R)`, `legal_time_log (W)`, `legal_sync_clio (W)`, `legal_efile_bundle (W, never files)`. Unattended/cron: reads + reports only, exactly like finance.

### v1 scope (ship this, nothing more)
1. Open folder/file → matter workspace; recent matters; Linux+Windows installers.
2. DOCX edit via ONLYOFFICE/LibreOffice handoff + in-app notes; PDF view/annotate/Bates/redact (true redaction).
3. AI Ask over the matter (local default) with page/span citations; AI redlines as tracked changes.
4. Playbook review + clause library (3 sample playbooks: NDA, MSA, employment).
5. Citation checker/formatter (eyecite + CourtListener) with Verify-All gate.
6. Deadline extraction + calendar export; demo matter; `legal doctor`; privacy tier UI + matter AI-log.
**Explicit non-goals v1:** filing, sending email/signatures without approval, trust accounting, large-scale eDiscovery, Westlaw/Lexis content, mobile, macOS (fast-follow).

## Recommended Model Privacy Catalog (default config)
- **Default:** LOCAL-ONLY — Qwen3 8B (16 GB machines) / Qwen3 32B or 27B (24 GB VRAM) / Llama 3.3 8B fallback; embeddings `bge`/`nomic` local; Whisper local.
- **Offered ZDR:** Anthropic API (ZDR agreement), OpenAI API (ZDR-approved), Azure OpenAI, AWS Bedrock, Groq/Fireworks (open models) — each labelled with terms-checked date.
- **Offered STANDARD:** Anthropic/OpenAI paid APIs without ZDR, OpenRouter **ZDR-only allowlist mode**.
- **Blocked:** consumer chat accounts, Google AI Studio free tier, any provider flagged Trains=Yes on OpenRouter, Together with storage left on.

## Recommended Integrations Priority List
- **P0:** Local folders, CourtListener/RECAP, govinfo/eCFR, Microsoft Graph, Google Workspace, IMAP, Calendar/.ics, Ollama/LM Studio.
- **P1:** Clio, DocuSign + Documenso, PACER (RECAP-first), Dropbox/Box, NetDocuments, Stripe/QuickBooks, Zoom/Teams files + local transcription, Filevine.
- **P2:** PracticePanther, Smokeball (partner), iManage, Ironclad/Juro, Adobe Sign, LawPay, UniCourt/Trellis, Notion/Slack, state e-filing bundle prep.

## Risks
| Risk | Severity | Mitigation |
|---|---|---|
| UPL / “AI lawyer” claims (esp. pro-se mode) | High | Information-not-advice UX, jurisdiction disclaimers, no outcome predictions, FTC/DoNotPay lesson. |
| Privilege waiver via cloud/consumer tools | High | LOCAL default, tier ceilings, Heppner warning, AI-log, DPA/ZDR only. |
| Hallucinated citations → sanctions (Mata) | High | Resolver-gated citations, Verify-All, AI-marked text, human sign-off. |
| Cross-matter leakage via memory/skills | High | Matter-scoped memory, no self-learning on client content by default. |
| Deadline miscalculation → malpractice | High | Show rule source + arithmetic, dual-entry for filing dates, “verify local rules”. |
| DOCX fidelity loss → altered meaning | Medium-High | OOXML-native editing, fidelity corpus, compare-before-save. |
| Licence contamination (AGPL/GPL/Llama) | Medium | Licence decision + process-isolated plugins (§8). |
| Key/credential theft on desktop | Medium | OS keychain only, SQLCipher option, signed updates. |

## Could not verify
- “Lemma” as a named open-source legal precedent (overloaded name; no authoritative repo found) and Venice/Proton Lumo/Brave primary API/DPA terms for firm use — left as personal-use mentions only.
- Exact current Anthropic API log-retention days (sources report both 30-day and 7-day figures for different surfaces/dates) and several quote-only prices (Harvey/Luminance/iManage) — all labelled Reported/Quote in tables; re-verify at procurement time.
- Whether “Hermes Desktop by ApeLabs” exists as a distinct product: sources show ApeLabs as a Hermes *plugin* author and NousResearch as the Desktop vendor; report follows the sources.
- No live in-browser check of vendor pricing pages was performed for quote-only products (they have none); Clio/DocuSign/Paxton published figures are via secondary sources citing vendor pages, flagged as such.

## Sources
Primary / verified live 2026-11-09:
- https://github.com/apelabs-dev/hermes-finance
- https://github.com/NousResearch/hermes-agent
- https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5
- https://github.com/NousResearch/hermes-agent/pull/91797
- https://github.com/NousResearch/hermes-agent/pull/97005
- https://github.com/NousResearch/hermes-agent/pull/140760

Index sources (read 2026-11-09):
- https://hermes-plugins.korchasa.dev/
- https://hermesatlas.com/ecosystem/
- https://github.com/moikapy/lich/blob/HEAD/wiki/raw/audits/2026-09-23-hermes-vs-lich.md
- https://www.ithub.directory/agent-frameworks/hermes-agent
- https://theairankings.com/best-ai-for-legal/
- https://www.layer3labs.io/tools/legal-ai-cost-calculator
- https://www.trylegal.ai/upgraded.html
- https://www.prometheusconsulting.ai/guide/harvey-ai-review
- https://spellbook.com/briefs/cocounsel-alternatives
- https://www.nexlaw.ai/compare/
- https://www.theaicemetery.com/casetext/
- https://mukuldewangan.com/clio-analysis.html
- https://github.com/janderswag/docuchat.app/blob/HEAD/docs/council/2026-07-07-reports/competitor-landscape.md
- https://www.iqdoc.app/blog/what-the-model-labs-built-for-legal
- https://rankite.com/blog/best-ai-contract-review-software
- https://blog.promise.legal/ai-ethics-compliance-law-firms-2026/
- https://www.enclaveservers.com/research/whitepapers/aba-opinion-512-client-confidentiality/
- https://jazz.security/dlp-explained/dlp-basics/can-lawyers-put-client-information-into-chatgpt-or-claude/
- https://www.brillnexsystems.com/blogs/ai-for-law-firms
- https://www.tuput.com/blog/ai-hallucination-explained-with-the-court-cases-where-lawyers-were-sanctioned-for-fake-citations/
- https://pdfTron.com/capabilities/docx-editor/comparison/tiptap
- https://massivegrid.com/blog/nextcloud-office-replacing-google-docs-sheets/
- https://rominur.com/EditPDF_Paper.html
- https://github.com/sukumarc/openpdf/blob/HEAD/README.md
- https://dev.to/magictoolshub/how-i-built-a-112-tool-pdf-toolkit-that-never-uploads-your-files-g4j
- https://supergood.ai/blog/why-integrations-are-the-backbone-of-legal-crm-value-and-what-it-means-for-your-firm/
- https://pearsign.com/integrations
- https://www.anchorterminal.com/tools/docusign
- https://www.exploreai.directory/collections/privacy-first-ai-tools
- https://kompanion.online/en/local-llm-macbook-2026-lm-studio-ollama-jan/
- https://www.roguedigital.ai/insights/where-your-data-goes-chatgpt-claude
- https://dev.to/ostrafile/we-dont-train-on-your-data-is-not-zero-retention-1kk6
- https://www.januscompliance.co.uk/blog/gdpr-compliant-llm-api-openai-vs-anthropic-vs-google-2026
- https://www.developersdigest.tech/blog/which-ai-apis-train-on-your-data
- https://meetily.ai/blog/which-ai-providers-train-on-your-data/
- https://openrouter.ai/providers
- https://localaimaster.com/blog/ai-hardware-requirements-2025-complete-guide
- https://llmhardware.io/vram-calculator
- https://www.promptquorum.com/local-llms/local-llm-hardware-guide?trk=article-ssr-frontend-pulse_little-text-block
- https://aithinkerlab.com/best-local-llm-models-privacy-dev/
- https://typilot.com/blog/how-much-ram-to-run-local-llm
- https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/
- https://www.buildr.sh/posts/electron-is-a-tax
- https://dev.to/ashish_mishra_26/whats-the-sqlite-equivalent-for-full-text-and-vector-search-38i8
- https://www.agentic-pulse.dev/blog/2026-09-22-lancedb-vs-sqlite-vec-vs-chroma-benchmark-2026/
- https://free.law/
- https://github.com/vaquill-ai/awesome-legaltech/blob/HEAD/README.md
- https://github.com/cyanheads/courtlistener-mcp-server/blob/HEAD/docs/design.md
- http://openjurist.org/attributions

*Note on page instructions: No page encountered instructed this research to do anything beyond the mission; nothing extraneous was followed.*
