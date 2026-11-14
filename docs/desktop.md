# Desktop: Linux and Windows

## Decision
The standalone product is **Tauri 2 + a Python sidecar**. Hermes Desktop itself
is Electron, and if Hermes Legal lived only inside Hermes Desktop, Electron
would be the answer; as a standalone product for solo and small-firm hardware,
Tauri's 3-10 MB shell against Electron's 85-150 MB, roughly half the memory,
Rust capability permissions for privileged files, and built-in signed updater
win. The Python sidecar is not optional either way: eyecite, python-docx,
Docassemble patterns and Whisper all live in Python, and the hermes-finance
codebase pattern is Python.

**Mitigation for WebView variance:** the document of record is never rendered by
raw WebView layout. Rendering of record happens in ONLYOFFICE / LibreOffice /
PDF.js at pinned versions, with a visual-regression fidelity corpus in CI on
both operating systems (numbering, footnotes, tables, tracked changes, comments).

## Editing stack
- **ONLYOFFICE** (AGPL-3.0, OOXML-native) for in-app DOCX editing.
- **LibreOffice headless** (MPL-2.0) for DOCX to PDF conversion and as the
  fallback editor ("Open in LibreOffice / Word").
- **python-docx + direct OOXML patching** for AI redlines and templates.
- **PDF.js** to render, **pdf-lib** to write: annotations, Bates stamps, form
  fields. Redaction rebuilds the page content — drawing a black box over text
  is not redaction, and the app verifies by re-extracting text afterward.
- **Native Tesseract** for OCR (the WASM build is far too slow on long scans).
- TipTap / Lexical are used only for in-app notes and the Ask composer. They do
  not round-trip DOCX track changes as OOXML, so they are never the editor of
  record.

## Packaging
- Linux: AppImage, `.deb`, Flatpak. Declare and document the network permission
  (local model servers and opt-in connectors) for Flathub review.
- Windows: signed NSIS/MSI (budget for a code-signing certificate or Azure
  Trusted Signing from day one — unsigned legal software will not survive
  SmartScreen), plus a `winget` manifest.
- File associations for `.docx` and `.pdf`, "Open Folder as Matter", drag and
  drop, recent matters, a `hermes-legal://` deep link, and a folder watcher that
  writes conflict copies rather than ever overwriting silently.

### What is scaffolded now

The Tauri 2 scaffold lives in `desktop/src-tauri/` and is configuration
and source, not a compiled deliverable in pull request CI:

- `tauri.conf.json` declares the bundle targets (`nsis`, `msi`,
  `appimage`, `deb`), the Python sidecar under `bundle.externalBin`, the
  `.docx` and `.pdf` file associations above, and the signed updater
  endpoint. The identifier and package names stay `hermes-legal` /
  `hermes_legal`; this is packaging, not a rename.
- `src/lib.rs` starts the sidecar as `legal serve --port 8770` (loopback
  only) and keeps the shell usable, with an explanation on screen, when
  the sidecar cannot start — the CLI, MCP server and dashboard never depend on
  the shell.
- `capabilities/default.json` lets the shell execute exactly the bundled
  sidecar and nothing else.
- `desktop/flatpak/` holds the Flatpak manifest; every permission,
  including `--share=network`, is justified in its README for Flathub
  review.
- `desktop/winget/` holds the winget manifest set for the signed NSIS
  and MSI installers. Installer hashes are added at publish time from
  the real signed artifacts.
- `.github/workflows/desktop.yml` builds the shell on `windows-latest`
  and `ubuntu-latest`. It is dispatched by hand only, so it never gates
  a pull request.

### Signing and updates

Code signing is a hard release requirement, and no signing material is
committed to this repository — no certificate, no private key, and no
placeholder value standing in for one. Release builds read the
certificate or Azure Trusted Signing configuration, and the Tauri
updater signing key, from repository secrets; the full list is in
`desktop/packaging.md`. A build without those secrets is unsigned, is
for smoke testing only, and is never published. Updates are signed on
both platforms and verified by the shell against the updater public key
before they are applied.

### Acceptance status

Issue #7 accepts this work when installers build in CI for both
platforms and a clean install on each platform passes `legal doctor`
and opens the demo matter. The scaffold and the manually triggered
workflow are the first step; the remaining steps — a real per-target
sidecar executable, signing secrets configured, signed update
verification, and the clean-install checks — are tracked in the
checklist in `desktop/packaging.md` and are not claimed here.
