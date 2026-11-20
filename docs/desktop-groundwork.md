# Desktop client groundwork (issue #34)

Status: groundwork, written 2026-11-17 against `main`. This page is the
working plan for the lightweight desktop client in issue #34. It audits
what the first pass on `main` already does, states what is verified and
what is not, and lays out the path to a usable Windows build.

Read this together with `desktop/PROTOCOL.md` (protocol research),
`desktop/TESTING.md` (manual checklist) and `desktop/packaging.md`
(bundles and signing).

## 1. Goal and non-goals

Goal: a small Windows desktop app that connects to a running Hermes agent
backend the way the Android client apps do. The user enters host, port
and token, sees whether the connection is healthy, picks a session,
chats with streamed replies, and answers approval prompts when the
server exposes them.

Non-goals:

- Not a Hermes plugin. That direction was dropped on 2026-11-14.
- Does not embed or start the agent. It is a thin client. It starts no
  child process at all.
- No Linux packaging work in this issue. The Flatpak and deb/AppImage
  files stay in the tree but are not built on pull requests.
- No code signing. CI builds are unsigned smoke builds.
- No frontend framework and no bundler. The frontend is plain HTML, CSS
  and ES modules that Node can import directly in tests.
- No legal logic in the client. Matters, documents and the database
  belong to the Python core, not to this app.

## 2. Current state audit

Columns: "On main" is the state before this groundwork pull request.
"After groundwork PR" is the state on branch `issue/desktop-34`.
"Works" means implemented and covered by an automated test against the
mock server. It does not mean verified against a live Hermes server;
no live check has been run (see section 4).

| # | Scope item from #34 | On main | After groundwork PR | Evidence |
|---|---|---|---|---|
| 1 | Connection setup: host, port, token, persisted locally | Works, with a security gap | Works, same gap, now warned about | Form: `desktop/dist/index.html`. Validation: `desktop/dist/js/config.mjs:21-57`. Persistence: `config.mjs:68-82`, called from `desktop/dist/js/app.mjs` `connect()`. The token is stored in WebView `localStorage` in plain text. Tests: `desktop/tests/config.test.mjs`. |
| 2 | Health / status indicator | Partial | Works against the mock | On main the dot is set once at connect time (`app.mjs` `setStatus()` and `connect()`), with no periodic check, so a server that dies later still shows green. This PR adds `desktop/dist/js/health.mjs` (`HealthMonitor`, polling `GET /health` with exponential backoff) and wires it in `app.mjs`. Tests: `desktop/tests/health.test.mjs`. |
| 3 | Session list | Works | Works | `client.mjs` `listSessions()` (`GET /api/sessions`), rendered by `app.mjs` `renderSessions()`. No paging UI: only the first 50 rows are requested. Tests: `client.test.mjs` "listSessions normalizes the real list shape". |
| 4 | Chat with streaming responses | Works | Works | `client.mjs` `chatStream()` plus `desktop/dist/js/sse.mjs`. Tests: `client.test.mjs` "chatStream renders deltas incrementally and completes", `sse.test.mjs`. No cancel button, no resume after a dropped stream. |
| 5 | Approval prompts | Works against the mock | Works against the mock | `client.mjs` `approvalsSupported()` and `resolveApproval()`, `app.mjs` `showApproval()` / `answerApproval()`. Feature-gated on `/v1/capabilities`; when not advertised the UI says so. Tests: `client.test.mjs` "chatStream surfaces an approval request and resolves it mid-stream" and the 409 case. |
| 6 | Tests against a mock implementing the real protocol | Partial | Partial | `desktop/tests/mock-hermes.mjs` implements what `desktop/PROTOCOL.md` describes. The protocol document cites upstream sources by name but pins no commit and vendors no excerpt, so the mock cannot be checked against the real server from this repository. See section 4. |
| 7 | Windows packaging: NSIS / MSI bundle targets | Works (configured) | Works (configured) | `desktop/src-tauri/tauri.conf.json` `bundle.targets` includes `nsis` and `msi`; `bundle.windows.nsis` and `bundle.windows.wix` are set. Pinned by `tests/test_desktop_packaging.py`. |
| 8 | Windows CI build | Works (configured) | Works (configured), simpler | `.github/workflows/desktop.yml` job `build-windows (pull request)` runs `npm test` then `cargo tauri build --bundles nsis,msi` and uploads the bundles. This PR removes the placeholder sidecar staging step because the app no longer bundles a sidecar. |

