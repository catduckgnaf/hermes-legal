# Desktop: thin client for Hermes (Linux and Windows)

The app in `desktop/` is a Tauri 2 thin client. It connects to a Hermes
agent that is already running, the same way the Android clients do. It
does not embed the agent, it does not start a Python sidecar, and it
does not edit documents.

Document work stays in the Python package: `legal doc-redline`,
`legal redact`, `legal bates-stamp`, `legal cite-check`, `legal deadlines`,
and `legal serve`. The earlier plan for a standalone editor (ONLYOFFICE,
a Python sidecar, PDF.js inside this window, DOCX and PDF file
associations) is not this app. It was dropped for v1. See the decisions
in [desktop groundwork](desktop-groundwork.md). A document viewer beside
the chat is tracked separately and is not built here.

## What the window does

- Connection: scheme, host, port and token. Scheme, host and port stay
  in the page's local storage. The token is stored by the shell: Windows
  Credential Manager, or a mode-0600 file on Linux. A token left in
  local storage from an older build is moved once and then removed.
- Health: `GET /health`, with a status dot. A bad token is a separate
  "token rejected" state, because `/health` does not check the token.
- Sessions: list, load more (`offset`), create, and history.
- Chat: streamed replies. If the stream ends without a terminal event,
  the client says the reply was interrupted and reloads history. Stop
  aborts the stream and calls `POST /v1/runs/{run_id}/stop`.
- Approvals: shown when `GET /v1/capabilities` advertises them.
- The composer is disabled until the connection is healthy and the token
  is accepted, and while the connection is offline.

The frontend is plain HTML, CSS and JavaScript in `desktop/dist`, with
no build step. Protocol logic is tested with `npm test` in `desktop/`
against a mock server.

## Packaging

| Platform | Installers | When they are built |
|---|---|---|
| Windows | NSIS, MSI | Every pull request that touches `desktop/**`, plus the manual full build. The pull-request job silent-installs the NSIS package, launches it, and uninstalls it. |
| Linux | deb, AppImage | Every pull request that touches `desktop/**`, plus the manual full build. |
| Linux (sandboxed) | Flatpak manifest | Structure only. Not built in CI. |

The app id is `com.catduckgnaf.hermes-legal` in Tauri and Flatpak. A
hyphen is allowed in the last element of a Flatpak id (D-Bus bus names
allow it there, and discourage it). It stays.

There are no DOCX or PDF file associations. The client does not open
local documents. The signed updater plugin is not registered and has no
endpoint in `tauri.conf.json`. Both come back only with a feature that
needs them and, for the updater, a real public key.

Signing secrets are documented in `desktop/packaging.md`. CI builds are
unsigned smoke builds. They are not a release.

## Not this app

A future local-first editor could still use ONLYOFFICE or LibreOffice,
PDF.js, and the Python tools above. That would be a different program,
or a later milestone of this one, and it is not shipping now. Privacy
tiers, citation checks and redaction do not move into the WebView.
