import json

from hermes_legal.cli import main
from hermes_legal.docx_edit import accept_all_text, make_docx
from hermes_legal.tooldefs import TOOL_IMPLEMENTATIONS


def test_tool_implementations_point_at_real_functions():
    import importlib
    for tool, path in TOOL_IMPLEMENTATIONS.items():
        module_name, _, attr = path.rpartition(".")
        assert callable(getattr(importlib.import_module(module_name), attr)), tool


def test_cli_doc_compare_and_redline(tmp_path, capsys):
    original = tmp_path / "a.docx"
    revised = tmp_path / "b.docx"
    out = tmp_path / "redline.docx"
    original.write_bytes(make_docx(["Original sentence.", "Same."]))
    revised.write_bytes(make_docx(["Revised sentence.", "Same."]))
    assert main(["doc-compare", str(original), str(revised), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identical"] is False
    assert payload["summary"]["replace"] == 1
    assert main(["doc-redline", str(original), str(revised), "-o", str(out)]) == 0
    assert accept_all_text(out.read_bytes()) == ["Revised sentence.", "Same."]


def test_cli_bates_plan_says_plan_only(tmp_path, capsys):
    assert main(["bates-plan", "--pages", "2", "--prefix", "ACME-"]) == 0
    text = capsys.readouterr().out
    assert "ACME-000001" in text and "plan only" in text


def test_cli_redact_verify_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean.txt"
    clean.write_text("Nothing sensitive here.")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("Contains the secret phrase.")
    assert main(["redact-verify", str(clean), "secret phrase"]) == 0
    capsys.readouterr()
    assert main(["redact-verify", str(dirty), "secret phrase"]) == 1


def test_doc_redline_refuses_to_overwrite_an_existing_file(tmp_path):
    from hermes_legal import cli
    from hermes_legal.docx_edit import make_docx
    old, new, out = tmp_path / "old.docx", tmp_path / "new.docx", tmp_path / "out.docx"
    old.write_bytes(make_docx(["One."]))
    new.write_bytes(make_docx(["Two."]))
    out.write_bytes(b"precious")
    assert cli.main(["doc-redline", str(old), str(new), "-o", str(out)]) == 2
    assert out.read_bytes() == b"precious"