Defects from issue #26 that touch the desktop app:

| Defect | On main | After groundwork PR |
|---|---|---|
| Tauri and Flatpak use different app identifiers | `com.catduckgnaf.hermes-legal` (Tauri) vs `com.catduckgnaf.hermeslegal` (Flatpak) | Both `com.catduckgnaf.hermes-legal`. A Node test and a Python test pin the match. |
| Flatpak requests the whole home directory | `--filesystem=home` | Removed. The thin client reads and writes no user files. |
| Sidecar is not stopped on exit | `lib.rs` spawned `hermes-legal-sidecar serve --port 8770` and dropped the child handle | Sidecar removed entirely. Nothing is spawned, so nothing can be left running. |
| Webview has shell permissions it does not need | `shell:allow-execute` and `shell:allow-spawn` in `capabilities/default.json`, `tauri-plugin-shell` registered | Capability file grants `core:default` only. The shell plugin is no longer a dependency. |

Other gaps found in the audit (not fixed here unless stated):

- `lib.rs` on main carried two contradictory doc comments (thin client
  and sidecar dashboard). Fixed in this PR.
- `tauri.conf.json` descriptions still described the local-first legal
  desktop with a Python sidecar. Fixed in this PR.
- `tauri.conf.json` still declares `fileAssociations` for DOCX and PDF.
  The thin client cannot open those files. Left in place because
  `tests/test_desktop_packaging.py` pins them and removing them is a
  product decision (open question 4).
- `plugins.updater` is configured with an empty `pubkey` and the updater
  plugin is not registered in Rust. Harmless today, but it is dead
  configuration. Left for the signing milestone.
- `app.mjs` has no automated test. It is DOM wiring only, but errors in
  `selectSession()` and the "new session" handler are not caught and
  would surface as unhandled rejections.
- The CSP allows `connect-src http: https: ws: wss:` to any host. That
  is required while the host is user-configured, and is discussed in
  section 5.
- The session list has no paging and no search.
- There is no stream cancel and no reconnect of a dropped chat stream.

## 3. Architecture

### 3.1 Process model

One process tree, owned by Tauri:

- The Tauri shell (`desktop/src-tauri`, Rust). It creates one window
  labeled `main`, loads the static files in `desktop/dist`, and does
  nothing else. No commands, no plugins, no child processes.
- The system WebView (WebView2 on Windows). It runs the frontend and
  makes every network request itself with `fetch`.

There is no sidecar and no local server. The Hermes agent runs
elsewhere (same machine or another host) and is reached over HTTP.

### 3.2 Shell versus webview

| Concern | Owner today | Planned owner |
|---|---|---|
| Window, lifecycle, installers | Shell | Shell |
| Rendering, user input | Webview | Webview |
| HTTP and SSE to Hermes | Webview (`fetch`) | Webview |
| Host and port persistence | Webview (`localStorage`) | Webview |
| Token persistence | Webview (`localStorage`, plain text) | Shell, through two narrow commands backed by Windows Credential Manager (M2) |

Keeping HTTP in the webview means the protocol code stays testable in
plain Node with no Rust build. The cost is that the CSP must allow
outbound connections to a user-chosen host.

### 3.3 Module boundaries

| Module | Responsibility | May import | Tested by |
|---|---|---|---|
| `dist/js/config.mjs` | Normalize, validate, load and save the connection config. Report security warnings for a config. | nothing | `tests/config.test.mjs` |
| `dist/js/sse.mjs` | Incremental SSE parser. No transport. | nothing | `tests/sse.test.mjs` |
| `dist/js/client.mjs` | Every Hermes HTTP call and the stream loop. Turns HTTP and network failures into `HermesError`. | `config.mjs`, `sse.mjs` | `tests/client.test.mjs` (mock server) |
| `dist/js/health.mjs` | `backoffDelay()` and `HealthMonitor`: periodic health polling with backoff, state change callback. Timers are injected. | nothing | `tests/health.test.mjs` |
| `dist/js/app.mjs` | DOM wiring only. No protocol knowledge beyond event names it renders. | all of the above | manual checklist (`desktop/TESTING.md`) |
| `src-tauri/src/lib.rs` | Start the window. | Tauri | Windows CI build |

Rule: nothing except `app.mjs` touches `document` or `window`, and
nothing except `client.mjs` builds a Hermes URL.

