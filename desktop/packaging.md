# Packaging

How the desktop installers are built, signed, and published. The shell
is Tauri 2 with the Python core as a sidecar; the layout in this
repository is:

- `src-tauri/` — the Tauri scaffold: `tauri.conf.json` (bundle targets,
  sidecar, file associations, updater endpoint), `Cargo.toml`,
  `src/main.rs` and `src/lib.rs` (the shell starts the sidecar), and
  `capabilities/default.json` (the sidecar is the only program the shell
  may execute).
- `dist/` — the desktop client frontend: plain HTML, CSS and
  JavaScript that connects to the Hermes API server the user
  configured (see `README.md` and `PROTOCOL.md` in this directory).
- `flatpak/` — the Flatpak manifest and its permission justifications.
- `winget/` — the winget manifest set for the signed Windows installers.
- `.github/workflows/desktop.yml` — the desktop build: pull-request
  tests and Windows smoke build, plus the manually triggered full
  build.

## Bundle targets

| Platform | Targets | Where they are declared |
|---|---|---|
| Windows | NSIS installer, MSI installer | `bundle.targets` in `src-tauri/tauri.conf.json` |
| Linux | AppImage, `.deb` | `bundle.targets` in `src-tauri/tauri.conf.json` |
| Linux (sandboxed) | Flatpak | `flatpak/com.catduckgnaf.hermeslegal.json` |

The Hermes plugin and the local dashboard remain fully usable without
the shell. Packaging never becomes a requirement for the Python core.

## Building

The desktop workflow (`.github/workflows/desktop.yml`) runs on pull
requests that touch `desktop/**`: the client tests against the mock
Hermes server, and an unsigned Windows build
(`cargo tauri build --bundles nsis,msi`) for smoke. The full build is
dispatched by hand (`workflow_dispatch`): it builds the shell on
`windows-latest` and `ubuntu-latest` and uploads the bundle artifacts
for smoke testing.

Two build inputs are still scaffold placeholders, and artifacts built
with them are never a release:

- The sidecar file is staged as a placeholder with the target-triple
  name Tauri expects. Packaging the Python core as one executable per
  target replaces it.
- The updater public key in `tauri.conf.json` is empty, and the shell
  does not register the updater plugin yet (see `src/lib.rs`). Both land
  with the first signed release, when the key exists.

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
artifacts are for smoke testing only and are never published, never
submitted to winget or Flathub, and never attached to a release.

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

The manifest requests `--share=network` and `--filesystem=home`; both
are justified in `flatpak/README.md` for Flathub review. In short:
network reaches the user's own local model servers and the connectors
the user opts into per matter (nothing is sent by default), and home
access is what opening a folder as a matter means in this product.
Narrowing home access to per-folder portal grants is follow-up work,
as is wiring the full Rust and Python build into `flatpak-builder`
modules.

## Checklist

- [x] Tauri 2 scaffold with the Python sidecar configured
- [x] NSIS, MSI, AppImage, and `.deb` bundle targets declared
- [x] Flatpak manifest with the network permission documented and justified
- [x] winget manifest set for the signed installers
- [x] Desktop workflow: manually triggered full build for Windows and Linux, plus pull-request client tests and an unsigned Windows build
- [ ] Windows code-signing certificate or Azure Trusted Signing secret configured
- [ ] Updater signing key generated, public key committed, updater plugin registered
- [ ] Python core packaged as a real per-target sidecar executable
- [ ] Signed auto-update bundles verified on both platforms
- [ ] Clean Windows install and clean Linux install pass `legal doctor` and open the demo matter
- [ ] Fidelity corpus rendered and compared on Windows and Linux in CI
