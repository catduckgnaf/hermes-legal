"""Issue #23: verification runs on the whole PDF file, not only its text layer.

A black rectangle is not the only way a "redacted" PDF leaks. The phrase
can sit in the document information, in XMP, in an annotation, in an
embedded attachment, in a compressed stream, or in an earlier revision
kept by an incremental save. Each test below hides the phrase in exactly
one of those places, in a file whose visible text layer is clean, and
pins that ``audit_redacted_pdf`` and ``legal redact-verify`` refuse it.
"""
import io
import zlib

import pytest

pypdf = pytest.importorskip("pypdf")

from hermes_legal import pdf_tools
from hermes_legal.cli import main
from hermes_legal.pdf_tools import audit_redacted_pdf, build_text_pdf, redact_pdf

SECRET = "Project Bluebird"
CLEAN = "Nothing sensitive on this page."


def _writer(pages=(CLEAN,)):
    return pypdf.PdfWriter(clone_from=io.BytesIO(build_text_pdf(list(pages))))


def _saved(writer) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _incremental_update(original: bytes, clean_text: str) -> bytes:
    """Append a real incremental save that replaces page 1's content.

    Object 5 is the first page's content stream in ``build_text_pdf``
    output. The newest revision shows only ``clean_text``; the earlier
    revision, with the original content, stays in the file.
    """
    content = pdf_tools._text_page_content(clean_text, 792.0)
    prev = int(original.rsplit(b"startxref", 1)[1].split()[0])
    body = (b"5 0 obj\n<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
            + content + b"\nendstream\nendobj\n")
    at = len(original)
    xref_at = at + len(body)
    size = int(original.rsplit(b"/Size", 1)[1].split()[0])
    tail = (f"xref\n5 1\n{at:010d} 00000 n \n"
            f"trailer\n<< /Size {size} /Root 1 0 R /Prev {prev} >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return original + body + tail


def test_clean_fresh_pdf_passes_with_nothing_blocking():
    audit = audit_redacted_pdf(build_text_pdf([CLEAN]), [SECRET])
    assert audit.passed and audit.blocking == []
    assert audit.revisions == 1


def test_phrase_in_text_layer_fails():
    audit = audit_redacted_pdf(build_text_pdf([f"About {SECRET} here."]), [SECRET])
    assert not audit.passed
    assert not audit.text_layer.passed


def test_phrase_in_document_information_fails():
    data = build_text_pdf([CLEAN], metadata={"Title": f"{SECRET} memo"})
    audit = audit_redacted_pdf(data, [SECRET])
    assert audit.text_layer.passed  # the visible text is clean
    assert not audit.passed
    assert SECRET in audit.string_survivors


def test_phrase_in_utf16_document_information_fails():
    writer = _writer()
    writer.add_metadata({"/Subject": f"{SECRET} — privileged"})  # forces UTF-16
    audit = audit_redacted_pdf(_saved(writer), [SECRET])
    assert audit.text_layer.passed and not audit.passed
    assert SECRET in audit.string_survivors or SECRET in audit.byte_survivors


def test_phrase_in_compressed_xmp_metadata_fails():
    from pypdf.generic import DecodedStreamObject, NameObject
    writer = _writer()
    xmp = DecodedStreamObject()
    xmp.set_data(f"<x:xmpmeta><dc:title>{SECRET}</dc:title></x:xmpmeta>".encode())
    xmp[NameObject("/Type")] = NameObject("/Metadata")
    xmp[NameObject("/Subtype")] = NameObject("/XML")
    writer._root_object[NameObject("/Metadata")] = writer._add_object(xmp.flate_encode())
    data = _saved(writer)
    assert SECRET.encode() not in data  # compressed: a raw byte search alone misses it
    audit = audit_redacted_pdf(data, [SECRET])
    assert audit.text_layer.passed and not audit.passed
    assert SECRET in audit.byte_survivors
    assert audit.inventory["xmp"] == 1


def test_phrase_in_annotation_fails():
    from pypdf.annotations import FreeText
    writer = _writer()
    writer.add_annotation(0, FreeText(text=f"see {SECRET}", rect=(50, 550, 200, 650)))
    audit = audit_redacted_pdf(_saved(writer), [SECRET])
    assert not audit.passed
    assert SECRET in audit.string_survivors
    assert audit.inventory["annotations"] >= 1


def test_phrase_in_embedded_attachment_fails():
    writer = _writer()
    writer.add_attachment("notes.txt", f"internal: {SECRET}".encode())
    for page in writer.pages:
        page.compress_content_streams()
    audit = audit_redacted_pdf(_saved(writer), [SECRET])
    assert audit.text_layer.passed and not audit.passed
    assert SECRET in audit.byte_survivors
    assert audit.inventory["attachments"] >= 1


def test_phrase_in_earlier_revision_fails_even_though_newest_is_clean():
    data = _incremental_update(build_text_pdf([f"About {SECRET} here."]), CLEAN)
    assert pdf_tools.extract_text_layer(data).full_text().strip() == CLEAN
    audit = audit_redacted_pdf(data, [SECRET])
    assert audit.text_layer.passed and not audit.passed
    assert audit.revisions == 2
    assert SECRET in audit.byte_survivors


def test_earlier_revision_blocks_even_when_no_phrase_is_found():
    # A phrase drawn in pieces in an old revision (for example a kerned TJ
    # array) is invisible to any byte search, so history alone must fail.
    data = _incremental_update(build_text_pdf(["placeholder"]), CLEAN)
    audit = audit_redacted_pdf(data, [SECRET])
    assert audit.byte_survivors == [] and audit.string_survivors == []
    assert not audit.passed
    assert any("earlier saved revision" in reason for reason in audit.blocking)


def test_hex_string_spelling_is_found_in_raw_bytes():
    forms = pdf_tools._phrase_byte_forms(SECRET)
    assert SECRET.encode().hex().encode() in forms
    assert SECRET.lower().encode("utf-16-be").lower() in forms
    assert any(form in b"<< /Title <" + SECRET.encode().hex().upper().encode().lower() + b"> >>"
               for form in forms)


def test_flate_streams_are_decoded_for_every_revision():
    blob = b"1 0 obj\n<< >>\nstream\n" + zlib.compress(SECRET.encode()) + b"\nendstream\nendobj\n"
    assert SECRET.encode() in b"".join(pdf_tools._flate_streams(blob))


def test_images_are_reported_as_not_searched():
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
    writer = _writer()
    image = DecodedStreamObject()
    image.set_data(b"\x00\x00\x00")
    for key, value in (("/Type", NameObject("/XObject")), ("/Subtype", NameObject("/Image")),
                       ("/Width", NumberObject(1)), ("/Height", NumberObject(1)),
                       ("/ColorSpace", NameObject("/DeviceRGB")),
                       ("/BitsPerComponent", NumberObject(8))):
        image[NameObject(key)] = value
    writer._add_object(image)
    audit = audit_redacted_pdf(_saved(writer), [SECRET])
    assert audit.inventory["images"] == 1
    assert any("no OCR" in note for note in audit.notes)


def test_encrypted_pdf_fails_closed():
    writer = _writer()
    writer.encrypt("pw")
    data = _saved(writer)
    try:
        audit = audit_redacted_pdf(data, [SECRET])
    except Exception:
        return  # refusing to read it at all is also fail-closed
    assert not audit.passed


def test_redact_rebuild_output_passes_the_whole_file_audit():
    writer = pypdf.PdfWriter(clone_from=io.BytesIO(
        build_text_pdf([f"About {SECRET} here.", CLEAN], metadata={"Title": f"{SECRET} memo"})))
    writer.add_attachment("notes.txt", f"internal: {SECRET}".encode())
    source = _saved(writer)
    assert not audit_redacted_pdf(source, [SECRET]).passed
    result = redact_pdf(source, [SECRET])
    assert result.verification.passed
    audit = audit_redacted_pdf(result.output_bytes, [SECRET])
    assert audit.passed and audit.revisions == 1
    assert audit.inventory["attachments"] == 0 and audit.inventory["info_entries"] == 0
    assert audit.inventory["annotations"] == 0 and audit.inventory["xmp"] == 0
    lowered = result.output_bytes.lower()
    for stream in pdf_tools._flate_streams(result.output_bytes):
        lowered += stream.lower()
    assert SECRET.lower().encode() not in lowered
    assert SECRET.lower().encode("utf-16-be").lower() not in lowered


def test_cli_redact_verify_fails_on_hidden_copy_and_says_where(tmp_path, capsys):
    pdf = tmp_path / "leaky.pdf"
    pdf.write_bytes(build_text_pdf([CLEAN], metadata={"Title": f"{SECRET} memo"}))
    assert main(["redact-verify", str(pdf), SECRET]) == 1
    out = capsys.readouterr().out
    assert "FAILED:" in out and "string value" in out
    assert "no PDF was checked" not in out


def test_cli_redact_verify_fails_on_incremental_history(tmp_path, capsys):
    pdf = tmp_path / "history.pdf"
    pdf.write_bytes(_incremental_update(build_text_pdf([f"About {SECRET} here."]), CLEAN))
    assert main(["redact-verify", str(pdf), SECRET]) == 1
    assert "earlier saved revision" in capsys.readouterr().out


def test_cli_redact_verify_passes_a_clean_fresh_pdf(tmp_path, capsys):
    pdf = tmp_path / "clean.pdf"
    pdf.write_bytes(build_text_pdf([CLEAN]))
    assert main(["redact-verify", str(pdf), SECRET]) == 0
    out = capsys.readouterr().out
    assert "checked the PDF file itself" in out and "re-extracted" in out