### 3.4 Data flows

Connect:

1. `app.mjs` reads the form and calls `saveConfig()`. Invalid input
   throws a `TypeError` whose message is shown; nothing is sent.
2. `new HermesClient(config)`, then `GET /health` (no auth).
3. `GET /v1/capabilities` (bearer). A failure here is tolerated and
   treated as "approvals not advertised".
4. Status becomes connected; `HealthMonitor` starts polling.
5. `GET /api/sessions`, then the first session's messages are loaded.

List sessions: `GET /api/sessions?limit=50&offset=0`, rows mapped by
`normalizeSession()`, rendered as buttons. Selecting one calls
`GET /api/sessions/{id}/messages` and renders user and assistant rows.

Send and stream:

1. If no session is selected, `POST /api/sessions` creates one.
2. `POST /api/sessions/{id}/chat/stream` with `{ "message": text }`.
3. The response body is read chunk by chunk into `SSEParser`.
4. `assistant.delta` appends text. `assistant.completed` replaces the
   text with the final content. `run.completed`, `run.failed` or
   `run.cancelled` sets the result status.
5. The session list is refreshed when the stream ends.

Approve:

1. An `approval.request` event arrives on the open stream.
2. If capabilities advertised approval support, the prompt is shown
   with the choices the event carried (fallback `once` / `deny`).
3. The user's choice goes to `POST /v1/runs/{run_id}/approval` on a
   second connection while the stream stays open.
4. The stream continues and ends normally.

## 4. Protocol: what is cited and what is unverified

`desktop/PROTOCOL.md` says the client uses the Hermes API server (HTTP
plus SSE, default `127.0.0.1:8642`, bearer token from `API_SERVER_KEY`)
and names these sources: `NousResearch/hermes-agent` files
`gateway/platforms/api_server.py` and
`gateway/platforms/api_server_runs.py` "on current main", the Hermes
docs pages "Programmatic Integration" and "API Server", and three
Android clients (`rusty4444/hermes-android`,
`pavel-zinchenko/hermes-android-client`, Hermes-Relay).

What that citation does not give: a commit hash, a file line, a URL, or
a copied excerpt. None of the upstream sources is vendored here. So
from inside this repository **no endpoint or event can be verified**.
This groundwork did not fetch upstream and did not contact any Hermes
host. Everything below is therefore one of:

- CITED, UNVERIFIED: stated in `desktop/PROTOCOL.md` with a named
  upstream source, not checkable from this repository.
- UNCITED, UNVERIFIED: used by the client or the mock but not stated in
  `desktop/PROTOCOL.md` at all.

