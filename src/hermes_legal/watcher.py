"""Folder watching for matter workspaces: detect external edits, and
never let a save silently overwrite one.

The watcher is snapshot based and uses only the standard library. A
snapshot records the size, modification time, and SHA-256 hash of every
file in a matter folder. Comparing the folder against its snapshot
reports files that were created, modified, or deleted outside the app.
Content decides: a file whose modification time moved but whose hash is
unchanged is not reported as modified.

When the app is about to write a document whose on-disk content no
longer matches the snapshot (an external edit landed first), the write
does not touch the original. The proposed content is preserved as a
conflict copy next to the original instead, so both versions survive
and a person decides which one wins.
"""
import hashlib
import os
import pathlib
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .matters import ensure_workspace_tables, iter_document_paths, matter_folder


@dataclass(frozen=True)
class FileState:
    """One file as recorded in a snapshot."""

    relative_path: str
    sha256: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class Change:
    """One difference between a matter folder and its snapshot."""

    relative_path: str
    kind: str  # "created", "modified", or "deleted"
    snapshot_sha256: str = ""
    current_sha256: str = ""


@dataclass
class WriteResult:
    """Outcome of a guarded document write."""

    status: str  # "written" or "conflict"
    path: str
    conflict_copy: str = ""
    changes: list = field(default_factory=list)


def hash_file(path):
    """SHA-256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def scan_folder(folder):
    """Current state of every file under a folder, keyed by relative path."""
    root = pathlib.Path(folder)
    states = {}
    for path in iter_document_paths(root):
        try:
            stat = path.stat()
            digest = hash_file(path)
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        states[relative] = FileState(relative, digest, stat.st_size, stat.st_mtime_ns)
    return states


def take_snapshot(conn, matter_id):
    """Replace the stored snapshot for a matter with the folder as it is now.

    Returns the number of files recorded. Raises ValueError when the
    matter does not exist.
    """
    folder = matter_folder(conn, matter_id)
    if folder is None:
        raise ValueError(f"no such matter: {matter_id}")
    ensure_workspace_tables(conn)
    states = scan_folder(folder)
    conn.execute("DELETE FROM document_snapshots WHERE matter_id=?", (matter_id,))
    conn.execute(
        "INSERT INTO document_snapshot_marks (matter_id) VALUES (?) "
        "ON CONFLICT(matter_id) DO UPDATE SET taken_at=datetime('now')",
        (matter_id,),
    )
    conn.executemany(
        "INSERT INTO document_snapshots (matter_id, path, sha256, size, mtime_ns) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (matter_id, state.relative_path, state.sha256, state.size, state.mtime_ns)
            for state in states.values()
        ],
    )
    conn.commit()
    return len(states)


def load_snapshot(conn, matter_id):
    """The stored snapshot for a matter, keyed by relative path."""
    ensure_workspace_tables(conn)
    rows = conn.execute(
        "SELECT path, sha256, size, mtime_ns FROM document_snapshots WHERE matter_id=?",
        (matter_id,),
    ).fetchall()
    return {
        row[0]: FileState(row[0], row[1], row[2], row[3]) for row in rows
    }


def _update_snapshot_entry(conn, matter_id, state):
    ensure_workspace_tables(conn)
    conn.execute(
        "INSERT INTO document_snapshots (matter_id, path, sha256, size, mtime_ns) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(matter_id, path) DO UPDATE SET "
        "sha256=excluded.sha256, size=excluded.size, mtime_ns=excluded.mtime_ns",
        (matter_id, state.relative_path, state.sha256, state.size, state.mtime_ns),
    )
    conn.commit()


def _snapshot_taken(conn, matter_id):
    """Whether a snapshot exists, even one of a folder that was empty."""
    ensure_workspace_tables(conn)
    return conn.execute(
        "SELECT 1 FROM document_snapshot_marks WHERE matter_id=?", (matter_id,)
    ).fetchone() is not None


def _write_atomic(target, data):
    """Replace ``target`` in one step, so a crash cannot leave half a document."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, target)
    except BaseException:
        pathlib.Path(temp_name).unlink(missing_ok=True)
        raise


