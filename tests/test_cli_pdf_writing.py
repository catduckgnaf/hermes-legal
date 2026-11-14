"""CLI wiring for `legal bates-stamp` and `legal redact` on real PDFs."""
import pytest

pytest.importorskip("pypdf")

from hermes_legal.cli import main
from hermes_legal.pdf_tools import build_text_pdf, extract_text_layer

SECRET = "<redacted>"


def _src(tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(build_text_pdf(
        [f"Public text. {SECRET} is here.", "Clean page."],
        metadata={"Title": "Secret Matter File"}))
    return src


def test_cli_bates_stamp_writes_stamped_pdf(tmp_path, capsys):
    src, out = _src(tmp_path), tmp_path / "stamped.pdf"
    assert main(["bates-stamp", str(src), "-o", str(out), "--prefix", "ACME-", "--start", "42"]) == 0
    text = capsys.readouterr().out
    assert "ACME-000042" in text and "ACME-000043" in text
    doc = extract_text_layer(out.read_bytes())
    assert "ACME-000042" in doc.pages[0].text and "ACME-000043" in doc.pages[1].text


def test_cli_bates_stamp_refuses_non_pdf_and_overwrite(tmp_path, capsys):
    plain = tmp_path / "plain.txt"
    plain.write_text("not a pdf")
    assert main(["bates-stamp", str(plain), "-o", str(tmp_path / "x.pdf")]) == 2
    assert "no PDF was stamped" in capsys.readouterr().err
    src, out = _src(tmp_path), tmp_path / "stamped.pdf"
    out.write_bytes(b"precious")
    assert main(["bates-stamp", str(src), "-o", str(out)]) == 2
    assert out.read_bytes() == b"precious"


def test_cli_redact_writes_verified_rebuild_and_states_coverage(tmp_path, capsys):
    src, out = _src(tmp_path), tmp_path / "redacted.pdf"
    assert main(["redact", str(src), SECRET, "-o", str(out)]) == 0
    text = capsys.readouterr().out
    assert "not covered" in text and "metadata cleared" in text
    data = out.read_bytes()
    assert SECRET.encode() not in data and b"Secret Matter File" not in data
    doc = extract_text_layer(data)
    assert "Public text." in doc.full_text() and "Clean page." in doc.full_text()


def test_cli_redact_refuses_non_pdf(tmp_path, capsys):
    plain = tmp_path / "plain.txt"
    plain.write_text(SECRET)
    assert main(["redact", str(plain), SECRET, "-o", str(tmp_path / "x.pdf")]) == 2
    assert "no PDF was redacted" in capsys.readouterr().err
    assert not (tmp_path / "x.pdf").exists()
