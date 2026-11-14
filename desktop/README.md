# Desktop client

A lightweight desktop client that connects to Hermes — the agent
backend — the way the Android client apps do. It is built from the
ground up as a client: it does not embed the agent and it is not a
Hermes plugin (the plugin direction was decided against on
2026-11-14). Windows first; Linux later.

See [PROTOCOL.md](PROTOCOL.md) for the researched Hermes protocol this
client is built against, and [../docs/desktop.md](../docs/desktop.md)
for the earlier Tauri decision record this client keeps.

## What it does

- Connection setup — scheme, host, port and token — persisted locally
  in the WebView's local storage on this computer only. The defaults
  are the Hermes API server defaults: `127.0.0.1`, port `8642`, and
  the token is that server's `API_SERVER_KEY`, sent as a bearer token.
  The token is stored as entered; treat this computer's user account
  as the trust boundary, the same as a saved API key in any client.
- Health and status: `GET /health` on connect, with a status indicator
  that stays visible, plus the server's version.
- Session list: `GET /api/sessions`, with create and history
  (`GET /api/sessions/{id}/messages`).
- Chat with streaming: `POST /api/sessions/{id}/chat/stream`, rendered
  incrementally as `assistant.delta` events arrive.
- Approval prompts: when the server advertises approval support in
  `GET /v1/capabilities`, an `approval.request` event opens a prompt
  with the server's own choices, answered through
  `POST /v1/runs/{run_id}/approval`. When the server does not
  advertise it, the connection panel says so and no prompt is shown.

## Layout

- `dist/` — the whole frontend: plain HTML, CSS and JavaScript, no
  framework, no build step. Protocol logic lives in testable ES
  modules under `dist/js/` (`config.mjs`, `sse.mjs`, `client.mjs`);
  `dist/js/app.mjs` only wires them to the page.
- `tests/` — Node tests (`node --test`) that run the client logic
  against `tests/mock-hermes.mjs`, a mock server implementing the
  real protocol shapes: health, capabilities, sessions, streaming
  chat, and the approval flow. Run them with `npm test` in this
  directory.
- `src-tauri/` — the Tauri 2 shell (`tauri.conf.json`, `Cargo.toml`,
  `src/main.rs`, `src/lib.rs`, capabilities, icons). The shell stays
  minimal; all client behavior is in the frontend modules. The
  bundled Python sidecar from the earlier scaffold remains configured
  for the legal core packaging and is not part of the Hermes
  connection.
- `flatpak/` — Flatpak manifest (structure only in this pass; Linux
  packaging is later).
- `winget/` — winget manifest set for the signed Windows installers.
- `packaging.md` — build, signing secrets, update, and release
  checklist.

## Windows packaging and CI

`tauri.conf.json` keeps the NSIS and MSI bundle targets (plus the
existing Linux targets, untouched in this pass). The desktop workflow
runs the mock-server tests and an unsigned Windows build
(`cargo tauri build --bundles nsis,msi`) on pull requests that touch
`desktop/**`, and keeps the manually triggered full build. CI builds
are unsigned smoke builds; signing stays a release step, see
`packaging.md`.
