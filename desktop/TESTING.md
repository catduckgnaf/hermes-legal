# Desktop client: manual test checklist

Two parts: what to watch on GitHub Actions, and what to check by hand
on a Windows machine. Tick each box; anything that fails goes into the
pull request or a new issue with the step number.

Background: `../docs/desktop-groundwork.md`. Protocol notes:
`PROTOCOL.md`.

## Part A: automated checks you can run locally

Needs Node 22 or newer. No install step; there are no dependencies.

```
cd desktop
npm test
```

- [ ] A1. All tests pass (config, SSE parser, client against the mock
      server, health monitor, packaging consistency).

From the repository root, with the Python dev environment:

```
python -m pytest tests/test_desktop_packaging.py -q
python scripts/check_us_spelling.py
```

- [ ] A2. Both pass.

## Part B: GitHub Actions

Open the pull request, then the "Checks" tab, workflow "Desktop".

- [ ] B1. Job `client tests (mock Hermes server)` is green.
- [ ] B2. Job `build-windows (pull request)` is green. In its log:
  - [ ] the step "Run the desktop client tests against the mock Hermes
        server" ran and passed on Windows;
  - [ ] there is no "Stage the Python sidecar placeholder" step (it was
        removed with the sidecar);
  - [ ] the step "Build the Tauri app for Windows (unsigned smoke
        build)" finished and its last lines list an `.msi` and a
        `-setup.exe`.
- [ ] B3. The run has an artifact named
      `hermes-legal-desktop-windows-pr`. Download it. It contains
      `nsis/hermes-legal_<version>_x64-setup.exe` and
      `msi/hermes-legal_<version>_x64_en-US.msi`.
- [ ] B4. The repository test workflow (Python suite) is green,
      including `tests/test_desktop_packaging.py`.

If B2 fails in the Rust compile step, the most likely cause is this
pull request's removal of `tauri-plugin-shell`; paste the compiler
error into the pull request.

## Part C: Windows, by hand

Use the artifact from B3. The build is unsigned, so Windows SmartScreen
will warn. That is expected until signing is set up.

You need a Hermes agent with the API server enabled and its key. For a
dry run without Hermes you can use the mock instead (see C0).

### C0. Optional: run against the mock server

In a terminal with Node 22:

```
cd desktop
node -e "import('./tests/mock-hermes.mjs').then(async (m) => { console.log(Object.keys(m)); })"
```

That prints the mock's exports. `tests/client.test.mjs` shows how the
tests start it on an ephemeral port; a small standalone launcher script
is not in the tree yet (it is a good first follow-up). The mock token
is `test-api-server-key`. The mock sends no CORS headers, so the
installed app may be refused by the WebView when pointed at the mock;
record what you see in C4.

### C1. Install

- [ ] C1.1 Run the `-setup.exe`. SmartScreen: "More info", "Run
      anyway". The installer completes without asking for admin rights
      (it installs for the current user).
- [ ] C1.2 `hermes-legal` appears in the Start menu.
- [ ] C1.3 Separately, on a clean user profile or after uninstalling,
      run the `.msi`. It installs and appears in "Installed apps".

### C2. First start

- [ ] C2.1 The app opens one window titled "hermes-legal - Hermes
      desktop client".
- [ ] C2.2 The form shows scheme `http`, host `127.0.0.1`, port `8642`,
      empty token. The status dot is gray and reads "Not connected."
- [ ] C2.3 Task Manager, Details tab: only the app and its WebView2
      processes run. There is no `hermes-legal-sidecar` process.

### C3. Connection validation

- [ ] C3.1 Clear the host and press Connect: an error says the host is
      required. Nothing else happens.
- [ ] C3.2 Port `0` or `70000`: an error says the port must be between
      1 and 65535.
- [ ] C3.3 Paste a full URL such as `http://127.0.0.1:8642/` into the
      host field and connect: it is accepted.

### C4. Connect to a real Hermes API server

- [ ] C4.1 Enter the host, port and token. Press Connect. The dot turns
      amber, then green, and the text shows the server version.
- [ ] C4.2 If it does not connect although the same host answers
      `curl http://<host>:<port>/health`, open the WebView developer
      tools if available and note any CORS error. This is open question
      1 in the groundwork document; report exactly what the console
      says.
- [ ] C4.3 With a non-loopback host over `http`, the note under the
      status line contains a warning about the unencrypted token.
- [ ] C4.4 With an empty token, the note warns that no token is set.
- [ ] C4.5 With a wrong token, connecting fails or the session list
      fails with a 401 message. Note which. (A green dot with a bad
      token is a known gap, sub-issue 4.)

### C5. Sessions and chat

- [ ] C5.1 The session list fills. Sessions you created from another
      client appear.
- [ ] C5.2 Click a session: its history loads.
- [ ] C5.3 "New session", type a message, send: the reply appears
      incrementally, not all at once.
- [ ] C5.4 After the reply, the session list shows the new session.
- [ ] C5.5 Send a long prompt and let it idle more than 10 seconds
      mid-run (for example one that uses a slow tool): the stream does
      not break on keepalives.

### C6. Approvals

- [ ] C6.1 The note under the status line says whether this server
      advertises approval support. Write down which sentence you see.
- [ ] C6.2 If advertised: ask for something that needs approval. A
      prompt appears with the command and the choices. "once" lets the
      run continue; repeat and choose "deny", and the run reports the
      denial.
- [ ] C6.3 If not advertised: no prompt appears, and the note says so
      plainly.

### C7. Health indicator and reconnect

- [ ] C7.1 While connected, stop the Hermes API server (or block the
      port). Within about 15 seconds the dot turns red and the text
      reads "Connection lost. Retrying in N s."
- [ ] C7.2 The retry interval grows (1, 2, 4, 8 ... up to 30 seconds).
- [ ] C7.3 Start the server again. The dot returns to green without
      pressing Connect.
- [ ] C7.4 Change the host to something else and press Connect while
      the old server is down: the status follows the new connection
      only.

### C8. Persistence

- [ ] C8.1 Close the app and reopen it: scheme, host, port and token
      are filled in as saved. (The token is stored unencrypted in the
      WebView profile for now; moving it to Windows Credential Manager
      is milestone M2.)
- [ ] C8.2 The saved settings live under
      `%LOCALAPPDATA%\com.catduckgnaf.hermes-legal\`. Confirm the folder
      name matches the identifier.

### C9. Exit and uninstall

- [ ] C9.1 Close the window. In Task Manager no `hermes-legal` or
      orphaned child process remains after a few seconds.
- [ ] C9.2 Uninstall from "Installed apps". The Start menu entry is
      gone.

## What to report back

- The step numbers that failed, with the exact message shown.
- For C4.2, the developer console text.
- For C6.1, which approval sentence appeared.
- The Hermes agent version shown in the status line.
