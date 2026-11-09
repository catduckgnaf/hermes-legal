"""DOCX compare and redline: real OOXML track changes, standard library only.

A redline produced here is not a proprietary change model. It is a ``.docx``
zip whose ``word/document.xml`` carries genuine ``w:ins`` / ``w:del``
elements, attributed to :data:`AUTHOR` and marked unverified in that name
until a human accepts them in Word or LibreOffice. Everything is built by
patching ``document.xml`` (and, when missing, ``word/settings.xml``) inside
the zip with :mod:`zipfile` and :mod:`xml.etree.ElementTree`; no third-party
package is involved, so the module works fully offline.

Scope, honestly stated:

- Compare is deterministic and paragraph-level (``difflib`` opcodes over
  paragraph text, in order). It is not word-level and it does not diff
  formatting, styles, or comments.
- The redline builder operates on top-level body paragraphs. Tables and
  other block elements are preserved unchanged, in place; text inside a
  table cell is not redlined by this builder.
- Accepting the built redline yields exactly the revised top-level
  paragraphs; rejecting it yields exactly the original ones. The test suite
  pins that round trip (:func:`accept_all_text` / :func:`reject_all_text`).
"""
from __future__ import annotations

import copy
import difflib
import io
import itertools
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
AUTHOR = "hermes-legal (AI - unverified)"

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _xml_bytes(root: ET.Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(root, encoding="utf-8")


def _parse_part(raw: bytes) -> tuple[ET.Element, dict[str, str]]:
    """Parse an XML part and return it with its namespace declarations.

    ElementTree renames prefixes and drops declarations it thinks are unused.
    Word documents reference prefixes from attribute values
    (``mc:Ignorable="w14 w15"``), and Word refuses a file where those are not
    declared, so the original declarations have to survive the round trip.
    """
    declared: dict[str, str] = {}
    for _event, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        if prefix:
            declared.setdefault(prefix, uri)
    for prefix, uri in declared.items():
        if not re.fullmatch(r"ns\d+", prefix):
            ET.register_namespace(prefix, uri)
    return ET.fromstring(raw), declared


def _part_bytes(root: ET.Element, declared: dict[str, str]) -> bytes:
    """Serialize a part from :func:`_parse_part`, restoring its declarations."""
    body = ET.tostring(root, encoding="utf-8").decode("utf-8")
    end = re.search(r"/?>", body).start()
    missing = "".join(
        f' xmlns:{prefix}="{uri}"' for prefix, uri in declared.items()
        if f"xmlns:{prefix}=" not in body[:end]
    )
    body = body[:end] + missing + body[end:]
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            + body.encode("utf-8"))


# --------------------------------------------------------------------------
# Minimal valid DOCX package (also the fixture generator used by tests)
# --------------------------------------------------------------------------

_CONTENT_TYPES = {
    "word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    "word/settings.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    "word/numbering.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
    "word/footnotes.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
}
_REL_TYPES = {
    "word/styles.xml": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
    "word/settings.xml": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
    "word/numbering.xml": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
    "word/footnotes.xml": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes",
}
_FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # deterministic bytes for identical input


def _content_types_xml(parts: dict) -> bytes:
    root = ET.Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
    for ext, ctype in (("rels", "application/vnd.openxmlformats-package.relationships+xml"),
                       ("xml", "application/xml")):
        el = ET.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/content-types}Default")
        el.set("Extension", ext)
        el.set("ContentType", ctype)
    for name, ctype in _CONTENT_TYPES.items():
        if name in parts:
            el = ET.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/content-types}Override")
            el.set("PartName", "/" + name)
            el.set("ContentType", ctype)
    return _xml_bytes(root)


def _rels_xml(rels: list[tuple[str, str, str]]) -> bytes:
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    root = ET.Element(f"{{{ns}}}Relationships")
    for rid, rtype, target in rels:
        el = ET.SubElement(root, f"{{{ns}}}Relationship")
        el.set("Id", rid)
        el.set("Type", rtype)
        el.set("Target", target)
    return _xml_bytes(root)


