# Hermes protocol research

Findings from researching the real Hermes protocol before building this
client (2026-11-14). Sources: the live `NousResearch/hermes-agent`
repository (`gateway/platforms/api_server.py` and
`gateway/platforms/api_server_runs.py` on current main), the official
Hermes docs pages "Programmatic Integration" and "API Server"
(hermes-agent.nousresearch.com), and existing Android clients
(`rusty4444/hermes-android`, `pavel-zinchenko/hermes-android-client`,
Hermes-Relay).

## Hermes ships three protocols

| Protocol | Transport | Notes |
|---|---|---|
| ACP | JSON-RPC over stdio | For IDE clients that already speak the Agent Client Protocol. |
| TUI gateway | JSON-RPC over stdio or WebSocket | The rich host protocol behind the Ink TUI and the Hermes desktop app. |
| API server | HTTP + Server-Sent Events | OpenAI-compatible; for web frontends and language-agnostic clients. |

All three drive the same agent core.

## The protocol this client uses: the API server

The Android clients settle the choice. `rusty4444/hermes-android` does
chat and sessions against the gateway API server on port 8642
(`GET /api/sessions`, `GET /api/sessions/{id}/messages`,
`POST /v1/chat/completions` with SSE) and uses the dashboard on 9119
only for management surfaces. This client follows that split and uses
the API server only:

- Enable it with `API_SERVER_ENABLED=true`; it binds `127.0.0.1:8642`
  by default (`API_SERVER_HOST` / `API_SERVER_PORT` change that).
- Auth is one bearer token: `Authorization: Bearer <API_SERVER_KEY>`.
  The key is required even on loopback. `GET /health` is the only
  public route used here.
- Health: `GET /health` returns `{ "status": "ok", "platform":
  "hermes-agent", "version": ... }`. `GET /health/detailed` is an
  authenticated readiness view.
- Feature detection: `GET /v1/capabilities` returns `features` and
  `endpoints`. This client reads `features.run_approval_response` and
  `features.approval_events` before showing any approval UI.
- Sessions (all bearer-gated): `GET /api/sessions?limit&offset` returns
  `{ "object": "list", "data": [...] }` with rows carrying `id`,
  `title`, `source`, `model`, `message_count`, `last_active` and
  `preview`. `POST /api/sessions` creates one (201,
  `{ "object": "hermes.session", "session": {...} }`).
  `GET /api/sessions/{id}/messages` returns the same list envelope.
- Streaming chat: `POST /api/sessions/{id}/chat/stream` with body
  `{ "message": "..." }` (the server also accepts `input`) answers SSE
  frames — `event: <name>` plus `data: <json>` where the JSON also
  carries `event`, `session_id`, `run_id`, `seq` and `ts`. Event
  order: `run.started`, `message.started`, then any mix of
  `assistant.delta` (`delta` text), `assistant.commentary`,
  `tool.started` / `tool.completed` / `tool.failed` and
  `approval.request`, then `assistant.completed` (authoritative final
  `content`), a terminal `run.completed` / `run.failed` /
  `run.cancelled`, and `done`. Idle streams get a `: keepalive`
  comment line about every 10 seconds; parsers must skip comments.
- Session continuity headers exist for the OpenAI-compatible routes
  (`X-Hermes-Session-Id`, `X-Hermes-Session-Key`); the native session
  routes carry the session id in the path instead, which is what this
  client uses.

## Approvals: exposed, with two shapes

Approvals are real on this protocol; nothing is faked.

- During a session-chat stream (and on `/v1/runs`), a gated tool call
  emits an `approval.request` event carrying the (server-redacted)
  `command` and `description` plus the `choices` the client may send
  back — `once`, `session`, `always`, `deny`, narrowed to
  `once` / `deny` when the server says so. The run parks in
  `waiting_for_approval`.
- The client resolves it with `POST /v1/runs/{run_id}/approval`. The
  plain API-server shape is `{ "choice": "once" }`. When the gateway
  runs its canonical session authority, the same endpoint requires the
  exact identity: `{ "request_id": "<prompt_id>",
  "execution_generation": <n>, "choice": "once" }`, and stale or
  foreign identities get HTTP 409. This client sends `request_id` and
  `execution_generation` whenever the approval event carried them.
- If a server does not advertise approval support in
  `/v1/capabilities`, the client shows no prompt UI and says so in the
  connection panel instead of pretending.

## The TUI gateway, and why it is not v1 here

The TUI gateway (`tui_gateway/server.py`) is richer: `session.create`,
`session.list`, `prompt.submit`, streaming `message.delta` /
`message.complete` events, and server-to-client JSON-RPC requests for
`approval`, `clarify`, `sudo` and `secret`, which the client must
advertise with `client.capabilities` (`{ "server_requests": true }`)
after `gateway.ready` or the gateway fails them fast. Over WebSocket
it lives on the dashboard port (9119) at `/api/ws`, speaks protocol
`hermes-gateway-v1`, and needs a single-use ticket per connection,
obtained locally (`hermes gateway attach --json` or a dashboard
session token). That ticket bootstrap is built for hosts running on
the same machine as Hermes; the newer Android clients that use it run
on-device (Termux) for exactly that reason. A remote desktop client
pointing at a Hermes host over LAN or Tailscale has no honest way to
mint those tickets, so v1 uses the API server, whose bearer token is
designed for remote clients. The TUI gateway stays the documented
upgrade path for a same-machine mode.

## Weight: why Tauri, not a rewrite

The existing decision in the project docs stands and this client keeps
it: a Tauri 2 shell is a few megabytes against an Electron install an
order of magnitude larger, uses the operating system's WebView instead
of shipping a browser, and the frontend here is plain HTML, CSS and
JavaScript with no framework and no build step — the whole client
logic is three small ES modules that Node tests import directly.
