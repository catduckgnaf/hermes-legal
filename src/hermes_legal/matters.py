"""A matter is an ordinary folder plus a row of metadata. Files stay files:
no import into a proprietary store, no silent overwrite.

Opening a folder or a single file records the open in a persisted,
append-only log, so the recent-matters list survives restarts and is
ordered by the most recent open, not by creation. Nothing is copied out
of the folder the user opened: the database holds metadata only.
"""
import pathlib
import urllib.parse

from .providers import TIERS

# Privacy ceilings a matter may carry. BLOCKED is a provider tier, never a
# valid ceiling for a matter, so it is excluded here.
MATTER_PRIVACY_CEILINGS = tuple(t for t in TIERS if t != "BLOCKED")

DEEP_LINK_SCHEME = "hermes-legal"

_WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS matter_opens (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  opened_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS matter_open_files (
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  path TEXT NOT NULL,
  opened_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (matter_id, path)
);
CREATE TABLE IF NOT EXISTS document_snapshots (
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  mtime_ns INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (matter_id, path)
);
"""


def ensure_workspace_tables(conn):
    """Create the matter-workspace tables on a connection from ``db``.

    Kept here (rather than in the base schema) so a database created by an
    earlier build gains the tables the first time any workspace function
    runs, with no migration step for the user.
    """
    conn.executescript(_WORKSPACE_SCHEMA)
    conn.commit()


def matter_folder(conn, matter_id):
    """Return the folder for a matter id, or None when there is no such matter."""
    row = conn.execute("SELECT folder FROM matters WHERE id=?", (matter_id,)).fetchone()
    return row[0] if row else None


def _record_open(conn, matter_id):
    ensure_workspace_tables(conn)
    conn.execute("INSERT INTO matter_opens (matter_id) VALUES (?)", (matter_id,))
    conn.commit()


def record_open(conn, matter_id):
    """Record that a matter was opened just now (drives recent matters)."""
    if matter_folder(conn, matter_id) is None:
        raise ValueError(f"no such matter: {matter_id}")
    _record_open(conn, matter_id)


def _find_matter_id(conn, folder):
    row = conn.execute("SELECT id FROM matters WHERE folder=?", (str(folder),)).fetchone()
    return row[0] if row else None


def _create_matter(conn, folder, name, privacy_ceiling):
    if privacy_ceiling is not None and privacy_ceiling not in MATTER_PRIVACY_CEILINGS:
        raise ValueError(
            f"unknown privacy ceiling: {privacy_ceiling!r} "
            f"(choose one of {', '.join(MATTER_PRIVACY_CEILINGS)})"
        )
    if privacy_ceiling is None:
        cur = conn.execute(
            "INSERT INTO matters (name, folder) VALUES (?, ?)",
            (name or folder.name, str(folder)),
        )
    else:
        cur = conn.execute(
            "INSERT INTO matters (name, folder, privacy_ceiling) VALUES (?, ?, ?)",
            (name or folder.name, str(folder), privacy_ceiling),
        )
    conn.commit()
    return cur.lastrowid


def _snapshot(conn, matter_id):
    # Local import: watcher imports helpers from this module.
    from . import watcher

    watcher.take_snapshot(conn, matter_id)


def open_folder_as_matter(conn, folder, name=None, privacy_ceiling=None):
    """Open a folder as a matter and return its matter id.

    Reopening a folder that is already a matter returns the existing
    matter instead of creating a duplicate, and records the new open so
    the folder moves to the top of the recent-matters list. A content
    snapshot is taken at open time; that snapshot is the baseline the
    folder watcher compares against to detect external edits.
    """
    folder = pathlib.Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"not a folder: {folder}")
    ensure_workspace_tables(conn)
    existing = _find_matter_id(conn, folder)
    if existing is not None:
        _record_open(conn, existing)
        return existing
    matter_id = _create_matter(conn, folder, name, privacy_ceiling)
    _record_open(conn, matter_id)
    _snapshot(conn, matter_id)
    return matter_id


def open_file_as_matter(conn, file_path, name=None, privacy_ceiling=None):
    """Open a single file as a matter and return its matter id.

    The file stays where it is. Its containing folder becomes the matter
    folder (so sibling documents are listed with it), and the file itself
    is remembered as an opened file for that matter.
    """
    file_path = pathlib.Path(file_path).expanduser().resolve()
    if not file_path.is_file():
        raise ValueError(f"not a file: {file_path}")
    matter_id = open_folder_as_matter(
        conn, file_path.parent, name=name, privacy_ceiling=privacy_ceiling
    )
    ensure_workspace_tables(conn)
    conn.execute(
        "INSERT INTO matter_open_files (matter_id, path) VALUES (?, ?) "
        "ON CONFLICT(matter_id, path) DO UPDATE SET opened_at=datetime('now')",
        (matter_id, str(file_path)),
    )
    conn.commit()
    return matter_id


def parse_deep_link(uri):
    """Parse a ``hermes-legal://`` deep link into the local path it names.

    Accepts ``hermes-legal://open?path=<path>`` and
    ``hermes-legal://matter/open?path=<path>``. Returns None for anything
    that is not such a link, and raises ValueError for a link in the right
    scheme that carries no usable path. No path is opened by this function;
    it only decodes the link, so a link can never smuggle in an action.
    """
    if not isinstance(uri, str) or not uri.startswith(f"{DEEP_LINK_SCHEME}://"):
        return None
    parsed = urllib.parse.urlparse(uri)
    if parsed.netloc not in ("open", "matter") and parsed.path not in ("/open", ""):
        raise ValueError(f"unsupported deep link: {uri}")
    values = urllib.parse.parse_qs(parsed.query).get("path")
    if not values or not values[0]:
        raise ValueError(f"deep link carries no path: {uri}")
    return values[0]


def open_as_matter(conn, target, name=None, privacy_ceiling=None):
    """Open a folder, a file, or a deep link as a matter; return its id.

    This is the single entry point behind drag and drop, file
    associations, and the ``legal matter open`` command: whatever shape
    the target arrives in, the file or folder on disk is what is opened.
    """
    deep_link_path = parse_deep_link(target)
    if deep_link_path is not None:
        target = deep_link_path
    path = pathlib.Path(target).expanduser().resolve()
    if path.is_dir():
        return open_folder_as_matter(conn, path, name=name, privacy_ceiling=privacy_ceiling)
    if path.is_file():
        return open_file_as_matter(conn, path, name=name, privacy_ceiling=privacy_ceiling)
    raise ValueError(f"not a file or folder: {path}")


# Short alias: opening is the verb every caller reaches for.
open_matter = open_as_matter


def list_matters(conn):
    return conn.execute(
        "SELECT id, name, folder, privacy_ceiling, status FROM matters ORDER BY id"
    ).fetchall()


def recent_matters(conn, limit=10):
    """Matters ordered by most recent open, most recent first.

    Returns the same columns as :func:`list_matters` plus the last-opened
    timestamp and the number of recorded opens. The order is persisted in
    the ``matter_opens`` log, so it is the same after a restart. Matters
    that have never been recorded as opened sort last, newest first.
    """
    ensure_workspace_tables(conn)
    if limit is not None and limit < 0:
        raise ValueError("limit must be zero or greater")
    rows = conn.execute(
        "SELECT m.id, m.name, m.folder, m.privacy_ceiling, m.status, "
        "MAX(o.opened_at) AS last_opened_at, COUNT(o.id) AS open_count, "
        "MAX(o.id) AS last_open_seq "
        "FROM matters m LEFT JOIN matter_opens o ON o.matter_id = m.id "
        "GROUP BY m.id "
        "ORDER BY COALESCE(last_open_seq, 0) DESC, m.id DESC"
    ).fetchall()
    trimmed = rows if limit is None else rows[:limit]
    return [tuple(row[:7]) for row in trimmed]


def opened_files(conn, matter_id):
    """Files opened individually for a matter, as absolute path strings."""
    ensure_workspace_tables(conn)
    rows = conn.execute(
        "SELECT path FROM matter_open_files WHERE matter_id=? ORDER BY path",
        (matter_id,),
    ).fetchall()
    return [row[0] for row in rows]


def _document_kind(path):
    suffix = path.suffix.lower().lstrip(".")
    return suffix or "file"


def iter_document_paths(root):
    """Every file under a matter folder, sorted by relative path."""
    root = pathlib.Path(root)
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: str(p.relative_to(root)),
    )


def list_document_records(conn, matter_id):
    """Document records for a matter, listed live from disk.

    Each record is a dict with ``path`` (absolute), ``relative_path``,
    ``name``, ``kind`` (the file extension, or ``file``), ``size`` in
    bytes, and ``mtime_ns``. This is the listing the ``legal_doc_*`` tool
    definitions describe: ``legal_matter_get`` reports a matter through
    it, and document search and read enumerate their candidates from it,
    so a document that appears on disk is listed without any import step.
    """
    folder = matter_folder(conn, matter_id)
    if folder is None:
        return []
    root = pathlib.Path(folder)
    records = []
    for path in iter_document_paths(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        records.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root)),
                "name": path.name,
                "kind": _document_kind(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return records


def list_documents(conn, matter_id):
    """Relative paths of a matter's documents, listed live from disk."""
    return [record["relative_path"] for record in list_document_records(conn, matter_id)]


def get_matter(conn, matter_id):
    """One matter as a dict: metadata, opened files, and its documents.

    The payload behind the ``legal_matter_get`` tool definition. Returns
    None when there is no matter with that id.
    """
    row = conn.execute(
        "SELECT id, name, folder, privacy_ceiling, status, created_at "
        "FROM matters WHERE id=?",
        (matter_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "folder": row[2],
        "privacy_ceiling": row[3],
        "status": row[4],
        "created_at": row[5],
        "opened_files": opened_files(conn, matter_id),
        "documents": list_document_records(conn, matter_id),
    }
