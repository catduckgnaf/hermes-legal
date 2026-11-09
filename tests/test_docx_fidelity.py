import io
import zipfile
from xml.etree import ElementTree as ET

from hermes_legal.docx_edit import W_NS, accept_all_text, build_redline, make_docx, reject_all_text
from hermes_legal.docx_fixtures import (FIDELITY_CASES, fidelity_corpus, make_footnote_docx,
                                        make_numbered_docx, make_table_docx, make_tracked_docx)
from hermes_legal.docx_edit import read_docx_paragraphs
from datetime import datetime, timezone

WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _xml(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read(name)


def test_corpus_covers_every_case_and_is_valid():
    corpus = fidelity_corpus()
    assert tuple(corpus) == FIDELITY_CASES
    for name, data in corpus.items():
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None, name
            ET.fromstring(zf.read("word/document.xml"))  # parses as XML


def test_corpus_is_deterministic():
    assert fidelity_corpus() == fidelity_corpus()


def test_numbering_case_has_numpr_and_numbering_part():
    data = make_numbered_docx(["One.", "Two."])
    assert b"numPr" in _xml(data, "word/document.xml")
    assert b"abstractNum" in _xml(data, "word/numbering.xml")
    assert read_docx_paragraphs(data) == ["One.", "Two."]


def test_footnote_case_has_reference_and_footnotes_part():
    data = make_footnote_docx("Body text.", "The footnote.")
    assert b"footnoteReference" in _xml(data, "word/document.xml")
    assert b"The footnote." in _xml(data, "word/footnotes.xml")


def test_table_case_has_table_and_surrounding_paragraphs():
    data = make_table_docx([["H1", "H2"], ["a", "b"]])
    assert b"<w:tbl>" in _xml(data, "word/document.xml") or b"<w:tbl " in _xml(data, "word/document.xml")
    # Top-level paragraphs are the intro and the closing line; cells are not
    # top-level paragraphs.
    assert read_docx_paragraphs(data) == ["Table follows.", "End of table."]


def test_table_survives_a_redline_of_surrounding_text():
    data = make_table_docx([["H1"], ["cell"]])
    redlined = build_redline(data, ["Table follows, revised.", "End of table."], when=WHEN)
    assert b"<w:tbl>" in _xml(redlined, "word/document.xml") or b"<w:tbl " in _xml(redlined, "word/document.xml")
    assert b"cell" in _xml(redlined, "word/document.xml")
    assert accept_all_text(redlined) == ["Table follows, revised.", "End of table."]
    assert reject_all_text(redlined) == ["Table follows.", "End of table."]


def test_tracked_changes_case_accepts_and_rejects():
    data = make_tracked_docx(["Old sentence.", "Same."], ["New sentence.", "Same."])
    assert accept_all_text(data) == ["New sentence.", "Same."]
    assert reject_all_text(data) == ["Old sentence.", "Same."]
