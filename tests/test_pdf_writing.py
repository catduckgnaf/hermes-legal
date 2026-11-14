"""Bates stamping and true redaction on real PDF bytes.

These tests build a fixture PDF with the standard-library builder in
``pdf_tools`` (no pypdf needed to write it), then use the ``pdf`` extra
(pypdf) to prove what the acceptance criteria name: the stamp text is
present on re-extraction from the OUTPUT bytes, and a redacted PDF
contains none of the target text on re-extraction or in its raw bytes,
while other text and the page count survive. Metadata scrubbing is
checked on the rebuilt file's document info and raw bytes.
"""
import pytest

pypdf = pytest.importorskip("pypdf")

from hermes_legal.pdf_tools import (BatesConfig, build_text_pdf, extract_text_layer,
                                    redact_pdf, stamp_pdf, verify_redaction)

SECRET = "<redacted>"
KEEP = "The quarterly report is public."


def _fixture() -> bytes:
    return build_text_pdf(
        [
            f"{KEEP} {SECRET} appears here.",
            f"Second page repeats {SECRET}.",
            "Nothing sensitive on this page.",
        ],
        metadata={"Title": "Secret Matter File", "Author": "Jane Roe"},
    )


def test_fixture_pdf_has_text_and_metadata():
    data = _fixture()
    doc = extract_text_layer(data)
    assert doc.page_count == 3
    assert SECRET in doc.full_text()
    assert b"Secret Matter File" in data


def test_bates_stamp_writes_label_on_every_page():
    stamped = stamp_pdf(_fixture(), BatesConfig(prefix="ACME-", start=42))
    assert stamped != _fixture()
    doc = extract_text_layer(stamped)
    assert doc.page_count == 3
    for page, label in zip(doc.pages, ["ACME-000042", "ACME-000043", "ACME-000044"]):
        assert label in page.text
    # Original content survives stamping.
    assert KEEP in doc.full_text()
    assert SECRET in doc.full_text()


def test_bates_stamp_respects_start_digits_and_suffix():
    stamped = stamp_pdf(_fixture(), BatesConfig(prefix="X/", suffix="/Y", start=7, digits=3))
    doc = extract_text_layer(stamped)
    assert "X/007/Y" in doc.pages[0].text
    assert "X/009/Y" in doc.pages[2].text


def test_redact_pdf_removes_secret_from_bytes_and_reextraction():
    result = redact_pdf(_fixture(), [SECRET])
    assert result.verification.passed
    assert SECRET.encode() not in result.output_bytes
    assert SECRET.lower().encode() not in result.output_bytes.lower()
    doc = extract_text_layer(result.output_bytes)
    assert doc.page_count == 3
    assert verify_redaction(doc, [SECRET]).passed
    # Other text survives the rebuild.
    assert KEEP in doc.full_text()
    assert "Nothing sensitive on this page." in doc.full_text()
    assert "[REDACTED]" in doc.full_text()
    assert result.plan.pages_affected == [1, 2]


def test_redact_pdf_scrubs_metadata():
    result = redact_pdf(_fixture(), [SECRET])
    assert b"Secret Matter File" not in result.output_bytes
    assert b"Jane Roe" not in result.output_bytes
    import io
    reader = pypdf.PdfReader(io.BytesIO(result.output_bytes))
    meta = reader.metadata
    assert meta is None or not (meta.title or meta.author)


def test_redact_pdf_with_absent_phrase_still_verifies():
    result = redact_pdf(_fixture(), ["never present phrase"])
    assert result.verification.passed
    assert KEEP in extract_text_layer(result.output_bytes).full_text()


def test_stamp_and_redact_reject_non_pdf():
    with pytest.raises(ValueError):
        stamp_pdf(b"not a pdf", BatesConfig())
    with pytest.raises(ValueError):
        redact_pdf(b"not a pdf", [SECRET])