def _styles_xml() -> bytes:
    root = ET.Element(_w("styles"))
    doc_defaults = ET.SubElement(root, _w("docDefaults"))
    rpr_default = ET.SubElement(doc_defaults, _w("rPrDefault"))
    ET.SubElement(rpr_default, _w("rPr"))
    style = ET.SubElement(root, _w("style"))
    style.set(_w("type"), "paragraph")
    style.set(_w("default"), "1")
    style.set(_w("styleId"), "Normal")
    name = ET.SubElement(style, _w("name"))
    name.set(_w("val"), "Normal")
    ET.SubElement(style, _w("qFormat"))
    return _xml_bytes(root)


# Elements CT_Settings requires to come before w:trackRevisions, in order.
_BEFORE_TRACK_REVISIONS = frozenset(_w(tag) for tag in (
    "writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
    "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
    "printFractionalCharacterWidth", "printFormsData", "embedTrueTypeFonts",
    "embedSystemFonts", "saveSubsetFonts", "saveFormsData", "mirrorMargins",
    "alignBordersAndEdges", "bordersDoNotSurroundHeader", "bordersDoNotSurroundFooter",
    "gutterAtTop", "hideSpellingErrors", "hideGrammaticalErrors", "activeWritingStyle",
    "proofState", "formsDesign", "attachedTemplate", "linkStyles",
    "stylePaneFormatFilter", "stylePaneSortMethod", "documentType", "mailMerge",
    "revisionView",
))


def _settings_xml(track_revisions: bool = False) -> bytes:
    root = ET.Element(_w("settings"))
    if track_revisions:
        ET.SubElement(root, _w("trackRevisions"))
    return _xml_bytes(root)


def run_element(text: str) -> ET.Element:
    """One plain ``w:r`` run holding ``text``."""
    run = ET.Element(_w("r"))
    t = ET.SubElement(run, _w("t"))
    if text[:1].isspace() or text[-1:].isspace():
        t.set(f"{{{XML_NS}}}space", "preserve")
    t.text = text
    return run


def paragraph_element(text: str) -> ET.Element:
    p = ET.Element(_w("p"))
    if text:
        p.append(run_element(text))
    return p


def document_root(body_children: list[ET.Element]) -> ET.Element:
    root = ET.Element(_w("document"))
    body = ET.SubElement(root, _w("body"))
    for child in body_children:
        body.append(child)
    sect = ET.SubElement(body, _w("sectPr"))
    pg_sz = ET.SubElement(sect, _w("pgSz"))
    pg_sz.set(_w("w"), "12240")
    pg_sz.set(_w("h"), "15840")
    return root


def package_docx(parts: dict[str, bytes]) -> bytes:
    """Assemble a deterministic DOCX zip from named parts.

    ``parts`` must contain ``word/document.xml``. Content types and the
    document relationships are generated from which optional parts exist
    (styles, settings, numbering, footnotes).
    """
    parts = dict(parts)
    parts["[Content_Types].xml"] = _content_types_xml(parts)
    parts["_rels/.rels"] = _rels_xml([
        ("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
         "word/document.xml"),
    ])
    doc_rels = []
    for i, name in enumerate(sorted(n for n in parts if n in _REL_TYPES), start=1):
        doc_rels.append((f"rId{i}", _REL_TYPES[name], name.split("/", 1)[1]))
    parts["word/_rels/document.xml.rels"] = _rels_xml(doc_rels)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ["[Content_Types].xml", "_rels/.rels"] + sorted(n for n in parts if n not in ("[Content_Types].xml", "_rels/.rels")):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, parts[name])
    return out.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    """A minimal valid DOCX holding one paragraph per string, in order.

    This is the fixture generator: its output opens as a Word-compatible
    document (correct content types, relationships, styles, and section
    properties) and round-trips through :func:`read_docx_paragraphs`.
    """
    parts = {
        "word/document.xml": _xml_bytes(document_root([paragraph_element(p) for p in paragraphs])),
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _settings_xml(),
    }
    return package_docx(parts)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def _read_part(data: bytes, name: str) -> bytes | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read(name) if name in zf.namelist() else None
    except zipfile.BadZipFile as exc:
        raise ValueError("not a DOCX file: the input is not a zip package") from exc


