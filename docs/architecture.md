# Architecture

One Python package (`src/hermes_legal/`), one SQLite file, ordinary folders for
matter files, and three ways in: the desktop/dashboard, the `legal` CLI, and the
MCP agent adapter. This mirrors hermes-finance deliberately. There is no Hermes
plugin; the desktop client is standalone.

- **Tools are defined once** in `tooldefs.py` (18 `legal_*` tools). The CLI read
  commands, the dashboard and the MCP server all call the same
  implementations, so they agree by construction.
- **A matter is a folder.** Files stay as files in the user's own folders; the
  database holds metadata, deadlines, citation checks and the AI log — never the
  only copy of a document.
- **The AI writes through the OOXML layer, not the editor.** A redline is built
  programmatically as real `w:ins` / `w:del` track changes attributed to the AI
  and marked unverified, then opened in the visual editor for a human to accept
  or reject. See [the editing stack](desktop.md) and the research report.
- **Memory and skills are matter-scoped.** A self-learning agent loop is a
  liability in legal work: one client's information must never surface in
  another's matter. Cross-matter memory is off by default and opt-in per matter.
- **Storage:** SQLite (WAL) + FTS5 + sqlite-vec for local search; local
  embeddings only. LanceDB is the scale-out option past roughly 100k chunks.
- **Secrets** live in the operating system keychain (Windows Credential Manager /
  DPAPI, Linux Secret Service). The standalone server mode may use a 0600 secrets
  file, as hermes-finance does; the desktop default may not.
