"""One local SQLite file. Directory 0700, file 0600, WAL, and a read-only
connection for agent tools that redacts credential columns to NULL — the
hermes-finance pattern, applied to matters instead of money."""
import os, sqlite3, pathlib

SCHEMA_VERSION = 3

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
  verified INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'confirmed',
  kind TEXT NOT NULL DEFAULT '',
  confirmed_by TEXT NOT NULL DEFAULT '',
  second_confirmer TEXT NOT NULL DEFAULT '',
  confirmed_at TEXT NOT NULL DEFAULT '',
  source_excerpt TEXT NOT NULL DEFAULT '',
  rule_id TEXT NOT NULL DEFAULT '',
  calculation_json TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  raw TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unverified',
  resolver TEXT NOT NULL DEFAULT '',
  checked_at TEXT
);
CREATE TABLE IF NOT EXISTS citation_attestations (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  citation TEXT NOT NULL,
  citation_class TEXT NOT NULL DEFAULT '',
  attested_by TEXT NOT NULL,
  attested_at TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_log (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  provider TEXT NOT NULL,
  tier TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS credentials (
  id INTEGER PRIMARY KEY,
  connector TEXT NOT NULL,
  secret TEXT
);
CREATE TABLE IF NOT EXISTS ceiling_raises (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  previous_ceiling TEXT NOT NULL,
  new_ceiling TEXT NOT NULL,
  raised_by TEXT NOT NULL,
  consent_note TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def data_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("HERMES_LEGAL_DATA_DIR") or (pathlib.Path.home() / ".local/share/hermes-legal" if os.name != "nt" else pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "hermes-legal"))
    d.mkdir(parents=True, exist_ok=True)
    try: os.chmod(d, 0o700)
    except OSError: pass
    return d

def default_path() -> pathlib.Path:
    return data_dir() / "legal.db"

def _add_column_if_missing(conn, table, name, decl):
    """ALTER TABLE for one column, only when the table lacks it.

    CREATE TABLE IF NOT EXISTS never adds columns to an existing table, so
    column growth is the one job the base schema cannot do on its own. Each
    numbered migration below is written to be safe on a database that
    already carries its change, because a database created by the old ad
    hoc path has no migration record and runs the whole list once.
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _migration_1_base_schema(conn):
    conn.executescript(SCHEMA)


def _migration_2_ai_log_model(conn):
    _add_column_if_missing(conn, "ai_log", "model", "TEXT NOT NULL DEFAULT ''")


# The deadlines confirmation columns, in the order they were added. The
# same set is carried by the base schema for new files; this migration is
# what brings an existing deadlines table up to it.
_DEADLINE_CONFIRMATION_COLUMNS = (
    ("status", "TEXT NOT NULL DEFAULT 'confirmed'"),
    ("kind", "TEXT NOT NULL DEFAULT ''"),
    ("confirmed_by", "TEXT NOT NULL DEFAULT ''"),
    ("second_confirmer", "TEXT NOT NULL DEFAULT ''"),
    ("confirmed_at", "TEXT NOT NULL DEFAULT ''"),
    ("source_excerpt", "TEXT NOT NULL DEFAULT ''"),
    ("rule_id", "TEXT NOT NULL DEFAULT ''"),
    ("calculation_json", "TEXT NOT NULL DEFAULT ''"),
)


def _migration_3_deadline_confirmation_columns(conn):
    for name, decl in _DEADLINE_CONFIRMATION_COLUMNS:
        _add_column_if_missing(conn, "deadlines", name, decl)


# The one numbered migration list. Append-only: never edit or renumber an
# entry that has shipped, add the next number instead. Applied in order by
# apply_migrations and recorded in schema_migrations.
MIGRATIONS = [
    (1, "base schema: core tables", _migration_1_base_schema),
    (2, "ai_log gains a model column", _migration_2_ai_log_model),
    (3, "deadlines gains the confirmation columns",
     _migration_3_deadline_confirmation_columns),
]


def apply_migrations(conn) -> None:
    """Apply every unrecorded migration, in order, and record each one.

    A database created before this list existed has no schema_migrations
    table; it runs the whole list once, which is safe because every
    migration is idempotent, and its existing rows are left untouched.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "description TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for version, description, apply_migration in MIGRATIONS:
        if version in applied:
            continue
        apply_migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (version, description))
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


def connect(path=None) -> sqlite3.Connection:
    p = pathlib.Path(path) if path else default_path()
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA journal_mode=WAL")
    apply_migrations(conn)
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