def _paragraph_text(p: ET.Element, mode: str = "accepted") -> str:
    """Text of one paragraph. ``accepted`` drops ``w:del`` content and keeps
    insertions; ``rejected`` drops insertions and restores ``w:delText``;
    ``current`` is the stored visible text (plain ``w:t`` outside deletions).
    """
    chunks: list[str] = []

    def walk(el: ET.Element, in_ins: bool, in_del: bool) -> None:
        in_ins = in_ins or el.tag == _w("ins")
        in_del = in_del or el.tag == _w("del")
        if el.tag == _w("t"):
            if mode == "accepted" and in_del:
                return
            if mode == "rejected" and in_ins:
                return
            if mode == "current" and in_del:
                return
            chunks.append(el.text or "")
            return
        if el.tag == _w("delText"):
            if mode == "rejected" and not in_ins:
                chunks.append(el.text or "")
            return
        if el.tag in (_w("tab"),):
            chunks.append("\t")
            return
        if el.tag in (_w("br"), _w("cr")):
            chunks.append("\n")
            return
        for child in el:
            walk(child, in_ins, in_del)

    walk(p, False, False)
    return "".join(chunks)


def _paragraph_mark(p: ET.Element, tag: str) -> ET.Element | None:
    ppr = p.find(_w("pPr"))
    if ppr is None:
        return None
    rpr = ppr.find(_w("rPr"))
    if rpr is None:
        return None
    return rpr.find(_w(tag))


def _body_paragraphs(data: bytes, mode: str) -> list[str]:
    raw = _read_part(data, "word/document.xml")
    if raw is None:
        raise ValueError("not a DOCX file: word/document.xml is missing")
    root = ET.fromstring(raw)
    body = root.find(_w("body"))
    if body is None:
        return []
    texts = []
    for child in body:
        if child.tag != _w("p"):
            continue
        # A deleted paragraph mark means the whole paragraph goes away on
        # accept; an inserted paragraph mark means it goes away on reject.
        if mode == "accepted" and _paragraph_mark(child, "del") is not None:
            continue
        if mode == "rejected" and _paragraph_mark(child, "ins") is not None:
            continue
        texts.append(_paragraph_text(child, mode))
    return texts


def read_docx_paragraphs(data: bytes) -> list[str]:
    """Top-level paragraph texts (track changes accepted), in order."""
    return _body_paragraphs(data, "accepted")


def accept_all_text(data: bytes) -> list[str]:
    """Paragraph texts as if every tracked change were accepted."""
    return _body_paragraphs(data, "accepted")


def reject_all_text(data: bytes) -> list[str]:
    """Paragraph texts as if every tracked change were rejected."""
    return _body_paragraphs(data, "rejected")


@dataclass(frozen=True)
class TrackChange:
    kind: str  # "ins" or "del"
    author: str
    date: str
    text: str


def list_track_changes(data: bytes) -> list[TrackChange]:
    """Every ``w:ins`` / ``w:del`` in document order, with its text."""
    raw = _read_part(data, "word/document.xml")
    if raw is None:
        raise ValueError("not a DOCX file: word/document.xml is missing")
    root = ET.fromstring(raw)
    changes = []

    def walk(el: ET.Element, in_ppr: bool) -> None:
        in_ppr = in_ppr or el.tag == _w("pPr")
        if el.tag in (_w("ins"), _w("del")) and not in_ppr:
            kind = "ins" if el.tag == _w("ins") else "del"
            tag = _w("t") if kind == "ins" else _w("delText")
            text = "".join(t.text or "" for t in el.iter(tag))
            changes.append(TrackChange(kind, el.get(_w("author"), ""), el.get(_w("date"), ""), text))
        for child in el:
            walk(child, in_ppr)

    walk(root, False)
    return changes


def has_track_changes(data: bytes) -> bool:
    return bool(list_track_changes(data))


# --------------------------------------------------------------------------
# Deterministic paragraph-level compare
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ParagraphChange:
    kind: str  # "equal", "insert", "delete", or "replace"
    old_index: int | None
    new_index: int | None
    old_text: str | None
    new_text: str | None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "old_index": self.old_index, "new_index": self.new_index,
                "old_text": self.old_text, "new_text": self.new_text}


@dataclass
class CompareResult:
    changes: list[ParagraphChange] = field(default_factory=list)

    @property
    def changed(self) -> list[ParagraphChange]:
        return [c for c in self.changes if c.kind != "equal"]

    @property
    def is_identical(self) -> bool:
        return not self.changed

    def as_dict(self) -> dict:
        return {"identical": self.is_identical,
                "summary": {k: sum(1 for c in self.changes if c.kind == k)
                            for k in ("equal", "insert", "delete", "replace")},
                "changes": [c.as_dict() for c in self.changes]}


