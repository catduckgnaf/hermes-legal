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
    """One PDF literal string body: WinAnsi bytes with the delimiters escaped."""
    raw = text.encode("latin-1", "replace")
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


def _overlay_pdf(label: str, width: float, height: float, position: str) -> bytes:
    """A one-page PDF holding only the Bates label at ``position``."""
    text_width = len(label) * 5.0  # close enough for 9pt Helvetica placement
    vertical, _, horizontal = position.partition("-")
    y = height - 24 if vertical == "top" else 24.0
    if horizontal == "left":
        x = 36.0
    elif horizontal == "center":
        x = max((width - text_width) / 2, 0.0)
    else:  # right, the default
        x = max(width - 36.0 - text_width, 0.0)
    content = (f"BT /F1 9 Tf 1 0 0 1 {x:g} {y:g} Tm (".encode()
               + _pdf_literal(label) + b") Tj ET")
    return _raw_pdf([content], [(width, height)])


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
        overlay = pypdf.PdfReader(io.BytesIO(_overlay_pdf(stamp.label, width, height, stamp.position)))
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
    verification = verify_redaction(extract_text_layer(output), phrases)
    # Byte-level backstop: no phrase may survive in the raw rebuilt bytes
    # either, in its original or case-folded form.
    if verification.passed:
        lowered = output.lower()
        survivors = [p for p in phrases if p and p.encode("latin-1", "replace").lower() in lowered]
        if survivors:
            verification = RedactionVerification(
                passed=False, remaining=verification.remaining,
                normalized_remaining=survivors)
    return RedactionResult(output_bytes=output, verification=verification, plan=plan)


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
