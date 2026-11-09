# Desktop shell

Tauri 2 shell + Python sidecar. See [../docs/desktop.md](../docs/desktop.md) for the decision, the editing stack, and the Linux (AppImage, deb, Flatpak) and Windows (signed NSIS/MSI, winget) packaging plan. The Hermes plugin and local dashboard ship first; the shell is the v1 packaging of the same Python core, not a rewrite.

Layout:

- `src-tauri/` — Tauri 2 scaffold (`tauri.conf.json`, `Cargo.toml`, `src/main.rs`, `src/lib.rs`, capabilities, icons, sidecar staging notes in `src-tauri/binaries/README.md`)
- `dist/` — frontend placeholder shown before the Python sidecar answers
- `flatpak/` — Flatpak manifest with documented permissions
- `winget/` — winget manifest set for the signed Windows installers
- `packaging.md` — build, signing secrets, update, and release checklist

Builds run through the manually triggered desktop workflow; see `packaging.md` before treating any artifact as a release.