def compare_paragraphs(old: list[str], new: list[str]) -> CompareResult:
    """Deterministic diff: ``difflib`` opcodes, ``replace`` blocks paired
    positionally with any surplus reported as plain deletes / inserts."""
    result = CompareResult()
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                result.changes.append(ParagraphChange("equal", i1 + k, j1 + k, old[i1 + k], new[j1 + k]))
        elif tag == "delete":
            for i in range(i1, i2):
                result.changes.append(ParagraphChange("delete", i, None, old[i], None))
        elif tag == "insert":
            for j in range(j1, j2):
                result.changes.append(ParagraphChange("insert", None, j, None, new[j]))
        else:  # replace
            paired = min(i2 - i1, j2 - j1)
            for k in range(paired):
                result.changes.append(ParagraphChange("replace", i1 + k, j1 + k, old[i1 + k], new[j1 + k]))
            for i in range(i1 + paired, i2):
                result.changes.append(ParagraphChange("delete", i, None, old[i], None))
            for j in range(j1 + paired, j2):
                result.changes.append(ParagraphChange("insert", None, j, None, new[j]))
    return result


def compare_docx(old_data: bytes, new_data: bytes) -> CompareResult:
    """Compare two DOCX byte strings at paragraph level."""
    return compare_paragraphs(read_docx_paragraphs(old_data), read_docx_paragraphs(new_data))


# --------------------------------------------------------------------------
# Redline builder: real w:ins / w:del by patching document.xml in the zip
# --------------------------------------------------------------------------

def _format_when(when: datetime | None) -> str:
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mark_paragraph(p: ET.Element, tag: str, change_id: int, author: str, date: str) -> None:
    """Track the paragraph mark itself, so accepting a deletion removes the
    paragraph (not just its text) and rejecting an insertion removes it."""
    ppr = p.find(_w("pPr"))
    if ppr is None:
        ppr = ET.Element(_w("pPr"))
        p.insert(0, ppr)
    rpr = ppr.find(_w("rPr"))
    if rpr is None:
        rpr = ET.Element(_w("rPr"))
        # CT_PPr ends with rPr, sectPr, pPrChange, in that order.
        at = next((i for i, c in enumerate(ppr) if c.tag in (_w("sectPr"), _w("pPrChange"))), len(ppr))
        ppr.insert(at, rpr)
    # CT_ParaRPr requires w:ins and w:del before any formatting.
    mark = ET.Element(_w(tag))
    rpr.insert(0, mark)
    mark.set(_w("id"), str(change_id))
    mark.set(_w("author"), author)
    mark.set(_w("date"), date)


# Containers that hold runs a tracked deletion must reach. Dropping these
# would lose their text for good when the change is rejected.
_RUN_CONTAINERS = frozenset(_w(tag) for tag in (
    "hyperlink", "ins", "smartTag", "fldSimple", "sdt", "sdtContent", "customXml",
))


def _deleted_paragraph(original: ET.Element, next_id, author: str, date: str, text: str) -> ET.Element:
    """A tracked deletion of ``original`` that keeps everything inside it.

    Each run stays where it is and is wrapped in ``w:del``, including runs
    inside hyperlinks, content controls, and another author's insertion.
    Existing deletions are left alone. ``next_id`` allocates ``w:id`` values.
    """
    p = copy.deepcopy(original)
    _mark_paragraph(p, "del", next_id(), author, date)

    def new_delete() -> ET.Element:
        delete = ET.Element(_w("del"))
        delete.set(_w("id"), str(next_id()))
        delete.set(_w("author"), author)
        delete.set(_w("date"), date)
        return delete

    made = False

    def wrap(parent: ET.Element) -> None:
        nonlocal made
        rebuilt: list[ET.Element] = []
        current: ET.Element | None = None
        for child in list(parent):
            if child.tag == _w("r"):
                if current is None:
                    current = new_delete()
                    rebuilt.append(current)
                    made = True
                for t in child.iter(_w("t")):
                    t.tag = _w("delText")
                for instr in child.iter(_w("instrText")):
                    instr.tag = _w("delInstrText")
                current.append(child)
                continue
            current = None
            rebuilt.append(child)
            if child.tag in _RUN_CONTAINERS:
                wrap(child)
        for child in list(parent):
            parent.remove(child)
        parent.extend(rebuilt)

    wrap(p)
    if not made and text:
        delete = new_delete()
        run = ET.SubElement(delete, _w("r"))
        t = ET.SubElement(run, _w("delText"))
        if text[:1].isspace() or text[-1:].isspace():
            t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = text
        p.append(delete)
    return p


