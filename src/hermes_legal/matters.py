"""A matter is an ordinary folder plus a row of metadata. Files stay files:
no import into a proprietary store, no silent overwrite."""
import pathlib

def open_folder_as_matter(conn, folder, name=None):
    folder = pathlib.Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"not a folder: {folder}")
    cur = conn.execute("INSERT INTO matters (name, folder) VALUES (?, ?)",
                       (name or folder.name, str(folder)))
    conn.commit()
    return cur.lastrowid

def list_matters(conn):
    return conn.execute("SELECT id, name, folder, privacy_ceiling, status FROM matters ORDER BY id").fetchall()

def list_documents(conn, matter_id):
    folder = conn.execute("SELECT folder FROM matters WHERE id=?", (matter_id,)).fetchone()
    if not folder: return []
    root = pathlib.Path(folder[0])
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
