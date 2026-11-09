import os

import pytest

from hermes_legal import db, matters, watcher


def _setup(tmp_path, files=None):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    for relative, content in (files or {"doc.md": "original"}).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    return conn, folder, mid


def test_snapshot_taken_at_open_reports_no_changes(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    assert watcher.take_snapshot(conn, mid) == 1
    assert watcher.detect_changes(conn, mid) == []
    assert watcher.MatterWatcher(conn, mid).poll() == []


def test_external_edit_is_detected_as_modified(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    (folder / "doc.md").write_text("edited externally")
    changes = watcher.detect_changes(conn, mid)
    assert [(c.relative_path, c.kind) for c in changes] == [("doc.md", "modified")]
    assert changes[0].snapshot_sha256 != changes[0].current_sha256
    assert changes[0].snapshot_sha256 == watcher.hash_bytes("original")


def test_created_and_deleted_files_are_detected(tmp_path):
    conn, folder, mid = _setup(tmp_path, {"keep.md": "k", "gone.md": "g"})
    (folder / "gone.md").unlink()
    (folder / "new.md").write_text("new")
    kinds = {c.relative_path: c.kind for c in watcher.detect_changes(conn, mid)}
    assert kinds == {"gone.md": "deleted", "new.md": "created"}


def test_touch_without_content_change_is_not_a_modification(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    target = folder / "doc.md"
    target.write_text("original")  # same content, new modification time
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert watcher.detect_changes(conn, mid) == []


def test_make_conflict_copy_preserves_original_and_is_unique(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    (folder / "doc.md").write_text("external version")
    first = watcher.make_conflict_copy(folder / "doc.md", stamp="20261109T120000Z")
    second = watcher.make_conflict_copy(folder / "doc.md", stamp="20261109T120000Z")
    assert first != second
    assert first.read_text() == "external version"
    assert second.read_text() == "external version"
    assert (folder / "doc.md").read_text() == "external version"
    assert "conflict-20261109T120000Z" in first.name


def test_preserve_conflict_copies_for_modified_documents_only(tmp_path):
    conn, folder, mid = _setup(tmp_path, {"a.md": "a", "b.md": "b"})
    (folder / "a.md").write_text("a edited")
    (folder / "c.md").write_text("created, not modified")
    copies = watcher.preserve_conflict_copies(conn, mid, stamp="20261109T120000Z")
    assert len(copies) == 1
    assert copies[0].endswith("a.conflict-20261109T120000Z.md")
    assert (folder / "a.md").read_text() == "a edited"


def test_guarded_write_with_no_conflict_writes_and_updates_snapshot(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    result = watcher.write_document(conn, mid, "doc.md", "app version")
    assert result.status == "written"
    assert (folder / "doc.md").read_text() == "app version"
    # The snapshot moved with the write, so the watcher stays quiet.
    assert watcher.detect_changes(conn, mid) == []
    created = watcher.write_document(conn, mid, "sub/new.md", "new doc")
    assert created.status == "written"
    assert (folder / "sub" / "new.md").read_text() == "new doc"


def test_guarded_write_after_external_edit_makes_conflict_copy_not_data_loss(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    (folder / "doc.md").write_text("external version")
    result = watcher.write_document(conn, mid, "doc.md", "app version")
    assert result.status == "conflict"
    # The external version is untouched; the proposed version survives whole.
    assert (folder / "doc.md").read_text() == "external version"
    assert result.conflict_copy
    assert watcher.hash_file(result.conflict_copy) == watcher.hash_bytes("app version")
    assert result.changes[0].kind == "modified"


def test_guarded_write_of_same_content_as_external_edit_is_not_a_conflict(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    (folder / "doc.md").write_text("same")
    result = watcher.write_document(conn, mid, "doc.md", "same")
    assert result.status == "written"
    assert (folder / "doc.md").read_text() == "same"


def test_guarded_write_refuses_to_escape_the_matter_folder(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    with pytest.raises(ValueError):
        watcher.write_document(conn, mid, "../outside.md", "nope")
    assert not (tmp_path / "outside.md").exists()


def test_watcher_rejects_unknown_matter(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    with pytest.raises(ValueError):
        watcher.MatterWatcher(conn, 4242)
    with pytest.raises(ValueError):
        watcher.detect_changes(conn, 4242)
    with pytest.raises(ValueError):
        watcher.make_conflict_copy(tmp_path / "missing.md")


def test_poll_and_preserve_returns_changes_and_copies(tmp_path):
    conn, folder, mid = _setup(tmp_path)
    (folder / "doc.md").write_text("external version")
    changes, copies = watcher.MatterWatcher(conn, mid).poll_and_preserve(
        stamp="20261109T120000Z"
    )
    assert [c.kind for c in changes] == ["modified"]
    assert len(copies) == 1
    assert (folder / "doc.md").read_text() == "external version"


def test_guarded_write_never_overwrites_a_file_created_outside_the_app(tmp_path):
    import pathlib
    from hermes_legal import db, matters
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "a.txt").write_text("a", encoding="utf-8")
    mid = matters.open_folder_as_matter(conn, folder)
    (folder / "new.docx").write_text("external work", encoding="utf-8")
    result = watcher.write_document(conn, mid, "new.docx", "app content")
    assert result.status == "conflict"
    assert (folder / "new.docx").read_text(encoding="utf-8") == "external work"
    assert pathlib.Path(result.conflict_copy).read_text(encoding="utf-8") == "app content"


def test_files_added_to_a_folder_that_was_empty_at_open_are_detected(tmp_path):
    from hermes_legal import db, matters
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder)
    (folder / "b.txt").write_text("b", encoding="utf-8")
    assert [(c.relative_path, c.kind) for c in watcher.detect_changes(conn, mid)] == [("b.txt", "created")]


def test_guarded_write_leaves_no_temporary_files(tmp_path):
    from hermes_legal import db, matters
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder)
    assert watcher.write_document(conn, mid, "sub/a.txt", "x").status == "written"
    assert sorted(p.name for p in folder.rglob("*") if p.is_file()) == ["a.txt"]
