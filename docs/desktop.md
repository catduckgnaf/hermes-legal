# Desktop: Linux and Windows

## Decision
The standalone product is **Tauri 2 + a Python sidecar**. Hermes Desktop itself
is Electron, and if hermes-legal lived only inside Hermes Desktop, Electron
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
