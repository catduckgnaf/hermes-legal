"""Fidelity corpus fixtures: generated DOCX cases, standard library only.

Each builder returns the bytes of a small, valid DOCX that exercises one
feature Word and LibreOffice must survive on a round trip: numbering,
footnotes, tables, and pre-existing tracked changes. The corpus is generated
rather than checked in as binary files, so CI on Linux and Windows builds
byte-identical fixtures and the tests can inspect the exact XML.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from .docx_edit import (AUTHOR, W_NS, _settings_xml, _styles_xml, _w, _xml_bytes,
                        build_redline, document_root, make_docx, package_docx,
                        paragraph_element, run_element)

FIDELITY_CASES = ("plain", "numbering", "footnotes", "tables", "tracked_changes")


def make_numbered_docx(items: list[str]) -> bytes:
    """A DOCX with a real ``w:numPr`` numbered list and a numbering part."""
    body = []
    for item in items:
        p = paragraph_element(item)
        ppr = ET.Element(_w("pPr"))
        numpr = ET.SubElement(ppr, _w("numPr"))
        ilvl = ET.SubElement(numpr, _w("ilvl"))
        ilvl.set(_w("val"), "0")
        numid = ET.SubElement(numpr, _w("numId"))
        numid.set(_w("val"), "1")
        p.insert(0, ppr)
        body.append(p)
    numbering = ET.Element(_w("numbering"))
    abstract = ET.SubElement(numbering, _w("abstractNum"))
    abstract.set(_w("abstractNumId"), "0")
    lvl = ET.SubElement(abstract, _w("lvl"))
    lvl.set(_w("ilvl"), "0")
    fmt = ET.SubElement(lvl, _w("numFmt"))
    fmt.set(_w("val"), "decimal")
    text = ET.SubElement(lvl, _w("lvlText"))
    text.set(_w("val"), "%1.")
    num = ET.SubElement(numbering, _w("num"))
    num.set(_w("numId"), "1")
    abs_id = ET.SubElement(num, _w("abstractNumId"))
    abs_id.set(_w("val"), "0")
    parts = {
        "word/document.xml": _xml_bytes(document_root(body)),
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _settings_xml(),
        "word/numbering.xml": _xml_bytes(numbering),
    }
    return package_docx(parts)


def make_table_docx(rows: list[list[str]]) -> bytes:
    """A DOCX with one paragraph, one real ``w:tbl``, and a closing paragraph."""
    intro = paragraph_element("Table follows.")
    outro = paragraph_element("End of table.")
    tbl = ET.Element(_w("tbl"))
    for row in rows:
        tr = ET.SubElement(tbl, _w("tr"))
        for cell in row:
            tc = ET.SubElement(tr, _w("tc"))
            tc.append(paragraph_element(cell))
    doc = document_root([intro])
    body = doc.find(_w("body"))
    sect = body.find(_w("sectPr"))  # type: ignore[union-attr]
    body.remove(sect)  # type: ignore[union-attr]
    body.append(tbl)  # type: ignore[union-attr]
    body.append(outro)  # type: ignore[union-attr]
    body.append(sect)  # type: ignore[union-attr]
    parts = {
        "word/document.xml": _xml_bytes(doc),
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _settings_xml(),
    }
    return package_docx(parts)


def make_footnote_docx(text: str, footnote_text: str) -> bytes:
    """A DOCX whose paragraph carries a footnote reference to a footnotes part."""
    p = ET.Element(_w("p"))
    p.append(run_element(text + " "))
    ref_run = ET.SubElement(p, _w("r"))
    ref = ET.SubElement(ref_run, _w("footnoteReference"))
    ref.set(_w("id"), "1")
    footnotes = ET.Element(_w("footnotes"))
    sep = ET.SubElement(footnotes, _w("footnote"))
    sep.set(_w("type"), "separator")
    sep.set(_w("id"), "0")
    sep.append(paragraph_element(""))
    note = ET.SubElement(footnotes, _w("footnote"))
    note.set(_w("id"), "1")
    note.append(paragraph_element(footnote_text))
    parts = {
        "word/document.xml": _xml_bytes(document_root([p])),
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _settings_xml(),
        "word/footnotes.xml": _xml_bytes(footnotes),
    }
    return package_docx(parts)


def make_tracked_docx(original: list[str], revised: list[str]) -> bytes:
    """A DOCX that already contains track changes (built by the redline builder)."""
    from datetime import datetime, timezone
    return build_redline(make_docx(original), revised,
                         when=datetime(2026, 1, 1, tzinfo=timezone.utc))


def fidelity_corpus() -> dict[str, bytes]:
    """The full corpus, keyed by case name, in :data:`FIDELITY_CASES` order."""
    return {
        "plain": make_docx(["First paragraph.", "Second paragraph."]),
        "numbering": make_numbered_docx(["File the motion.", "Serve all parties.", "Calendar the hearing."]),
        "footnotes": make_footnote_docx("The rule is settled.", "See the cited authority in the record."),
        "tables": make_table_docx([["Exhibit", "Pages"], ["A", "1-4"], ["B", "5-9"]]),
        "tracked_changes": make_tracked_docx(
            ["The hearing is on Monday.", "Filing is due Friday."],
            ["The hearing is on Tuesday.", "Filing is due Friday."]),
    }
