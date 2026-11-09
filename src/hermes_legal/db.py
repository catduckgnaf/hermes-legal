"""One local SQLite file. Directory 0700, file 0600, WAL, and a read-only
connection for agent tools that redacts credential columns to NULL — the
hermes-finance pattern, applied to matters instead of money."""
import os, sqlite3, pathlib

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS matters (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  client_ref TEXT NOT NULL DEFAULT '',
  folder TEXT NOT NULL,
  privacy_ceiling TEXT NOT NULL DEFAULT 'LOCAL_ONLY',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  path TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS deadlines (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  due_at TEXT NOT NULL,
  title TEXT NOT NULL,
  rule_source TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  raw TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unverified',
  resolver TEXT NOT NULL DEFAULT '',
  checked_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_log (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  provider TEXT NOT NULL,
  tier TEXT NOT NULL,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS credentials (
  id INTEGER PRIMARY KEY,
  connector TEXT NOT NULL,
  secret TEXT
);
"""

def data_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("HERMES_LEGAL_DATA_DIR") or (pathlib.Path.home() / ".local/share/hermes-legal" if os.name != "nt" else pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "hermes-legal"))
    d.mkdir(parents=True, exist_ok=True)
    try: os.chmod(d, 0o700)
    except OSError: pass
    return d

def connect(path=None) -> sqlite3.Connection:
    p = pathlib.Path(path) if path else data_dir() / "legal.db"
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    try: os.chmod(p, 0o600)
    except OSError: pass
    return conn

CREDENTIAL_COLUMNS = ("secret", "token", "api_key")

def connect_readonly(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{pathlib.Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=1")
    def authorizer(action, p1, p2, db, src):
        # SQLITE_IGNORE makes SQLite return NULL for the column, so even
        # SELECT * on an agent connection cannot read a credential.
        if action == sqlite3.SQLITE_READ and p1 == "credentials" and p2 in CREDENTIAL_COLUMNS:
            return sqlite3.SQLITE_IGNORE
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    return conn

def redact_row(row: dict) -> dict:
    """Credential-shaped values never leave a read path."""
    return {k: (None if k in CREDENTIAL_COLUMNS else v) for k, v in row.items()}