| Item | Where the client uses it | Status |
|---|---|---|
| `API_SERVER_ENABLED`, `API_SERVER_HOST`, `API_SERVER_PORT`, default port 8642 | `config.mjs` defaults | CITED, UNVERIFIED |
| `Authorization: Bearer <API_SERVER_KEY>` on every route except `/health` | `client.mjs` `#headers()` | CITED, UNVERIFIED |
| `GET /health` returning `status`, `platform`, `version` | `health()` | CITED, UNVERIFIED |
| `GET /health/detailed` | not used | CITED, UNVERIFIED |
| `GET /v1/capabilities` with `features.run_approval_response` and `features.approval_events` | `approvalsSupported()` | CITED, UNVERIFIED |
| `features.run_approval` as a fallback flag name | `client.mjs` `approvalsSupported()` | UNCITED, UNVERIFIED |
| `GET /api/sessions?limit&offset`, list envelope, row fields `id`, `title`, `source`, `model`, `message_count`, `last_active`, `preview` | `listSessions()` | CITED, UNVERIFIED |
| Row fields `ended_at`, `started_at` as fallbacks | `normalizeSession()` | UNCITED, UNVERIFIED |
| `POST /api/sessions` returning 201 with `object: "hermes.session"` | `createSession()` | CITED, UNVERIFIED |
| Request body fields `title` and `source: "desktop"` on session create | `createSession()` | UNCITED, UNVERIFIED |
| `GET /api/sessions/{id}/messages`, list envelope | `listMessages()` | CITED, UNVERIFIED |
| Message fields `id`, `role`, `content`, `timestamp` | `listMessages()` | UNCITED, UNVERIFIED |
| `POST /api/sessions/{id}/chat/stream` with `{ "message" }` | `chatStream()` | CITED, UNVERIFIED |
| SSE envelope fields `event`, `session_id`, `run_id`, `seq`, `ts` | `chatStream()` | CITED, UNVERIFIED |
| Events `run.started`, `message.started`, `assistant.delta`, `assistant.commentary`, `tool.started`, `tool.completed`, `tool.failed`, `approval.request`, `assistant.completed`, `run.completed`, `run.failed`, `run.cancelled`, `done` | `chatStream()`, `app.mjs` | CITED, UNVERIFIED |
| `: keepalive` comment about every 10 seconds | `sse.mjs` | CITED, UNVERIFIED |
| An `error` event with a `message` field | `client.mjs` stream loop | UNCITED, UNVERIFIED |
| A `request.cancel` event | `app.mjs` `send()` | UNCITED, UNVERIFIED |
| A `[DONE]` data sentinel on the native session stream | `sse.mjs`, `client.mjs` | UNCITED, UNVERIFIED (it is the OpenAI convention; whether the native route sends it is not stated) |
| Tool event fields `tool_name` / `tool` | `app.mjs` | UNCITED, UNVERIFIED |
| `approval.request` fields `command`, `description`, `choices` (`once`, `session`, `always`, `deny`) | `showApproval()` | CITED, UNVERIFIED |
| `approval.request` fields `request_id` / `prompt_id`, `execution_generation` | `answerApproval()` | CITED (as "when the event carried them"), UNVERIFIED |
| `POST /v1/runs/{run_id}/approval` with `{ "choice" }`, optional `request_id` and `execution_generation`, HTTP 409 on stale identity | `resolveApproval()` | CITED, UNVERIFIED |
| Error body shape `{ error: { message, code, type } }` | `errorFromBody()` | UNCITED, UNVERIFIED |
| Mock error code `approval_not_pending` | `mock-hermes.mjs` | UNCITED, UNVERIFIED |
| Stream resume (for example `Last-Event-ID`, or re-attaching to a run by `run_id`) | not implemented | UNKNOWN. `desktop/PROTOCOL.md` says nothing about resume. Do not build resume until this is researched. |
| Run cancel endpoint | not implemented | UNKNOWN |
| CORS behavior of the API server for a webview origin | all requests | UNKNOWN. If the server sends no CORS headers, `fetch` from the webview origin will fail on a real server even though the Node tests pass. This is the single biggest risk in the current design. See open question 1. |
| TUI gateway methods and ticket bootstrap | not used | CITED, UNVERIFIED |

Consequence for scope item 6: the mock is faithful to
`desktop/PROTOCOL.md`, and `desktop/PROTOCOL.md` is unverified from
here. Milestone M0 closes that gap by pinning the upstream commit and
recording one captured exchange from a real server.

## 5. Security model

Assets: the bearer token (full control of the agent), the conversation
content, and the ability to approve tool calls.

Token storage:

- Now: `localStorage` in the WebView profile, plain text, under key
  `hermes-legal-desktop.connection.v1`. On Windows that is a file in
  the app's data directory, readable by any process running as the
  same user. It is not encrypted.
- Plan (M2): keep scheme, host and port in `localStorage`. Move the
  token to Windows Credential Manager through the shell. Add exactly
  two Tauri commands, `token_get` and `token_set`, implemented with a
  credential store crate, and a custom capability that allows only
  those two. The frontend gets a `tokenStore` object with the same
  shape as the injected storage in `config.mjs`, so tests keep using an
  in-memory stand-in. On first run after the change, migrate an
  existing `localStorage` token into the store and delete it from
  `localStorage`. On Linux later, the same commands map to the Secret
  Service.

CSP (from `tauri.conf.json`): `default-src 'self'`, `script-src 'self'`
(no inline script, no remote script), `style-src 'self'
'unsafe-inline'`, `connect-src 'self' http: https: ws: wss:`.

- `connect-src` is wide because the host is chosen at run time and a
  static CSP cannot name it. Options for later: route requests through
  a Rust command that enforces the configured origin (heavier, loses
  the Node-testable client), or accept the wide `connect-src` and rely
  on `script-src 'self'` so that only shipped code can issue requests.
  The plan keeps the second option. `ws:` and `wss:` are unused today
  and can be dropped (sub-issue 7).
- All message text is inserted with `textContent`, never `innerHTML`.
  Keep that rule; a Markdown renderer, if added, must sanitize.