def _inserted_paragraph(text: str, next_id, author: str, date: str,
                        ppr_source: ET.Element | None) -> ET.Element:
    """A tracked insertion formatted like ``ppr_source``, its neighbor."""
    p = ET.Element(_w("p"))
    run_props = None
    if ppr_source is not None:
        ppr = ppr_source.find(_w("pPr"))
        if ppr is not None:
            ppr = copy.deepcopy(ppr)
            # A copied section break would add a section to the document, and
            # a copied revision mark would attribute this change to someone else.
            for tag in ("sectPr", "pPrChange"):
                for el in ppr.findall(_w(tag)):
                    ppr.remove(el)
            mark_props = ppr.find(_w("rPr"))
            if mark_props is not None:
                for tag in ("ins", "del", "moveFrom", "moveTo"):
                    for el in mark_props.findall(_w(tag)):
                        mark_props.remove(el)
            p.append(ppr)
        first_run = next(ppr_source.iter(_w("r")), None)
        if first_run is not None and first_run.find(_w("rPr")) is not None:
            run_props = copy.deepcopy(first_run.find(_w("rPr")))
    _mark_paragraph(p, "ins", next_id(), author, date)
    ins = ET.SubElement(p, _w("ins"))
    ins.set(_w("id"), str(next_id()))
    ins.set(_w("author"), author)
    ins.set(_w("date"), date)
    run = run_element(text)
    if run_props is not None:
        run.insert(0, run_props)
    ins.append(run)
    return p


def _ensure_track_revisions(parts: dict[str, bytes]) -> None:
    raw = parts.get("word/settings.xml")
    if raw is not None:
        root, declared = _parse_part(raw)
        if root.find(_w("trackRevisions")) is None:
            at = sum(1 for child in root if child.tag in _BEFORE_TRACK_REVISIONS)
            root.insert(at, ET.Element(_w("trackRevisions")))
        parts["word/settings.xml"] = _part_bytes(root, declared)
    else:
        parts["word/settings.xml"] = _settings_xml(track_revisions=True)


