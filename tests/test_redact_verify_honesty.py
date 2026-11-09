"""Issue #23 honesty: redact-verify must say plainly when no PDF was checked.

A text file that lacks a phrase is not a redacted PDF. These tests pin the
CLI contract: text input is announced as a text-only check, a real PDF is
verified on text re-extracted from the PDF bytes, and a PDF that cannot be
read (missing optional extra) is a plain refusal, never a pass.
"""
import pytest

from hermes_legal import pdf_tools
from hermes_legal.cli import main
from hermes_legal.pdf_tools import DocumentText, is_pdf_bytes


def test_is_pdf_bytes_detects_pdf_header():
    assert is_pdf_bytes(b"%PDF-1.7\nsome bytes")
    assert is_pdf_bytes(b"junk\n%PDF-1.4\n")  # header within the first bytes
    assert not is_pdf_bytes(b"plain text, no header at all")
    assert not is_pdf_bytes(b"")


def test_text_input_says_no_pdf_was_checked(tmp_path, capsys):
    clean = tmp_path / "clean.txt"
    clean.write_text("Nothing sensitive here.")
    assert main(["redact-verify", str(clean), "secret phrase"]) == 0
    out = capsys.readouterr().out
    assert "no PDF was checked" in out


def test_pdf_input_without_pdf_extra_is_a_plain_refusal(tmp_path, capsys, monkeypatch):
    def _missing(_data):
        raise RuntimeError("extracting a real PDF text layer needs the optional 'pdf' extra")

    monkeypatch.setattr(pdf_tools, "extract_text_layer", _missing)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfake body")
    assert main(["redact-verify", str(pdf), "secret phrase"]) == 2
    captured = capsys.readouterr()
    assert "no PDF was checked" in (captured.out + captured.err)


def test_pdf_input_verifies_text_reextracted_from_the_pdf(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        pdf_tools, "extract_text_layer",
        lambda _data: DocumentText.from_texts(["Rebuilt page text."]),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfake body")
    assert main(["redact-verify", str(pdf), "secret phrase"]) == 0
    out = capsys.readouterr().out
    assert "no PDF was checked" not in out
    assert "re-extracted" in out


def test_pdf_input_fails_when_phrase_survives_reextraction(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        pdf_tools, "extract_text_layer",
        lambda _data: DocumentText.from_texts(["Still has the secret phrase."]),
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfake body")
    assert main(["redact-verify", str(pdf), "secret phrase"]) == 1
