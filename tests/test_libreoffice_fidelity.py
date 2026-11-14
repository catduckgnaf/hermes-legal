"""LibreOffice fidelity gate for redlines, plus the Word-style fixture.

The conversion tests are the release gate that can run offline: they take
a redline built by ``docx_edit`` and the Word-authored-style fixture,
convert both with LibreOffice headless, and assert the conversion
succeeds and the tracked changes survive as document content. They skip
cleanly when ``soffice`` is not installed (CI runners without it, most
developer machines). Real Microsoft Word is not available in this
environment at all; opening a redline in Word stays a manual release
gate and is not claimed by these tests.
"""
import shutil
import subprocess

import pytest

from hermes_legal.docx_edit import accept_all_text, make_docx, build_redline, reject_all_text
from hermes_legal.docx_fixtures import make_word_style_docx

SOFFICE = shutil.which("soffice")


def _convert(docx_bytes: bytes, tmp_path, stem: str, fmt: str) -> bytes:
    src = tmp_path / f"{stem}.docx"
    src.write_bytes(docx_bytes)
    profile = tmp_path / "lo-profile"
    proc = subprocess.run(
        [SOFFICE, "--headless", "--norestore",
         f"-env:UserInstallation={profile.as_uri()}", "--convert-to", fmt,
         "--outdir", str(tmp_path), str(src)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / f"{stem}.{fmt}"
    assert out.exists()
    return out.read_bytes()


def test_package_parts_use_default_namespace_not_invented_prefix():
    # Regression pin for the bug the LibreOffice gate caught: the package
    # parts ([Content_Types].xml and the .rels files) were serialized with
    # an ElementTree-invented ns0: prefix, and LibreOffice refused to load
    # every generated DOCX. They must use the default namespace.
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(make_docx(["Hello."]))) as zf:
        for name in ("[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels"):
            part = zf.read(name)
            assert b"ns0:" not in part, name
            assert b'xmlns="' in part, name


def test_word_style_fixture_has_word_patterns_and_track_changes():
    data = make_word_style_docx()
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        document = zf.read("word/document.xml")
    assert b"mc:Ignorable" in document
    assert b"w14:paraId" in document
    assert b"rsidR" in document
    assert b"<w:ins " in document and b'w:id="' in document
    assert b"<w:del " in document and b"w:delText" in document
    assert accept_all_text(data) == ["The hearing is on Tuesday.", "Filing is due Friday."]
    assert reject_all_text(data) == ["The hearing is on Monday.", "Filing is due Friday."]


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) not installed")
def test_libreoffice_converts_redline_and_changes_survive(tmp_path):
    redline = build_redline(
        make_docx(["The hearing is on Monday.", "Filing is due Friday."]),
        ["The hearing is on Tuesday.", "Filing is due Friday."])
    text = _convert(redline, tmp_path, "redline", "txt").decode("utf-8", "replace")
    # The inserted text is document content after conversion; the deleted
    # word must not appear as ordinary body text on its own line content.
    assert "Tuesday" in text
    assert "Filing is due Friday." in text


@pytest.mark.skipif(SOFFICE is None, reason="LibreOffice (soffice) not installed")
def test_libreoffice_converts_word_style_fixture_to_pdf(tmp_path):
    pytest.importorskip("pypdf")
    from hermes_legal.pdf_tools import extract_text_layer
    pdf = _convert(make_word_style_docx(), tmp_path, "wordstyle", "pdf")
    doc = extract_text_layer(pdf)
    assert doc.page_count >= 1
    assert "Tuesday" in doc.full_text()
    assert "Filing is due Friday." in doc.full_text()
