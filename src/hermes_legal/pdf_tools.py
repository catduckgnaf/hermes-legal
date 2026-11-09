"""PDF utilities: Bates stamping plan and true-redaction verification.

The legal risk in this area is specific: drawing a black rectangle over
text is not redaction, because the text stays in the file. This module
therefore separates the two halves that can be proven offline:

- **Bates stamping is a plan.** :func:`plan_bates_stamps` computes the exact
  label for every page, deterministically. Rendering that plan onto real
  PDF page content is a writer step; this module does not pretend a plan
  is a stamped PDF.
- **Redaction is verified on the text layer.** Redaction work happens on
  :class:`DocumentText`, the extracted-text abstraction (a tuple of
  per-page strings). :func:`apply_redaction_to_text` removes the target
  text from that layer, and :func:`verify_redaction` re-checks the result
  the way the acceptance test re-extracts a finished PDF: exact,
  case-insensitive, and whitespace-normalized searches must all come back
  empty before verification passes. A caller that rebuilds a PDF must run
  the same verification on text re-extracted from the rebuilt file; a
  verification against anything else proves nothing.

Reading a real PDF's text layer is available through the optional ``pdf``
extra (``pypdf``) via :func:`extract_text_layer`; the plan and verification
logic itself is standard library only and fully testable offline.
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
