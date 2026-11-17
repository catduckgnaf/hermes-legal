"""PDF utilities: Bates stamping plan and true-redaction verification.

The legal risk in this area is specific: drawing a black rectangle over
text is not redaction, because the text stays in the file. This module
therefore separates the two halves that can be proven offline:

- **Bates stamping is a plan, and now also a writer.** :func:`plan_bates_stamps`
  computes the exact label for every page, deterministically.
  :func:`stamp_pdf` renders that plan onto real PDF page content with
  pypdf, merging a one-line overlay page (built by the standard-library
  writer below) onto every page.
- **Redaction is verified on the text layer, and now also a rebuild.**
  :func:`apply_redaction_to_text` removes the target text from the
  extracted layer, and :func:`redact_pdf` rebuilds a brand-new PDF from
  the redacted layer only, then runs :func:`verify_redaction` on text
  re-extracted from the rebuilt bytes. The rebuild writes no document
  metadata, and because the output is a fresh file it carries no
  annotations, attachments, form fields, images, or incremental-save
  history from the source. What that does **not** prove: text embedded
  in images was never in the text layer, no OCR check is run on it, and
  the rebuilt pages keep only the text layer — original layout, fonts,
  and graphics are not preserved. Those limits are stated in the CLI
  output and the docs, not hidden.

Reading a real PDF's text layer is available through the optional ``pdf``
extra (``pypdf``) via :func:`extract_text_layer`; the plan, verification,
and raw PDF writing logic itself is standard library only and fully
testable offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTION_PLACEHOLDER = "[REDACTED]"


# --------------------------------------------------------------------------
# Extracted text-layer abstraction
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based, as a human counts pages
    text: str


@dataclass(frozen=True)
class DocumentText:
    pages: tuple[PageText, ...]

    @classmethod
    def from_texts(cls, texts: list[str]) -> "DocumentText":
        return cls(tuple(PageText(i + 1, t) for i, t in enumerate(texts)))

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


# --------------------------------------------------------------------------
# Bates stamping plan
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BatesConfig:
    prefix: str = ""
    suffix: str = ""
    start: int = 1
    digits: int = 6
    position: str = "bottom-right"  # rendering hint for the writer step

    def __post_init__(self):
        if self.start < 0:
            raise ValueError("Bates start must be zero or greater")
        if self.digits < 1:
            raise ValueError("Bates digits must be at least 1")


@dataclass(frozen=True)
class BatesStamp:
    page_number: int
    label: str
    position: str

    def as_dict(self) -> dict:
        return {"page_number": self.page_number, "label": self.label, "position": self.position}


def format_bates_label(number: int, config: BatesConfig) -> str:
    """One label, for example ``ACME-000042`` for prefix ``ACME-``, digits 6."""
    return f"{config.prefix}{number:0{config.digits}d}{config.suffix}"


def plan_bates_stamps(page_count: int, config: BatesConfig | None = None) -> list[BatesStamp]:
    """The stamp for every page, in page order. Pure and deterministic:
    the same page count and config always produce the same plan, and the
    labels are unique and consecutive from ``config.start``."""
    if page_count < 0:
        raise ValueError("page count must be zero or greater")
    config = config or BatesConfig()
    return [BatesStamp(i + 1, format_bates_label(config.start + i, config), config.position)
            for i in range(page_count)]


# --------------------------------------------------------------------------
# True redaction: locate, remove, and verify on the text layer
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RedactionHit:
    page_number: int
    phrase: str
    start: int
    end: int

    def as_dict(self) -> dict:
        return {"page_number": self.page_number, "phrase": self.phrase,
                "start": self.start, "end": self.end}


@dataclass
class RedactionPlan:
    hits: list[RedactionHit] = field(default_factory=list)

    @property
    def pages_affected(self) -> list[int]:
        return sorted({h.page_number for h in self.hits})

    def as_dict(self) -> dict:
        return {"hit_count": len(self.hits), "pages_affected": self.pages_affected,
                "hits": [h.as_dict() for h in self.hits]}


def _find_all(text: str, phrase: str, *, case_sensitive: bool) -> list[tuple[int, int]]:
    if not phrase:
        return []
    haystack = text if case_sensitive else text.casefold()
    needle = phrase if case_sensitive else phrase.casefold()
    found, at = [], haystack.find(needle)
    while at != -1:
        found.append((at, at + len(needle)))
        at = haystack.find(needle, at + max(len(needle), 1))
    return found


def locate_redactions(document: DocumentText, phrases: list[str], *,
                      case_sensitive: bool = True) -> RedactionPlan:
    """Every occurrence of every phrase, by page and character offset."""
    plan = RedactionPlan()
    for page in document.pages:
        for phrase in phrases:
            for start, end in _find_all(page.text, phrase, case_sensitive=case_sensitive):
                plan.hits.append(RedactionHit(page.page_number, phrase, start, end))
    plan.hits.sort(key=lambda h: (h.page_number, h.start, h.phrase))
    return plan


def apply_redaction_to_text(document: DocumentText, phrases: list[str], *,
                              replacement: str = REDACTION_PLACEHOLDER) -> DocumentText:
    """A new text layer with every occurrence of every phrase removed.

    Longest phrases are replaced first so an overlapping shorter phrase
    cannot leave a fragment of a longer one behind. Matching is exact
    (case-sensitive); verification below is deliberately stricter than
    removal, so anything this step misses fails verification instead of
    passing silently.
    """
    ordered = sorted((p for p in phrases if p), key=len, reverse=True)
    pages = []
    for page in document.pages:
        text = page.text
        for phrase in ordered:
            text = text.replace(phrase, replacement)
        pages.append(PageText(page.page_number, text))
    return DocumentText(tuple(pages))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class RedactionVerification:
    passed: bool
    remaining: list[RedactionHit] = field(default_factory=list)
    normalized_remaining: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"passed": self.passed,
                "remaining": [h.as_dict() for h in self.remaining],
                "normalized_remaining": self.normalized_remaining}


def verify_redaction(document: DocumentText, phrases: list[str]) -> RedactionVerification:
    """Re-extraction check: no target phrase may survive in any form.

    Three searches must all be empty: exact matches, case-insensitive
    matches, and matches in whitespace-normalized text (which catches a
    phrase split across a line break by extraction). This is the check the
    acceptance criterion names: a redacted document contains none of the
    redacted text on re-extraction.
    """
    exact = locate_redactions(document, phrases, case_sensitive=True)
    folded = locate_redactions(document, phrases, case_sensitive=False)
    remaining = exact.hits if exact.hits else folded.hits
    normalized_doc = _normalize(document.full_text())
    normalized_remaining = [p for p in phrases if p and _normalize(p) in normalized_doc]
    return RedactionVerification(
        passed=not remaining and not normalized_remaining,
        remaining=remaining,
        normalized_remaining=normalized_remaining,
    )


def is_pdf_bytes(data: bytes) -> bool:
    """True when the bytes carry a PDF header.

    The PDF specification allows the ``%PDF-`` header to appear within the
    first 1024 bytes, so a short leading offset is tolerated. Anything else
    is not a PDF, and a check run against it must never be reported as a
    PDF check.
    """
    return b"%PDF-" in data[:1024]


# --------------------------------------------------------------------------
# Minimal raw PDF writer (standard library only)
# --------------------------------------------------------------------------

def _pdf_literal(text: str) -> bytes:
    """One PDF literal string body: WinAnsi bytes with the delimiters escaped.

    cp1252 is the encoding WinAnsiEncoding describes, so curly quotes,
    dashes and the section sign survive; latin-1 would turn them into "?".
    """
    raw = text.encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _raw_pdf(page_contents: list[bytes], page_sizes: list[tuple[float, float]],
             metadata: dict[str, str] | None = None) -> bytes:
    """Assemble a complete PDF from per-page content streams.

    Objects: 1 catalog, 2 page tree, 3 Helvetica font, then a page and a
    content object per page, and an info object only when ``metadata``
    is given. With no metadata the file has no ``/Info`` at all, which is
    what the redaction rebuild relies on for metadata scrubbing.
    """
    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(page_contents)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_contents)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, (content, (width, height)) in enumerate(zip(page_contents, page_sizes)):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:g} {height:g}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                       + content + b"\nendstream")
    info_obj = None
    if metadata:
        info_obj = len(objects) + 1
        entries = " ".join(f"/{key} ({_pdf_literal(value).decode('latin-1')})"
                           for key, value in metadata.items())
        objects.append(f"<< {entries} >>".encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R"
    if info_obj:
        trailer += f" /Info {info_obj} 0 R"
    out += f"trailer\n{trailer} >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def _text_page_content(text: str, height: float) -> bytes:
    import textwrap
    lines: list[str] = []
    for raw_line in text.split("\n"):
        lines.extend(textwrap.wrap(raw_line, 88) or [""])
    parts = [f"BT /F1 11 Tf 14 TL 72 {height - 72:g} Td".encode()]
    for i, line in enumerate(lines):
        if i:
            parts.append(b"T*")
        if line:
            parts.append(b"(" + _pdf_literal(line) + b") Tj")
    parts.append(b"ET")
    return b" ".join(parts)


def build_text_pdf(pages: list[str], *, page_sizes: list[tuple[float, float]] | None = None,
                   metadata: dict[str, str] | None = None) -> bytes:
    """A real PDF whose pages hold the given text, one string per page.

    Standard library only. This is the fixture builder for the tests and
    the output builder for the redaction rebuild. Text is set in
    Helvetica, wrapped at 88 characters; there is no other content.
    """
    sizes = page_sizes or [(612.0, 792.0)] * len(pages)
    contents = [_text_page_content(text, size[1]) for text, size in zip(pages, sizes)]
    return _raw_pdf(contents, sizes, metadata)


def _overlay_pdf(label: str, width: float, height: float, position: str,
                 x0: float = 0.0, y0: float = 0.0) -> bytes:
    """A one-page PDF holding only the Bates label at ``position``.

    ``x0``/``y0`` are the target page's media box origin: a page whose box
    does not start at 0,0 would otherwise get its label off the page.
    """
    text_width = len(label) * 5.0  # close enough for 9pt Helvetica placement
    vertical, _, horizontal = position.partition("-")
    y = height - 24 if vertical == "top" else 24.0
    if horizontal == "left":
        x = 36.0
    elif horizontal == "center":
        x = max((width - text_width) / 2, 0.0)
    else:  # right, the default
        x = max(width - 36.0 - text_width, 0.0)
    content = (f"BT /F1 9 Tf 1 0 0 1 {x + x0:g} {y + y0:g} Tm (".encode()
               + _pdf_literal(label) + b") Tj ET")
    return _raw_pdf([content], [(width + x0, height + y0)])


def _require_pypdf():
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "working with a real PDF file needs the optional 'pdf' extra: "
            "install hermes-legal[pdf] (pypdf)"
        ) from exc
    return pypdf


# --------------------------------------------------------------------------
# Bates stamping and true redaction on real PDF bytes (pypdf)
# --------------------------------------------------------------------------

def stamp_pdf(pdf_bytes: bytes, config: BatesConfig | None = None) -> bytes:
    """A stamped copy of ``pdf_bytes``: the planned label on every page.

    The source pages are kept as they are (content, images, metadata);
    only the overlay label is added. Raises ``ValueError`` for non-PDF
    input and ``RuntimeError`` when the ``pdf`` extra is missing.
    """
    if not is_pdf_bytes(pdf_bytes):
        raise ValueError("not a PDF: the input carries no %PDF- header")
    pypdf = _require_pypdf()
    import io
    config = config or BatesConfig()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    stamps = plan_bates_stamps(len(reader.pages), config)
    # Clone into the writer first: pypdf 7 only merges onto writer-owned pages.
    # Cloning also carries the source metadata over unchanged.
    writer = pypdf.PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    for page, stamp in zip(writer.pages, stamps):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        x0, y0 = float(page.mediabox.left), float(page.mediabox.bottom)
        overlay = pypdf.PdfReader(io.BytesIO(
            _overlay_pdf(stamp.label, width, height, stamp.position, x0, y0)))
        page.merge_page(overlay.pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@dataclass
class RedactionResult:
    output_bytes: bytes
    verification: RedactionVerification
    plan: RedactionPlan

    def as_dict(self) -> dict:
        return {"verification": self.verification.as_dict(), "plan": self.plan.as_dict(),
                "output_bytes": len(self.output_bytes)}


#: Plain-language coverage statement for the rebuild. The CLI prints this
#: verbatim so the limits travel with every redacted file it produces.
REDACTION_COVERAGE = (
    "covered: target phrases removed from the text layer and verified absent on "
    "re-extraction from the rebuilt PDF bytes; document metadata cleared (no info "
    "dictionary or XMP is written); incremental-save history dropped, because the "
    "output is a new file; annotations, attachments, and form fields are not "
    "carried into the rebuild",
    "not covered: text embedded in images was never in the text layer and no OCR "
    "check was run, so image content is not verified; the rebuild keeps only the "
    "text layer, so original layout, fonts, images, and graphics are not preserved",
)


def redact_pdf(pdf_bytes: bytes, phrases: list[str]) -> RedactionResult:
    """True redaction by rebuild: a new PDF built from redacted text only.

    The source is never edited in place. Its text layer is extracted, the
    phrases are removed, and a brand-new PDF is written from the result
    (see :data:`REDACTION_COVERAGE` for exactly what that covers). The
    returned verification ran on text re-extracted from the rebuilt
    bytes, which is the only verification that proves anything.
    """
    if not is_pdf_bytes(pdf_bytes):
        raise ValueError("not a PDF: the input carries no %PDF- header")
    pypdf = _require_pypdf()
    import io
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]
    document = extract_text_layer(pdf_bytes)
    plan = locate_redactions(document, phrases)
    redacted = apply_redaction_to_text(document, phrases)
    output = build_text_pdf([p.text for p in redacted.pages], page_sizes=sizes)
    # Whole-file audit of the rebuilt bytes: text layer, raw bytes, decoded
    # streams, string values and revision count. Anything blocking fails it.
    audit = audit_redacted_pdf(output, phrases)
    verification = audit.text_layer
    if not audit.passed and verification.passed:
        verification = RedactionVerification(
            passed=False, remaining=verification.remaining,
            normalized_remaining=sorted(set(audit.byte_survivors + audit.string_survivors))
            or list(audit.blocking))
    return RedactionResult(output_bytes=output, verification=verification, plan=plan)


# --------------------------------------------------------------------------
# Whole-file redaction audit: text layer, bytes, decoded streams, structure
# --------------------------------------------------------------------------

def _phrase_byte_forms(phrase: str) -> set[bytes]:
    """Every byte spelling of ``phrase`` a PDF can hold, lowercased.

    Literal strings (WinAnsi, UTF-8, with and without PDF escapes), UTF-16
    text strings, and the hex-string spelling of each. The haystack is
    lowercased before the search, so the forms are too.
    """
    forms: set[bytes] = set()
    for variant in {phrase, phrase.lower(), phrase.upper()}:
        for codec in ("cp1252", "utf-8", "utf-16-be", "utf-16-le"):
            raw = variant.encode(codec, "replace")
            forms.add(raw.lower())
            forms.add(raw.hex().encode())
        forms.add(_pdf_literal(variant).lower())
    return {form for form in forms if form}


def _flate_streams(data: bytes) -> list[bytes]:
    """Every Flate stream in the raw file, decoded, in every revision.

    A regular-expression sweep, not a parse: it also reaches streams that
    belong to earlier incremental-save revisions, which a parser that
    follows the newest cross-reference table never visits.
    """
    import zlib
    decoded = []
    for body in re.findall(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            decoded.append(zlib.decompress(body))
        except zlib.error:
            try:
                decoded.append(zlib.decompressobj().decompress(body))
            except zlib.error:
                pass
    return decoded


def revision_count(data: bytes) -> int:
    """How many saved revisions the file holds (1 for a freshly written file).

    Each incremental save appends a new ``%%EOF``. A linearized file
    carries two end markers for one revision, so that one case is allowed.
    """
    markers = data.count(b"%%EOF")
    if markers and b"/Linearized" in data[:2048]:
        markers -= 1
    return max(markers, 1)


def _object_inventory(pdf_bytes: bytes) -> dict:
    """Walk every object of the newest revision with pypdf.

    Returns the decoded data of every stream (any filter pypdf can
    decode, not only Flate), every string value, and counts of the things
    that hide content: images, annotations, attachments, form fields,
    info entries and XMP. Raises ``ValueError`` for an encrypted file.
    """
    pypdf = _require_pypdf()
    import io
    from pypdf.generic import (ArrayObject, ByteStringObject, DictionaryObject, StreamObject,
                               TextStringObject)
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted:
        raise ValueError("the PDF is encrypted, so its content cannot be checked")
    found = {"streams": [], "strings": [], "images": 0, "annotations": 0, "attachments": 0,
             "form_fields": 0, "info_entries": 0, "xmp": 0, "undecodable_streams": 0}

    def visit(obj) -> None:
        # Indirect references are not followed: every object is visited
        # once by number in the loop below, so cycles cannot recurse.
        if isinstance(obj, DictionaryObject):
            kind, subtype = dict.get(obj, "/Type"), dict.get(obj, "/Subtype")
            if subtype == "/Image":
                found["images"] += 1
            if kind == "/Annot" or ("/Rect" in obj and subtype is not None):
                found["annotations"] += 1
            if kind == "/Filespec" or "/EF" in obj:
                found["attachments"] += 1
            if "/FT" in obj:
                found["form_fields"] += 1
            if kind == "/Metadata":
                found["xmp"] += 1
            if isinstance(obj, StreamObject):
                try:
                    found["streams"].append(bytes(obj.get_data()))
                except Exception:  # an unsupported or damaged filter
                    found["undecodable_streams"] += 1
            for value in dict.values(obj):
                visit(value)
        elif isinstance(obj, ArrayObject):
            for value in list.__iter__(obj):
                visit(value)
        elif isinstance(obj, TextStringObject):
            found["strings"].append(str(obj))
        elif isinstance(obj, ByteStringObject):
            found["strings"].append(bytes(obj).decode("latin-1"))

    for number in range(1, int(reader.trailer.get("/Size", 1))):
        try:
            visit(reader.get_object(number))
        except Exception:
            found["undecodable_streams"] += 1
    info = reader.trailer.get("/Info")
    if info is not None:
        found["info_entries"] = len(info.get_object())
    return found


@dataclass
class PdfRedactionAudit:
    """What a whole-file check of one PDF found. ``passed`` is fail-closed:
    anything in ``blocking`` means the file is not safe to produce."""
    text_layer: RedactionVerification
    byte_survivors: list[str] = field(default_factory=list)
    string_survivors: list[str] = field(default_factory=list)
    revisions: int = 1
    inventory: dict = field(default_factory=dict)
    blocking: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blocking

    def as_dict(self) -> dict:
        layer = self.text_layer.as_dict()
        return {"passed": self.passed, "text_layer_passed": layer["passed"],
                "remaining": layer["remaining"],
                "normalized_remaining": layer["normalized_remaining"],
                "byte_survivors": self.byte_survivors, "string_survivors": self.string_survivors,
                "revisions": self.revisions, "inventory": self.inventory,
                "blocking": self.blocking, "notes": self.notes}


def audit_redacted_pdf(pdf_bytes: bytes, phrases: list[str]) -> PdfRedactionAudit:
    """Check a whole PDF file for any trace of ``phrases``. Fail closed.

    Four independent searches run on the file bytes themselves:

    1. the text layer re-extracted from the file (:func:`verify_redaction`);
    2. the raw bytes and every Flate stream of every revision, for each
       byte spelling a PDF can use (literal, UTF-16, hex string);
    3. every stream of the newest revision as pypdf decodes it, which
       covers XMP metadata, embedded attachments and non-Flate filters;
    4. every string value in every object: info entries, annotation
       contents, form field values, file names, bookmarks.

    The file fails when any search finds a phrase, when it holds earlier
    incremental-save revisions (their page content cannot be re-extracted,
    so a phrase drawn in pieces there would go unseen), or when it is
    encrypted or cannot be parsed. Images are counted and reported: text
    that exists only as pixels is not searched, because no OCR is run.
    """
    if not is_pdf_bytes(pdf_bytes):
        raise ValueError("not a PDF: the input carries no %PDF- header")
    phrases = [p for p in phrases if p and p.strip()]
    text_layer = verify_redaction(extract_text_layer(pdf_bytes), phrases)
    audit = PdfRedactionAudit(text_layer=text_layer, revisions=revision_count(pdf_bytes))
    if not text_layer.passed:
        audit.blocking.append("a phrase is still in the text layer re-extracted from the file")
    haystacks = [pdf_bytes.lower()] + [s.lower() for s in _flate_streams(pdf_bytes)]
    strings: list[str] = []
    try:
        found = _object_inventory(pdf_bytes)
    except ValueError as exc:
        audit.blocking.append(str(exc))
    except Exception as exc:  # a file the parser cannot walk is not a verified file
        audit.blocking.append(
            f"the PDF structure could not be read, so hidden content was not checked: {exc}")
    else:
        haystacks += [s.lower() for s in found.pop("streams")]
        strings = found.pop("strings")
        audit.inventory = found
    forms = {p: _phrase_byte_forms(p) for p in phrases}
    audit.byte_survivors = [p for p in phrases
                            if any(form in hay for hay in haystacks for form in forms[p])]
    normalized = [_normalize(s) for s in strings]
    audit.string_survivors = [p for p in phrases if any(_normalize(p) in s for s in normalized)]
    if audit.byte_survivors:
        audit.blocking.append("a phrase is still in the file bytes or a decoded stream "
                              "(page content, metadata, an attachment, or an earlier revision)")
    if audit.string_survivors:
        audit.blocking.append("a phrase is still in a string value (document information, "
                              "an annotation, a form field, a bookmark or a file name)")
    if audit.revisions > 1:
        audit.blocking.append(
            f"the file holds {audit.revisions - 1} earlier saved revision(s); earlier page content "
            "stays recoverable until the file is rewritten in full, so redact it with "
            "`legal redact`, which writes a new file")
    inv = audit.inventory
    if inv.get("images"):
        audit.notes.append(f"{inv['images']} image(s) present: text that exists only as pixels "
                           "was not searched, because no OCR was run")
    for key, label in (("annotations", "annotation(s)"), ("attachments", "attachment(s)"),
                       ("form_fields", "form field(s)"),
                       ("info_entries", "document information entries"),
                       ("xmp", "XMP metadata stream(s)")):
        if inv.get(key):
            audit.notes.append(f"{inv[key]} {label} present and searched; review whether "
                               "they should be produced at all")
    if inv.get("undecodable_streams"):
        audit.notes.append(f"{inv['undecodable_streams']} object(s) or stream(s) could not be "
                           "decoded and were searched in raw form only")
    return audit

# --------------------------------------------------------------------------
# Optional real-PDF text extraction (pypdf, the `pdf` extra)
# --------------------------------------------------------------------------

def extract_text_layer(pdf_bytes: bytes) -> DocumentText:
    """Extract the text layer of a real PDF with pypdf, if installed.

    Raises ``RuntimeError`` naming the optional extra when pypdf is absent;
    the plan and verification functions above never need it.
    """
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "extracting a real PDF text layer needs the optional 'pdf' extra: "
            "install hermes-legal[pdf] (pypdf)"
        ) from exc
    import io
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return DocumentText.from_texts([(page.extract_text() or "") for page in reader.pages])
