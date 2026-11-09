# Flatpak packaging

Manifest: `com.catduckgnaf.hermeslegal.json` (JSON form so the packaging
tests can parse it with the Python standard library).

## Permissions and why each one is requested

Flathub review requires every permission to be justified. The manifest
requests exactly these `finish-args`:

- `--share=network` — **required, and the one reviewers will ask about.**
  hermes-legal is local-first: the default LOCAL-ONLY tier talks only to
  model servers on this machine or the local network (Ollama, LM Studio).
  The opt-in tiers and connectors (CourtListener, govinfo, Microsoft
  Graph, Google Workspace) are named per matter by the user and also need
  the network. Without network access the application cannot reach even
  the user's own local model server, because Flatpak's sandbox loopback
  isolation still applies to the shared network namespace permission.
  Nothing is sent anywhere by default; the permission enables connections
  the user configures, it does not create any.
- `--filesystem=home` — matters are ordinary folders on the user's own
  computer; opening a folder as a matter is the core workflow. This is
  broader than a portal-only design, and it is deliberate for v1: the
  folder watcher and conflict-copy behavior operate on matter folders the
  user already opened. Narrowing this to per-folder portal grants is
  follow-up work, recorded in `desktop/packaging.md`.
- `--socket=wayland` and `--socket=fallback-x11` — the Tauri shell renders
  through the system WebView and needs a display socket on both display
  stacks.
- `--share=ipc` and `--device=dri` — WebView rendering support (shared
  memory and GPU acceleration) so long documents stay responsive on
  modest hardware.

## Build status

This is a scaffold manifest: the module copies the built shell and
sidecar binaries into `/app`. Wiring the full Rust and Python build into
`flatpak-builder` modules, and the Flathub submission itself, are
follow-up work named in `desktop/packaging.md`. No Flathub listing is
claimed until that work lands and a clean install passes the acceptance
checks in issue #7.
