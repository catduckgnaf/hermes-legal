# Packaging

How the desktop installers are built, signed, and published. The app is
a Tauri 2 thin client for a running Hermes agent. It bundles no Python
sidecar and has no shell permission. The layout in this repository is:

- `src-tauri/` — the Tauri shell: `tauri.conf.json` (Windows and Linux
  bundle targets, no file associations, no updater block), `Cargo.toml`,
  `src/main.rs`, `src/lib.rs` and `src/credentials.rs` (the window plus
  `token_get` and `token_set`), and `capabilities/default.json` (core
  window access and those two commands only).
- `dist/` — the desktop client frontend: plain HTML, CSS and JavaScript
  that connects to the Hermes API server the user configured (see
  `README.md` and `PROTOCOL.md` in this directory).
- `flatpak/` — the Flatpak manifest and its permission justifications.
  The manifest is not built in CI.
- `winget/` — the winget manifest set for the signed Windows installers.
- `.github/workflows/desktop.yml` — pull-request tests, an unsigned
  Windows build with a silent NSIS install check, an unsigned Linux
  build, and the manually triggered full build.

## Bundle targets

| Platform | Targets | Where they are declared |
|---|---|---|
| Windows | NSIS installer, MSI installer | `bundle.targets` in `src-tauri/tauri.conf.json` |
| Linux | AppImage, `.deb` | `bundle.targets` in `src-tauri/tauri.conf.json` |
| Linux (sandboxed) | Flatpak | `flatpak/com.catduckgnaf.hermes-legal.json` |

The CLI, the MCP server and the local dashboard remain fully usable
without the shell. Packaging never becomes a requirement for the Python
core.

## Building

The desktop workflow (`.github/workflows/desktop.yml`) runs on pull
requests that touch `desktop/**`: the client tests against the mock
Hermes server, an unsigned Windows build
(`cargo tauri build --bundles nsis,msi`) that silent-installs, launches
and uninstalls the NSIS package, and an unsigned Linux build
(`cargo tauri build --bundles deb,appimage`). The full build is
dispatched by hand (`workflow_dispatch`): it builds the shell on
`windows-latest` and `ubuntu-latest` and uploads the bundle artifacts
for smoke testing.

The updater is not configured. `tauri.conf.json` has no updater block
and the shell does not register the updater plugin. Both land with the
first signed release, when a real public key exists. An empty public
key is not committed in its place.

## Code signing: required secrets, nothing committed

Signing is not optional for this product: unsigned legal software will
not survive Windows SmartScreen, and Tauri updates are only installed
after signature verification. No certificate, private key, or
placeholder signing value is committed to this repository. Release
builds take all signing material from repository secrets:

| Secret | Used for |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | Signing update bundles on both platforms (Tauri updater) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Password for the updater signing key |
| `WINDOWS_CERTIFICATE` | Windows code-signing certificate (base64 PFX) for NSIS/MSI |
| `WINDOWS_CERTIFICATE_PASSWORD` | Password for the Windows certificate |
| `AZURE_TRUSTED_SIGNING_ENDPOINT` | Azure Trusted Signing endpoint, when used instead of a certificate file |

The matching updater public key is the only signing value that is ever
committed, and only once the real key exists: a public key is not a
secret, but a made-up one would break update verification for every
user, so the field stays empty until then.

A build whose signing secrets are absent is unsigned. Unsigned
artifacts are never published as a signed release and are never
submitted to winget or Flathub. An unsigned preview may be attached to
a GitHub release that says so in the title. The 0.1.0 preview is
[desktop-v0.1.0](https://github.com/catduckgnaf/hermes-legal/releases/tag/desktop-v0.1.0).
That preview is not a signed release.

## Updates

- The updater endpoint in `tauri.conf.json` points at the `latest.json`
  of the latest GitHub release. Each release publishes signed update
  bundles for both platforms next to the installers.
- The shell verifies the signature against the committed public key
  before applying an update; a failed verification is a hard stop, not
  a warning.
- `legal doctor` and the demo matter are the acceptance smoke checks: a
  clean install on each platform passes `legal doctor` and opens the
  demo matter before that release is announced.

## winget

The manifest set in `winget/` describes the signed NSIS and MSI
installers. `InstallerSha256` is computed from the signed artifacts and
added at publish time; it is absent from the scaffold on purpose,
because a hash committed before the artifact exists would be a
fabricated value. Submission to microsoft/winget-pkgs is part of the
release process once a signed release exists.

## Flatpak

The manifest requests `--share=network` and no filesystem access; the
permissions are justified in `flatpak/README.md` for Flathub review.
The desktop app is a thin client for a running Hermes agent, so it
needs the network to reach that agent and nothing from the home
directory. The app id matches the Tauri identifier,
`com.catduckgnaf.hermes-legal`.

## Checklist

- [x] Tauri 2 scaffold (thin client, no sidecar; see the note at the top)
- [x] NSIS, MSI, AppImage, and `.deb` bundle targets declared
- [x] Flatpak manifest with the network permission documented and justified
- [x] winget manifest set for the signed installers
- [x] Desktop workflow: manually triggered full build for Windows and Linux, plus pull-request client tests and an unsigned Windows build
- [ ] Windows code-signing certificate or Azure Trusted Signing secret configured
- [ ] Updater signing key generated, public key committed, updater plugin registered
- [ ] Signed auto-update bundles verified on both platforms
- [ ] Clean Windows install and clean Linux install pass `legal doctor` and open the demo matter
- [ ] Fidelity corpus rendered and compared on Windows and Linux in CI
