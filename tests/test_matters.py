import pathlib

import pytest

from hermes_legal import db, matters

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _conn(tmp_path):
    return db.connect(tmp_path / "legal.db")


def _folder(tmp_path, name="matter", files=None):
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    for relative, content in (files or {}).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    return folder


def test_open_folder_creates_matter_with_local_only_default(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path, files={"complaint.docx": b"fake"})
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    rows = matters.list_matters(conn)
    assert rows[0][0] == mid
    assert rows[0][1] == "Demo"
    assert rows[0][3] == "LOCAL_ONLY"
    assert rows[0][4] == "open"


def test_open_folder_rejects_missing_and_file_paths(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        matters.open_folder_as_matter(conn, tmp_path / "missing")
    a_file = tmp_path / "a.docx"
    a_file.write_bytes(b"x")
    with pytest.raises(ValueError):
        matters.open_folder_as_matter(conn, a_file)


def test_reopening_a_folder_returns_same_matter_without_duplicate(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path)
    first = matters.open_folder_as_matter(conn, folder, "Demo")
    second = matters.open_folder_as_matter(conn, folder)
    assert first == second
    assert len(matters.list_matters(conn)) == 1


def test_open_file_as_matter_uses_containing_folder_and_remembers_file(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(
        tmp_path, files={"brief.docx": b"brief", "exhibit.pdf": b"pdf"}
    )
    mid = matters.open_file_as_matter(conn, folder / "brief.docx")
    matter = matters.get_matter(conn, mid)
    assert matter["folder"] == str(folder.resolve())
    assert matter["opened_files"] == [str((folder / "brief.docx").resolve())]
    assert matters.list_documents(conn, mid) == ["brief.docx", "exhibit.pdf"]


def test_open_file_rejects_missing_and_folder_paths(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        matters.open_file_as_matter(conn, tmp_path / "missing.docx")
    with pytest.raises(ValueError):
        matters.open_file_as_matter(conn, tmp_path)


def test_open_as_matter_dispatches_files_folders_and_deep_links(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path, files={"note.md": "hi"})
    by_folder = matters.open_as_matter(conn, folder)
    by_file = matters.open_as_matter(conn, folder / "note.md")
    link = f"hermes-legal://open?path={folder}"
    by_link = matters.open_as_matter(conn, link)
    assert by_folder == by_file == by_link
    with pytest.raises(ValueError):
        matters.open_as_matter(conn, tmp_path / "missing")


def test_parse_deep_link_variants(tmp_path):
    folder = _folder(tmp_path)
    assert matters.parse_deep_link(f"hermes-legal://open?path={folder}") == str(folder)
    assert matters.parse_deep_link(f"hermes-legal://matter/open?path={folder}") == str(folder)
    assert matters.parse_deep_link("https://example.invalid/open") is None
    assert matters.parse_deep_link(str(folder)) is None
    with pytest.raises(ValueError):
        matters.parse_deep_link("hermes-legal://open")


def test_open_matter_rejects_unknown_privacy_ceiling(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path)
    with pytest.raises(ValueError):
        matters.open_folder_as_matter(conn, folder, privacy_ceiling="BLOCKED")
    mid = matters.open_folder_as_matter(conn, folder, privacy_ceiling="ZERO_RETENTION")
    assert matters.list_matters(conn)[0][3] == "ZERO_RETENTION"
    assert mid


def test_recent_matters_are_ordered_by_latest_open(tmp_path):
    conn = _conn(tmp_path)
    first = matters.open_folder_as_matter(conn, _folder(tmp_path, "first"), "First")
    second = matters.open_folder_as_matter(conn, _folder(tmp_path, "second"), "Second")
    assert [row[0] for row in matters.recent_matters(conn)] == [second, first]
    matters.open_folder_as_matter(conn, _folder(tmp_path, "first"))
    recent = matters.recent_matters(conn)
    assert [row[0] for row in recent] == [first, second]
    assert recent[0][6] == 2  # open count for the reopened matter
    assert recent[0][5]  # a last-opened timestamp is recorded


def test_recent_matters_persist_across_connections_and_honor_limit(tmp_path):
    db_path = tmp_path / "legal.db"
    conn = db.connect(db_path)
    ids = [
        matters.open_folder_as_matter(conn, _folder(tmp_path, f"m{i}"), f"M{i}")
        for i in range(3)
    ]
    conn.close()
    reopened = db.connect(db_path)
    assert [row[0] for row in matters.recent_matters(reopened)] == list(reversed(ids))
    assert [row[0] for row in matters.recent_matters(reopened, limit=2)] == list(
        reversed(ids)
    )[:2]
    assert matters.recent_matters(reopened, limit=0) == []
    with pytest.raises(ValueError):
        matters.recent_matters(reopened, limit=-1)


def test_document_listing_is_live_sorted_and_nested(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(
        tmp_path,
        files={"b.md": "b", "sub/a.docx": b"a", "sub/deep/c.pdf": b"c"},
    )
    mid = matters.open_folder_as_matter(conn, folder)
    assert matters.list_documents(conn, mid) == ["b.md", "sub/a.docx", "sub/deep/c.pdf"]
    # A file created after the matter was opened is listed without re-adding.
    (folder / "late.txt").write_text("late")
    assert "late.txt" in matters.list_documents(conn, mid)


def test_document_records_carry_kind_size_and_path(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path, files={"brief.docx": b"12345", "notes": "abc"})
    mid = matters.open_folder_as_matter(conn, folder)
    records = {r["relative_path"]: r for r in matters.list_document_records(conn, mid)}
    assert records["brief.docx"]["kind"] == "docx"
    assert records["brief.docx"]["size"] == 5
    assert records["brief.docx"]["path"] == str((folder / "brief.docx").resolve())
    assert records["notes"]["kind"] == "file"
    assert records["notes"]["size"] == 3


def test_list_documents_for_unknown_matter_is_empty(tmp_path):
    conn = _conn(tmp_path)
    assert matters.list_documents(conn, 9999) == []
    assert matters.list_document_records(conn, 9999) == []
    assert matters.get_matter(conn, 9999) is None


def test_get_matter_payload_includes_documents_and_metadata(tmp_path):
    conn = _conn(tmp_path)
    folder = _folder(tmp_path, files={"intake.md": "hi"})
    mid = matters.open_folder_as_matter(conn, folder, "Intake")
    matter = matters.get_matter(conn, mid)
    assert matter["name"] == "Intake"
    assert matter["privacy_ceiling"] == "LOCAL_ONLY"
    assert [d["relative_path"] for d in matter["documents"]] == ["intake.md"]


def test_demo_matter_lists_its_documents_from_disk(tmp_path):
    conn = _conn(tmp_path)
    mid = matters.open_folder_as_matter(
        conn, REPO_ROOT / "demo_matter", "Demo — Alvarez (fictional)"
    )
    documents = matters.list_documents(conn, mid)
    assert "README.md" in documents
    assert "intake.md" in documents