def detect_changes(conn, matter_id):
    """Compare a matter folder against its snapshot.

    Returns a list of :class:`Change`, sorted by path. A matter with no
    snapshot yet reports no changes: take a snapshot at open time (the
    open functions in ``matters`` do) before relying on detection.
    """
    folder = matter_folder(conn, matter_id)
    if folder is None:
        raise ValueError(f"no such matter: {matter_id}")
    snapshot = load_snapshot(conn, matter_id)
    if not snapshot and not _snapshot_taken(conn, matter_id):
        return []
    current = scan_folder(folder)
    changes = []
    for relative, state in sorted(current.items()):
        before = snapshot.get(relative)
        if before is None:
            changes.append(Change(relative, "created", "", state.sha256))
        elif before.sha256 != state.sha256:
            changes.append(Change(relative, "modified", before.sha256, state.sha256))
    for relative, before in sorted(snapshot.items()):
        if relative not in current:
            changes.append(Change(relative, "deleted", before.sha256, ""))
    return sorted(changes, key=lambda change: change.relative_path)


def _conflict_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def conflict_copy_path(path, stamp=None):
    """A fresh conflict-copy path next to a file; never an existing path."""
    path = pathlib.Path(path)
    stamp = stamp or _conflict_stamp()
    candidate = path.with_name(f"{path.stem}.conflict-{stamp}{path.suffix}")
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.stem}.conflict-{stamp}-{counter}{path.suffix}")
    return candidate


def make_conflict_copy(path, stamp=None):
    """Copy a file to a conflict copy next to it and return the copy's path.

    The original is left exactly as it is. Raises ValueError when the
    file to preserve does not exist.
    """
    path = pathlib.Path(path)
    if not path.is_file():
        raise ValueError(f"not a file: {path}")
    target = conflict_copy_path(path, stamp=stamp)
    shutil.copy2(path, target)
    return target


def preserve_conflict_copies(conn, matter_id, stamp=None):
    """Make a conflict copy of every externally modified document.

    Returns the list of conflict-copy paths created, sorted. Unmodified,
    created, and deleted documents get no copy: a modified document is
    the one where two versions now exist and one could be lost.
    """
    folder = matter_folder(conn, matter_id)
    if folder is None:
        raise ValueError(f"no such matter: {matter_id}")
    root = pathlib.Path(folder)
    copies = []
    for change in detect_changes(conn, matter_id):
        if change.kind != "modified":
            continue
        copies.append(str(make_conflict_copy(root / change.relative_path, stamp=stamp)))
    return sorted(copies)


def write_document(conn, matter_id, relative_path, content):
    """Write a document inside a matter folder, guarded against conflicts.

    If the file on disk still matches the snapshot (or does not exist yet),
    the content is written atomically and the snapshot entry is updated. If
    the file changed or appeared externally since the snapshot, it is not
    touched:
    the proposed content lands in a conflict copy instead, and the
    returned result has status ``conflict`` and names that copy.
    """
    folder = matter_folder(conn, matter_id)
    if folder is None:
        raise ValueError(f"no such matter: {matter_id}")
    root = pathlib.Path(folder).resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"document path escapes the matter folder: {relative_path}")
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    relative = target.relative_to(root).as_posix()
    snapshot = load_snapshot(conn, matter_id)
    before = snapshot.get(relative)
    if target.is_file():
        # A file the snapshot has never seen was created outside the app, so
        # it is someone's work just as much as an edited file is.
        current_hash = hash_file(target)
        expected = before.sha256 if before is not None else None
        if current_hash != expected and current_hash != hash_bytes(data):
            copy_path = conflict_copy_path(target)
            copy_path.write_bytes(data)
            return WriteResult(
                status="conflict",
                path=str(target),
                conflict_copy=str(copy_path),
                changes=[Change(relative, "modified" if before else "created",
                                before.sha256 if before else "", current_hash)],
            )
    _write_atomic(target, data)
    stat = target.stat()
    _update_snapshot_entry(
        conn, matter_id, FileState(relative, hash_file(target), stat.st_size, stat.st_mtime_ns)
    )
    return WriteResult(status="written", path=str(target))


class MatterWatcher:
    """A small polling watcher over one matter folder.

    Polling (rather than an operating-system event hook) keeps the
    watcher identical on Linux and Windows and fully testable offline.
    """

    def __init__(self, conn, matter_id):
        if matter_folder(conn, matter_id) is None:
            raise ValueError(f"no such matter: {matter_id}")
        self.conn = conn
        self.matter_id = matter_id

    def snapshot(self):
        return take_snapshot(self.conn, self.matter_id)

    def poll(self):
        """Changes since the snapshot, without taking a new one."""
        return detect_changes(self.conn, self.matter_id)

    def poll_and_preserve(self, stamp=None):
        """Changes since the snapshot, plus conflict copies of modified files."""
        changes = self.poll()
        copies = preserve_conflict_copies(self.conn, self.matter_id, stamp=stamp)
        return changes, copies
