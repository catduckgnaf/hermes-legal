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
