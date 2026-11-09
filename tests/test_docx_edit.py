import io
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pytest

from hermes_legal.docx_edit import (AUTHOR, W_NS, accept_all_text, build_redline,
                                    compare_docx, compare_paragraphs, has_track_changes,
                                    list_track_changes, make_docx, read_docx_paragraphs,
                                    reject_all_text)

WHEN = datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)


def _part(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert name in zf.namelist()
        return zf.read(name)


# --- fixture generator / Word-compatible structure ---

def test_make_docx_is_a_valid_package():
    data = make_docx(["Hello.", "World."])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml",
                     "word/_rels/document.xml.rels", "word/styles.xml", "word/settings.xml"):
            assert name in zf.namelist()
    content_types = _part(data, "[Content_Types].xml").decode()
    assert "wordprocessingml.document.main+xml" in content_types


def test_make_docx_round_trips_paragraphs():
    paras = ["First paragraph.", "  spaced  ", "", "Last one."]
    assert read_docx_paragraphs(make_docx(paras)) == paras


def test_make_docx_is_deterministic():
    assert make_docx(["A.", "B."]) == make_docx(["A.", "B."])


def test_make_docx_rejects_non_docx_in_read():
    with pytest.raises(ValueError):
        read_docx_paragraphs(b"not a zip at all")


# --- compare ---

def test_compare_identical():
    result = compare_paragraphs(["A.", "B."], ["A.", "B."])
    assert result.is_identical
    assert result.as_dict()["summary"] == {"equal": 2, "insert": 0, "delete": 0, "replace": 0}


def test_compare_insert_delete_replace():
    result = compare_paragraphs(["Keep.", "Old.", "Gone.", "Extra."],
                                ["Keep.", "New.", "Added."])
    kinds = [(c.kind, c.old_text, c.new_text) for c in result.changed]
    assert ("replace", "Old.", "New.") in kinds
    assert ("replace", "Gone.", "Added.") in kinds
    assert ("delete", "Extra.", None) in kinds
    inserted = compare_paragraphs(["Keep."], ["Keep.", "Added."])
    assert [(c.kind, c.old_text, c.new_text) for c in inserted.changed] == [("insert", None, "Added.")]


def test_compare_docx_bytes():
    a = make_docx(["One.", "Two."])
    b = make_docx(["One.", "Changed."])
    result = compare_docx(a, b)
    assert not result.is_identical
    assert result.changed[0].kind == "replace"


def test_compare_is_deterministic():
    old, new = ["A.", "B.", "C."], ["A.", "X.", "C.", "D."]
    assert compare_paragraphs(old, new).as_dict() == compare_paragraphs(old, new).as_dict()


# --- redline builder ---

def test_redline_produces_real_track_changes():
    original = make_docx(["The hearing is on Monday.", "Filing is due Friday."])
    redlined = build_redline(original, ["The hearing is on Tuesday.", "Filing is due Friday."],
                             when=WHEN)
    changes = list_track_changes(redlined)
    assert [(c.kind, c.text) for c in changes] == [
        ("del", "The hearing is on Monday."), ("ins", "The hearing is on Tuesday.")]
    assert all(c.author == AUTHOR == "hermes-legal (AI - unverified)" for c in changes)
    assert all(c.date == "2026-02-03T04:05:06Z" for c in changes)


def test_redline_xml_uses_ins_del_and_del_text():
    redlined = build_redline(make_docx(["Old text."]), ["New text."], when=WHEN)
    xml = _part(redlined, "word/document.xml").decode()
    assert "<w:ins " in xml and "<w:del " in xml and "<w:delText" in xml
    root = ET.fromstring(_part(redlined, "word/document.xml"))
    ids = [el.get(f"{{{W_NS}}}id") for el in root.iter()
           if el.tag in (f"{{{W_NS}}}ins", f"{{{W_NS}}}del")]
    # Content element plus paragraph mark, for the deletion and the insertion.
    assert len(ids) == len(set(ids)) == 4


def test_redline_accept_gives_revised_reject_gives_original():
    original_paras = ["Keep this.", "Replace this.", "Delete this.", "Keep that."]
    revised_paras = ["Keep this.", "Replaced.", "Keep that.", "Insert this."]
    redlined = build_redline(make_docx(original_paras), revised_paras, when=WHEN)
    assert accept_all_text(redlined) == revised_paras
    assert reject_all_text(redlined) == original_paras


def test_redline_insert_only_and_delete_only():
    base = make_docx(["Only."])
    assert accept_all_text(build_redline(base, ["Only.", "More."], when=WHEN)) == ["Only.", "More."]
    assert accept_all_text(build_redline(base, [], when=WHEN)) == []
    assert reject_all_text(build_redline(base, [], when=WHEN)) == ["Only."]


def test_redline_no_changes_has_no_track_changes():
    data = make_docx(["Same.", "Same two."])
    redlined = build_redline(data, ["Same.", "Same two."], when=WHEN)
    assert not has_track_changes(redlined)
    assert read_docx_paragraphs(redlined) == ["Same.", "Same two."]


def test_redline_accepts_revised_docx_bytes():
    original = make_docx(["Version one."])
    revised = make_docx(["Version two."])
    redlined = build_redline(original, revised, when=WHEN)
    assert accept_all_text(redlined) == ["Version two."]


def test_redline_enables_track_revisions_setting():
    redlined = build_redline(make_docx(["A."]), ["B."], when=WHEN)
    assert b"trackRevisions" in _part(redlined, "word/settings.xml")


def test_redline_preserves_other_parts():
    original = make_docx(["A.", "B."])
    redlined = build_redline(original, ["A.", "C."], when=WHEN)
    assert _part(redlined, "word/styles.xml") == _part(original, "word/styles.xml")