Tauri capability allowlist: after this PR, `capabilities/default.json`
grants `core:default` to window `main` and nothing else. No shell, no
filesystem, no HTTP plugin, no dialog. `desktop/tests/packaging.test.mjs`
fails if a `shell:` permission returns. Adding a capability later
requires a line in this section saying why.

Loopback versus LAN:

- Loopback (`127.0.0.1`, `::1`, `localhost`) over `http` is the default
  and is acceptable: the token does not leave the machine.
- Any other host over `http` sends the token and the conversation in
  clear text on the network. After this PR `configWarnings()` reports
  that and the UI shows the warning next to the status line. It warns;
  it does not block, because a tunnel such as a private mesh VPN makes
  plain `http` to a non-loopback name reasonable. Whether to block
  instead is open question 3.

TLS: `https` is accepted as a scheme. Certificate checks are whatever
the system WebView does. There is no option to trust a self-signed
certificate and none is planned; use a real certificate or a tunnel.

No shell permission: the app starts no process and has no plugin that
could. This is pinned by tests on both the Node and Python sides.

Not addressed yet: the token is visible in the form field while typed
(it is a password input), is held in memory for the session, and is
sent to whatever host the user typed. There is no host pinning.

## 6. State and error handling

Connection states shown by the indicator:

| State | Dot | Meaning | Entered when |
|---|---|---|---|
| `idle` | gray | Not connected yet | App start |
| `pending` | amber | Connecting, or waiting for an approval decision | Connect pressed, or `approval.request` |
| `ok` | green | Last health check succeeded | Health check succeeds |
| `error` | red | Not connected, or connection lost and retrying | Connect fails, or a health poll fails |

Health polling and backoff (`health.mjs`, added in this PR):

- While healthy, poll `GET /health` every 15 seconds.
- On failure, report `offline` with the retry delay and poll again
  after `backoffDelay(attempt)`: 1 s, 2 s, 4 s, 8 s, 16 s, capped at
  30 s, with up to 20 percent jitter.
- On the first success after failures, report `ok` and return to the
  15 second interval.
- `stop()` cancels the pending timer. Reconnecting with new settings
  stops the old monitor first.

Chat stream errors today: a network failure or non-2xx response
rejects with `HermesError`; the message is shown in the error bar and
the composer is re-enabled. A stream that ends with no terminal event
is reported as `completed` if any text arrived and `failed` otherwise.
That guess is weak and is listed as sub-issue 5.

SSE resume: not implemented and not designed, because the protocol
document does not say whether the server supports it (section 4). The
safe behavior after a dropped stream, which needs no new protocol, is:
show "stream interrupted", wait for health to return, then reload the
session's messages with `GET /api/sessions/{id}/messages` so the user
sees whatever the server finished. That is M1 work.

Offline: when the monitor reports `offline`, sending stays possible and
fails fast with the network error. M1 disables the composer while
offline and re-enables it on recovery.

Auth errors: HTTP 401 on any call surfaces as `HermesError` with
`status` 401. M1 maps that to a specific "token rejected" message and
stops the health monitor from showing green (health is unauthenticated,
so a green dot with a bad token is possible today; see sub-issue 4).

## 7. Packaging

- Bundle targets: `nsis` and `msi` for Windows are configured in
  `tauri.conf.json` (`bundle.targets`, `bundle.windows.nsis` with
  `installMode: currentUser`, `bundle.windows.wix` with `en-US`).
  `appimage` and `deb` remain configured for the later Linux work.
- No external binary. `bundle.externalBin` is removed with the sidecar.
- winget: `desktop/winget/` holds a three-file manifest set for
  `Catduck.HermesLegal`. `InstallerSha256` is deliberately absent until
  a real artifact exists. The manifests cannot be submitted before a
  signed release, because winget validation and SmartScreen both
  expect a signed installer.
- Unsigned smoke builds: every pull request that touches `desktop/**`
  builds NSIS and MSI installers on `windows-latest` and uploads them
  as a workflow artifact. They are unsigned, will trigger SmartScreen,
  and are never published as a release.
- Later signing: the workflow already passes the signing secrets named
  in `desktop/packaging.md` through to the build. Nothing is committed.
  Signing, the updater public key and the updater plugin registration
  land together in M4.

App identifier unification. Three identifiers exist:

| Surface | Identifier | Decision |
|---|---|---|
| Tauri (`tauri.conf.json` `identifier`) | `com.catduckgnaf.hermes-legal` | Kept. It is the Windows-first surface, it names the per-user data directory that holds the saved connection, and `tests/test_desktop_packaging.py` already pinned it. |
| Flatpak (`app-id`, file names, desktop entry) | was `com.catduckgnaf.hermeslegal` | Changed to `com.catduckgnaf.hermes-legal`. Nothing was ever published under the old id. Note: a hyphen in the last element of a Flatpak app id is, to my knowledge, allowed but discouraged; this was not re-checked against the Flatpak documentation in this pass. If Flathub review objects, the alternative is to change both surfaces to `com.catduckgnaf.hermeslegal` before the first release (open question 5). |
| winget (`PackageIdentifier`) | `Catduck.HermesLegal` | Kept. winget uses a `Publisher.Package` namespace, not reverse DNS, so it cannot literally match. It is the same product name. |

## 8. CI plan

Workflow `.github/workflows/desktop.yml`, triggered on pull requests
that touch `desktop/**` or the workflow file:

| Job | Runner | What it proves |
|---|---|---|
| `client tests (mock Hermes server)` | `ubuntu-latest` | `npm test` in `desktop/`: config, SSE, client contract, health monitor and packaging consistency tests. |
| `build-windows (pull request)` | `windows-latest` | The same Node tests on Windows, then `cargo tauri build --bundles nsis,msi`, then upload of `target/release/bundle/**`. Proves the Rust shell compiles without the shell plugin and both installers are produced. |
| `build (matrix)` | dispatch only | Full build on Windows and Linux, with signing secrets passed through when present. |

The repository-wide Python suite also runs
`tests/test_desktop_packaging.py`, which pins the packaging facts.

Planned additions, in order:

1. Cache `~/.cargo` and `target` in the Windows job (the Tauri CLI
   install dominates the run time).
2. An installer smoke step: run the NSIS installer with `/S`, check the
   executable exists, start it, wait a few seconds, check the process
   is alive, then stop it.
3. A JSON schema check of `capabilities/default.json` against the
   generated Tauri schema.
4. A live contract job, manual dispatch only, that runs the client
   tests against a real Hermes API server started in the job. Blocked
   on M0.

## 9. Test strategy

- Unit (Node, no network): `config.test.mjs`, `sse.test.mjs`,
  `health.test.mjs` (fake timers and a fake client).
- Mock server contract tests: `client.test.mjs` starts
  `mock-hermes.mjs` on an ephemeral loopback port and drives the real
  client through health, auth failure, capabilities, session list,
  create, history, streaming, approval and the 409 case.
- Packaging consistency: `desktop/tests/packaging.test.mjs` (Node) and
  `tests/test_desktop_packaging.py` (Python) read the config files and
  fail on identifier drift, shell permissions, a sidecar entry or a
  home directory grant.
- Mock fidelity: once M0 records a real exchange, add a fixture replay
  test that feeds the captured SSE bytes through `chatStream()`, and
  run `client.test.mjs` against a real server in the manual CI job.
- Manual: `desktop/TESTING.md` is the Windows smoke checklist and the
  GitHub Actions checklist.
- Not covered and not planned for automation yet: `app.mjs` DOM wiring.
  If it grows, extract the logic into a testable module instead of
  adding a browser test runner.

## 10. Milestones

### M0: protocol verification

Acceptance criteria:

- `desktop/PROTOCOL.md` names the upstream commit hash and links file
  lines for every endpoint and event in section 4.
- Every UNCITED row in section 4 is either cited or removed from the
  client and the mock.
- One real exchange is captured from a real server (health,
  capabilities, session list, one streamed turn, one approval if the
  server offers it) and stored, redacted, under `desktop/tests/fixtures/`.
- The CORS question is answered in writing with evidence.

### M1: usable daily on Windows from an unsigned build

Acceptance criteria:

- Every step of the Windows section of `desktop/TESTING.md` passes
  against a real Hermes server.
- Dropped stream recovery reloads the session history.
- 401 shows a "token rejected" message and the indicator is not green.
- Composer is disabled while offline.
- Session list paging ("load more").
- Stream cancel, if M0 finds a cancel endpoint.

### M2: token out of localStorage

Acceptance criteria:

- Token stored in Windows Credential Manager; not present in
  `localStorage` after migration.
- Capability file lists exactly the two token commands plus
  `core:default`, and the packaging test pins that list.
- Rust unit tests for the two commands; Node tests unchanged in shape.

