# Getting started

1. Install Python 3.12 and uv.
2. Clone this repository and run `uv sync`.
3. Run `uv run legal doctor` — it works offline and names anything missing.
4. Run `uv run legal demo`, then `uv run legal matter list`.
5. Open a real folder as a matter only when you are ready; the demo matter is fictional.

Access is **this computer only** by default: the app binds loopback and refuses to start on a non-loopback address until you choose a protected access mode in Settings. That fail-closed start is deliberate.

## Matter workspaces

A matter is an ordinary folder on this computer. Opening it records
metadata (name, folder, privacy ceiling, status) in the local database;
the documents themselves stay in place as ordinary files and are listed
from disk every time, never imported into a separate store.

```sh
uv run legal matter open ~/matters/alvarez        # open a folder as a matter
uv run legal matter open ~/matters/alvarez/brief.docx  # open one file (its folder becomes the matter)
uv run legal matter list                          # every matter
uv run legal matter recent                        # matters by most recent open
uv run legal matter documents 1                   # document listing for matter 1, from disk
```

Reopening a folder returns its existing matter instead of creating a
duplicate, and moves it to the top of the recent list. The recent list is
persisted in the local database, so its order survives restarts. A
`hermes-legal://open?path=<path>` deep link opens the same file or folder
through the same code path.

Opening a matter also takes a snapshot of its documents (size, modification
time, and SHA-256 hash). The folder watcher compares the folder against
that snapshot to detect edits made outside the app. When a guarded write
finds that a document changed externally since the snapshot, it never
overwrites that version: the proposed content is saved as a conflict copy
next to the original (for example `brief.conflict-20261109T120000Z.docx`)
and the original is left untouched, so a person decides which version wins.
