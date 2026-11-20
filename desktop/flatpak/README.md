# Flatpak packaging

Manifest: `com.catduckgnaf.hermes-legal.json` (JSON form so the packaging
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
- No filesystem permission. The desktop app is a thin client for a
  running Hermes agent (issue #34): it reads and writes no user files,
  so the earlier `--filesystem=home` grant was removed. If a later
  feature needs file access, use the file chooser portal instead of a
  static grant.
- `--socket=wayland` and `--socket=fallback-x11` — the Tauri shell renders
  through the system WebView and needs a display socket on both display
  stacks.
- `--share=ipc` and `--device=dri` — WebView rendering support (shared
  memory and GPU acceleration) so long documents stay responsive on
  modest hardware.

## Build status

This is a scaffold manifest: the module copies the built shell
binary into `/app`. Wiring the full Rust build into
`flatpak-builder` modules, and the Flathub submission itself, are
follow-up work named in `desktop/packaging.md`. No Flathub listing is
claimed until that work lands and a clean install passes the acceptance
checks in issue #7.

## App identifier

The Flatpak app id is `com.catduckgnaf.hermes-legal`, the same string as
the Tauri `identifier` in `src-tauri/tauri.conf.json`. Earlier scaffolds
used `com.catduckgnaf.hermeslegal` here; nothing was published under
that id. `desktop/tests/packaging.test.mjs` fails if the two drift.