### M3: installer quality

Acceptance criteria:

- CI installer smoke step passes for NSIS.
- Install, upgrade over a previous build, and uninstall work by hand
  for NSIS and MSI, and the saved connection survives an upgrade.
- Product strings, icons and file associations are correct for the
  thin client.

### M4: signed release and distribution

Acceptance criteria:

- Signed NSIS and MSI from the dispatch build.
- Updater plugin registered with a real public key, or the updater
  config removed.
- winget manifests completed with real hashes and validated locally.

## 11. Ready-to-file sub-issues

1. **Desktop: pin the Hermes API server protocol to an upstream commit.**
   `desktop/PROTOCOL.md` cites upstream files without a commit or line
   links. Add the commit hash and a link per endpoint and event. Mark
   or remove anything the client uses that upstream does not have (see
   the UNCITED rows in `docs/desktop-groundwork.md` section 4). Done
   when every row in that table is cited with a link.
2. **Desktop: verify CORS behavior of the API server from a WebView origin.**
   The client calls Hermes with `fetch` from the Tauri webview origin.
   Confirm on a real server whether cross-origin requests with an
   `Authorization` header and a streamed response succeed. If not,
   decide between a server-side CORS setting and moving HTTP into the
   Rust shell. Done when the answer and evidence are in
   `desktop/PROTOCOL.md`.
3. **Desktop: record a real exchange as a test fixture.**
   Capture and redact one health, capabilities, sessions and streamed
   chat exchange and add a replay test. Done when the fixture test runs
   in `npm test`.
4. **Desktop: treat a rejected token as a distinct state.**
   `/health` is unauthenticated, so the indicator can be green with a
   bad token. After connect and periodically, make one authenticated
   call and show "token rejected" on 401. Done with a mock server test
   for the wrong-token path through the monitor.
5. **Desktop: handle a chat stream that ends without a terminal event.**
   `chatStream()` guesses `completed` when text arrived. Report
   `interrupted` instead, and have the UI reload the session history.
   Done with a mock test that cuts the stream mid-turn.
6. **Desktop: store the token in Windows Credential Manager.**
   Implement the M2 plan in `docs/desktop-groundwork.md` section 5.
7. **Desktop: tighten the CSP.**
   Drop `ws:` and `wss:` from `connect-src` (unused), and review
   `style-src 'unsafe-inline'`. Done when the app still works by the
   manual checklist with the narrower policy.
8. **Desktop: catch errors in session selection and new session.**
   `selectSession()` and the new-session click handler in `app.mjs`
   can reject without showing an error. Route both through the error
   bar.
9. **Desktop: session list paging.**
   Only the first 50 sessions load. Add "load more" using `offset`.
10. **Desktop: decide the fate of DOCX and PDF file associations and the updater block.**
    Both are leftovers from the earlier local-first desktop direction.
    Remove them or record why they stay, and update
    `tests/test_desktop_packaging.py` to match.
11. **Desktop CI: cache cargo and add an NSIS install smoke step.**
    See section 8, planned additions 1 and 2.
12. **Docs: rewrite `docs/desktop.md` and `desktop/packaging.md` for the thin client.**
    Both still describe the Tauri shell plus Python sidecar product.
    This PR adds a short correction notice to each; the full rewrite is
    separate.

## 12. Open questions for the owner

1. CORS: does your Hermes API server answer cross-origin requests from
   a webview? If you can run the unsigned build against it once
   (`desktop/TESTING.md`, Windows steps 4 to 6), that answers it.
2. The Python sidecar is removed from the Tauri app in this PR, on the
   reading that issue #34 makes the desktop app a thin Hermes client
   only. `docs/desktop.md` still describes a "Tauri 2 plus Python
   sidecar" standalone product. Is that product dropped, or does it
   need its own separate app later?
3. Plain `http` to a non-loopback host: warn (current) or block unless
   an explicit "allow insecure" box is ticked?
4. DOCX and PDF file associations: remove from the thin client?
5. Identifier: keep `com.catduckgnaf.hermes-legal` everywhere, or move
   everything to the hyphen-free `com.catduckgnaf.hermeslegal` before
   anything ships?
6. Should the app be named for Hermes generally or stay `hermes-legal`?
   The window title is currently "hermes-legal - Hermes desktop client".
7. Is a same-machine TUI gateway mode (richer approvals, clarify, sudo
   prompts) wanted after v1, or is the API server enough?
