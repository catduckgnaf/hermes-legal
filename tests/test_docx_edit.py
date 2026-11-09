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


# ---------------------------------------------------------------------------
# Regressions: documents as Word actually writes them
# ---------------------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD_AUTHORED = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{_W}"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
    ' xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"'
    ' mc:Ignorable="w14 w15"><w:body>'
    '<w:p w14:paraId="1A2B3C4D"><w:r><w:t>Keep this.</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>See </w:t></w:r><w:hyperlink r:id="rId9"><w:r><w:t>the exhibit</w:t></w:r>'
    '</w:hyperlink><w:r><w:t> now.</w:t></w:r></w:p>'
    '<w:p><w:ins w:id="7" w:author="Pat" w:date="2026-01-01T00:00:00Z"><w:r><w:t>Prior.</w:t></w:r></w:ins></w:p>'
    '<w:sectPr/></w:body></w:document>'
)


def _word_docx():
    import hermes_legal.docx_edit as d
    return d.package_docx({
        "word/document.xml": _WORD_AUTHORED.encode("utf-8"),
        "word/styles.xml": d._styles_xml(),
        "word/settings.xml": d._settings_xml(),
    })


def _document_xml(data):
    import io
    import zipfile
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")


def test_redline_keeps_namespace_prefixes_word_requires():
    import hermes_legal.docx_edit as d
    xml = _document_xml(d.build_redline(_word_docx(), ["Keep this.", "New.", "Prior."]))
    assert 'mc:Ignorable="w14 w15"' in xml
    for prefix in ("mc", "w14", "w15"):
        assert f"xmlns:{prefix}=" in xml
    assert "w14:paraId=" in xml


def test_redline_revision_ids_stay_unique_with_existing_revisions():
    import re
    import hermes_legal.docx_edit as d
    xml = _document_xml(d.build_redline(_word_docx(), ["Keep this.", "New.", "Prior."]))
    ids = re.findall(r'<w:(?:ins|del)\b[^>]*w:id="(\d+)"', xml)
    assert len(ids) == len(set(ids)) and len(ids) >= 4


def test_rejecting_a_redline_restores_hyperlink_text():
    import hermes_legal.docx_edit as d
    src = _word_docx()
    out = d.build_redline(src, ["Keep this.", "New.", "Prior."])
    assert d.reject_all_text(out) == d.reject_all_text(src)
    assert "See the exhibit now." in d.reject_all_text(out)
    assert "New." in d.accept_all_text(out)


def test_inserted_paragraph_does_not_copy_a_section_break():
    import hermes_legal.docx_edit as d
    xml = (f'<w:document xmlns:w="{_W}"><w:body><w:p><w:pPr><w:sectPr/></w:pPr>'
           '<w:r><w:t>One.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    src = d.package_docx({"word/document.xml": xml.encode("utf-8"), "word/settings.xml": d._settings_xml()})
    out = _document_xml(d.build_redline(src, ["One.", "Two."]))
    assert out.count("sectPr") == xml.count("sectPr")