def build_redline(original_data: bytes, revised: list[str] | bytes, *,
                  author: str = AUTHOR, when: datetime | None = None) -> bytes:
    """Return a new DOCX: ``original_data`` redlined toward ``revised``.

    ``revised`` is either a list of paragraph strings or the bytes of the
    revised DOCX. Deleted paragraphs become ``w:del`` (their runs rewritten
    as ``w:delText``), inserted paragraphs become ``w:ins``, replaced
    paragraphs become a deletion followed by an insertion, and unchanged
    paragraphs are copied untouched. Every change carries ``author`` and
    the same timestamp. Non-paragraph block elements (tables, the section
    properties) are preserved unchanged; see the module docstring for the
    stated table scope.
    """
    revised_paragraphs = (read_docx_paragraphs(revised) if isinstance(revised, (bytes, bytearray))
                          else list(revised))
    date = _format_when(when)
    with zipfile.ZipFile(io.BytesIO(original_data)) as zf:
        infos = zf.infolist()
        parts = {info.filename: zf.read(info.filename) for info in infos}
    if "word/document.xml" not in parts:
        raise ValueError("not a DOCX file: word/document.xml is missing")
    root, declared = _parse_part(parts["word/document.xml"])
    body = root.find(_w("body"))
    if body is None:
        raise ValueError("not a DOCX file: document has no w:body")

    # w:id values must be unique across the document, including revisions
    # and bookmarks that were there before this redline.
    used_ids = [int(v) for el in root.iter() for v in [el.get(_w("id"))] if v and v.isdigit()]
    next_id = itertools.count(max(used_ids, default=0) + 1).__next__

    children = list(body)
    old_paras = [c for c in children if c.tag == _w("p")]
    old_texts = [_paragraph_text(p, "accepted") for p in old_paras]
    diff = compare_paragraphs(old_texts, revised_paragraphs)

    # Expand the diff into per-old-index actions plus inserts before an index.
    actions: dict[int, str] = {}
    inserts_before: dict[int, list[str]] = {}
    next_old = 0
    for change in diff.changes:
        if change.kind == "equal":
            actions[change.old_index] = "keep"  # type: ignore[index]
            next_old = change.old_index + 1  # type: ignore[operator]
        elif change.kind == "delete":
            actions[change.old_index] = "delete"  # type: ignore[index]
            next_old = change.old_index + 1  # type: ignore[operator]
        elif change.kind == "insert":
            inserts_before.setdefault(next_old, []).append(change.new_text or "")
        elif change.kind == "replace":
            actions[change.old_index] = "delete"  # type: ignore[index]
            inserts_before.setdefault(change.old_index + 1, []).append(change.new_text or "")  # type: ignore[index]
            next_old = change.old_index + 1  # type: ignore[operator]
    # Inserts attached past the last old paragraph belong at the end.
    end_inserts = inserts_before.pop(len(old_paras), []) if len(old_paras) in inserts_before else []
    # Inserts keyed beyond the end (replace on the final paragraph) join the end.
    for key in sorted(k for k in inserts_before if k > len(old_paras)):
        end_inserts.extend(inserts_before.pop(key))

    new_children: list[ET.Element] = []
    ppr_source = old_paras[0] if old_paras else None
    old_index = -1
    sect_pr = None
    for child in children:
        if child.tag == _w("sectPr"):
            sect_pr = child
            continue
        if child.tag == _w("p"):
            old_index += 1
            for text in inserts_before.get(old_index, []):
                new_children.append(_inserted_paragraph(text, next_id, author, date, ppr_source))
            ppr_source = child
            action = actions.get(old_index, "keep")
            if action == "keep":
                new_children.append(child)
            else:
                new_children.append(_deleted_paragraph(child, next_id, author, date, old_texts[old_index]))
            # A replace stores its new text in inserts_before[old_index + 1];
            # the next paragraph iteration emits it at its head, directly
            # after this deletion. A replace on the final paragraph was
            # moved to end_inserts above and is emitted at the end.
            continue
        new_children.append(child)
    for text in end_inserts:
        new_children.append(_inserted_paragraph(text, next_id, author, date, ppr_source))
    if sect_pr is not None:
        new_children.append(sect_pr)
    for child in children:
        body.remove(child)
    for child in new_children:
        body.append(child)

    parts["word/document.xml"] = _part_bytes(root, declared)
    _ensure_track_revisions(parts)
    # Regenerate content types / document rels only when settings was added.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        names = [info.filename for info in infos]
        if "word/settings.xml" not in names:
            # A foreign DOCX without settings: rebuild the package so the
            # new part is declared; document relationships gain settings.
            return _repackage_with_settings(parts, infos)
        for info in infos:
            data = parts[info.filename]
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(new_info, data)
    return out.getvalue()


def _repackage_with_settings(parts: dict[str, bytes], infos) -> bytes:
    """Rebuild the zip adding a settings part, its content-type override,
    and its document relationship, preserving every other part byte for byte
    except ``word/document.xml`` (already patched by the caller)."""
    # Edited as text: re-serializing these default-namespace parts through
    # ElementTree would rewrite every element with an ns0 prefix.
    content_types = parts["[Content_Types].xml"].decode("utf-8")
    if "/word/settings.xml" not in content_types:
        override = (f'<Override PartName="/word/settings.xml" '
                    f'ContentType="{_CONTENT_TYPES["word/settings.xml"]}"/>')
        parts["[Content_Types].xml"] = content_types.replace("</Types>", override + "</Types>").encode("utf-8")
    rel_name = "word/_rels/document.xml.rels"
    if rel_name in parts:
        rels = parts[rel_name].decode("utf-8")
        ids = set(re.findall(r'\bId="([^"]+)"', rels))
        n = next(i for i in itertools.count(1) if f"rId{i}" not in ids)
        relationship = (f'<Relationship Id="rId{n}" Type="{_REL_TYPES["word/settings.xml"]}" '
                        f'Target="settings.xml"/>')
        parts[rel_name] = rels.replace("</Relationships>", relationship + "</Relationships>").encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in infos:
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(new_info, parts[info.filename])
        info = zipfile.ZipInfo("word/settings.xml", date_time=_FIXED_ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, parts["word/settings.xml"])
    return out.getvalue()
