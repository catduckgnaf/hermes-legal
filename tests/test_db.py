from hermes_legal import db, matters
import pathlib

def test_matter_roundtrip(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"; folder.mkdir()
    (folder / "complaint.docx").write_bytes(b"fake")
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    assert matters.list_matters(conn)[0][1] == "Demo"
    assert matters.list_documents(conn, mid) == ["complaint.docx"]

def test_redaction():
    assert db.redact_row({"secret": "x", "name": "y"}) == {"secret": None, "name": "y"}


def test_readonly_connection_returns_null_for_credentials(tmp_path):
    path = tmp_path / "with space" / "legal.db"
    path.parent.mkdir()
    conn = db.connect(path)
    conn.execute("INSERT INTO credentials (connector, secret) VALUES ('clio', 'hunter2')")
    conn.commit()
    conn.close()
    readonly = db.connect_readonly(path)
    assert readonly.execute("SELECT connector, secret FROM credentials").fetchall() == [("clio", None)]
    assert readonly.execute("SELECT * FROM credentials").fetchall() == [(1, "clio", None)]


def test_readonly_connection_refuses_writes(tmp_path):
    import pytest
    import sqlite3
    path = tmp_path / "legal.db"
    db.connect(path).close()
    readonly = db.connect_readonly(path)
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("INSERT INTO credentials (connector) VALUES ('x')")
