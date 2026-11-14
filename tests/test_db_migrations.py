"""Central migration list: legacy databases upgrade, data survives."""
import sqlite3

from hermes_legal import db

# The version-1 schema, copied from the founding commit's db.py: deadlines
# without the confirmation columns, ai_log without a model column, and no
# citation_attestations or ceiling_raises tables. A database built this way
# is what the old ad hoc ALTER TABLE checks existed to upgrade.
OLD_SCHEMA = """
CREATE TABLE matters (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  client_ref TEXT NOT NULL DEFAULT '',
  folder TEXT NOT NULL,
  privacy_ceiling TEXT NOT NULL DEFAULT 'LOCAL_ONLY',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  path TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE deadlines (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER NOT NULL REFERENCES matters(id),
  due_at TEXT NOT NULL,
  title TEXT NOT NULL,
  rule_source TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE citations (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  raw TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unverified',
  resolver TEXT NOT NULL DEFAULT '',
  checked_at TEXT
);
CREATE TABLE ai_log (
  id INTEGER PRIMARY KEY,
  matter_id INTEGER,
  provider TEXT NOT NULL,
  tier TEXT NOT NULL,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE credentials (
  id INTEGER PRIMARY KEY,
  connector TEXT NOT NULL,
  secret TEXT
);
"""


def build_old_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("PRAGMA user_version=1")
    conn.execute(
        "INSERT INTO matters (name, folder) VALUES ('Legacy Matter', '/tmp/legacy')")
    conn.execute(
        "INSERT INTO ai_log (matter_id, provider, tier, action) "
        "VALUES (1, 'local', 'LOCAL_ONLY', 'summarize')")
    conn.execute(
        "INSERT INTO deadlines (matter_id, due_at, title, verified) "
        "VALUES (1, '2026-01-15', 'Legacy deadline', 1)")
    conn.commit()
    conn.close()


def columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_legacy_database_upgrades_and_data_survives(tmp_path):
    path = tmp_path / "legal.db"
    build_old_database(path)
    conn = db.connect(path)
    assert conn.execute("SELECT name FROM matters").fetchall() == [("Legacy Matter",)]
    assert conn.execute(
        "SELECT provider, model FROM ai_log").fetchall() == [("local", "")]
    assert conn.execute(
        "SELECT title, status, confirmed_by FROM deadlines").fetchall() == [
        ("Legacy deadline", "confirmed", "")]
    # Tables the old schema did not have are created by the base migration.
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"citation_attestations", "ceiling_raises", "schema_migrations"} <= tables
    recorded = [row[0] for row in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version")]
    assert recorded == [version for version, _desc, _fn in db.MIGRATIONS]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_migrations_are_recorded_once_and_idempotent(tmp_path):
    path = tmp_path / "legal.db"
    db.connect(path).close()
    conn = db.connect(path)
    recorded = conn.execute(
        "SELECT version, description FROM schema_migrations ORDER BY version").fetchall()
    assert [row[0] for row in recorded] == [v for v, _d, _f in db.MIGRATIONS]
    assert all(row[1] for row in recorded)
    assert db.SCHEMA_VERSION == db.MIGRATIONS[-1][0]


def test_fresh_database_gets_current_columns(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    assert "model" in columns(conn, "ai_log")
    for name in ("status", "kind", "confirmed_by", "second_confirmer",
                 "confirmed_at", "source_excerpt", "rule_id", "calculation_json"):
        assert name in columns(conn, "deadlines")
