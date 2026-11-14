"""PdfCraft as the redaction and Bates engine.

Offline tests drive :mod:`hermes_legal.pdfcraft` through a fake
``pdfcraft-cli`` that interprets the same JSON scripts, so the wrapper's
two-pass protocol, the independent verification and the no-overwrite rule
are pinned without the binary. The ``live`` tests at the end run the real
CLI and skip when it is not installed (set ``HERMES_LEGAL_PDFCRAFT`` or put
``pdfcraft-cli`` on PATH).
"""
import json
import pathlib
import subprocess

import pytest

pypdf = pytest.importorskip("pypdf")

from hermes_legal import pdfcraft
from hermes_legal.cli import main
from hermes_legal.pdf_tools import BatesConfig, build_text_pdf, extract_text_layer, stamp_pdf

SSN = "123-45-6789"


def source(tmp_path, name="in.pdf", pages=None, metadata=None):
    path = tmp_path / name
    path.write_bytes(build_text_pdf(
        pages or [f"Client SSN {SSN} is private. The lease ends in June.", f"Again: {SSN}."],
        metadata=metadata if metadata is not None else {"Author": "Jane Secret"}))
    return path


class FakeCli:
    """Interprets pdfcraft-cli run scripts with the repo's own PDF code.

    ``forget_redaction`` makes it report success without removing the
    text, which is exactly what the independent check must catch.
    """

    def __init__(self, *, forget_redaction=False, fail_tool=None):
        self.forget_redaction = forget_redaction
        self.fail_tool = fail_tool
        self.scripts = []

    def __call__(self, argv):
        assert argv[1:3] == ["run", "--script"] and "--report" in argv
        root = pathlib.Path(argv[argv.index("--root") + 1])
        steps = json.loads(pathlib.Path(argv[3]).read_text(encoding="utf-8"))
        self.scripts.append(steps)
        docs, report, ok = {}, [], True
        for number, step in enumerate(steps, start=1):
            tool, args = step["tool"], step["args"]
            if not ok:
                report.append({"step": number, "tool": tool, "status": "skipped"})
                continue
            if tool == self.fail_tool:
                ok = False
                report.append({"step": number, "tool": tool, "status": "error",
                               "error": f"step {number} ({tool}): simulated failure"})
                continue
            result = self.tool(root, docs, tool, args)
            report.append({"step": number, "tool": tool, "status": "ok", "result": [result]})
        return subprocess.CompletedProcess(argv, 0 if ok else 1,
                                           json.dumps({"ok": ok, "steps": report}), "")

    def tool(self, root, docs, tool, args):
        if tool == "doc_open":
            path = root / args["path"]
            assert path.resolve().is_relative_to(root.resolve()), "outside --root"
            data = path.read_bytes()
            docs[len(docs) + 1] = {"pages": [p.text for p in extract_text_layer(data).pages],
                                   "meta": bool(pypdf.PdfReader(str(path)).metadata), "marks": []}
            return {"doc": len(docs)}
        doc = docs.get(args.get("doc"))
        if tool == "doc_hidden_info":
            return {"categories": [{"category": "metadata", "count": int(doc["meta"])},
                                   {"category": "comments", "count": 0}]}
        if tool == "text_find":
            count = sum(page.casefold().count(args["query"].casefold()) for page in doc["pages"])
            return {"count": count, "matches": []}
        if tool == "redact_mark":
            doc["marks"].append(args["find"])
            return {"marked": 1}
        if tool == "redact_apply":
            if not self.forget_redaction:
                for mark in doc["marks"]:
                    doc["pages"] = [page.replace(mark, "") for page in doc["pages"]]
            return {"applied": len(doc["marks"])}
        if tool == "doc_remove_hidden":
            doc["meta"] = False
            return {}
        if tool == "doc_save":
            (root / args["path"]).write_bytes(build_text_pdf(
                doc["pages"], metadata={"Author": "Jane Secret"} if doc["meta"] else None))
            return {"saved": True}
        if tool == "doc_bates_multi":
            number = args["start_number"]
            for item in args["files"]:
                data = (root / item["input"]).read_bytes()
                config = BatesConfig(prefix=args["prefix"], suffix=args["suffix"],
                                     digits=args["digits"], start=number)
                (root / item["output"]).write_bytes(stamp_pdf(data, config))
                number += len(pypdf.PdfReader(str(root / item["input"])).pages)
            return {"completed": len(args["files"])}
        raise AssertionError(f"unexpected tool {tool}")


def text_of(path):
    return [p.text for p in extract_text_layer(pathlib.Path(path).read_bytes()).pages]


# ------------------------------------------------------------------ offline

def test_redact_marks_only_what_exists_then_verifies_and_writes(tmp_path):
    fake = FakeCli()
    out = tmp_path / "out.pdf"
    outcome = pdfcraft.redact(source(tmp_path), out, [SSN, "never in the file"],
                              cli="pdfcraft-cli", runner=fake)
    assert outcome.passed and out.is_file()
    assert outcome.marked == {SSN: 2, "never in the file": 0}
    assert outcome.hidden_removed == ["metadata"]
    probe, act = fake.scripts
    assert [s["tool"] for s in act] == ["doc_open", "redact_mark", "redact_apply",
                                        "doc_remove_hidden", "doc_save"]
    assert [s["args"]["find"] for s in act if s["tool"] == "redact_mark"] == [SSN]
    assert act[-1]["args"]["full"] is True
    assert all(SSN not in page for page in text_of(out))
    assert "The lease ends in June." in text_of(out)[0]
    assert not pypdf.PdfReader(str(out)).metadata


def test_redaction_that_does_not_remove_the_text_writes_nothing(tmp_path):
    out = tmp_path / "out.pdf"
    outcome = pdfcraft.redact(source(tmp_path), out, [SSN], cli="pdfcraft-cli",
                              runner=FakeCli(forget_redaction=True))
    assert not outcome.passed
    assert outcome.verification.remaining or outcome.byte_survivors
    assert not out.exists()


def test_pdfcraft_failure_raises_and_writes_nothing(tmp_path):
    out = tmp_path / "out.pdf"
    with pytest.raises(pdfcraft.PdfCraftError, match="simulated failure"):
        pdfcraft.redact(source(tmp_path), out, [SSN], cli="pdfcraft-cli",
                        runner=FakeCli(fail_tool="redact_apply"))
    assert not out.exists()


def test_redact_never_overwrites(tmp_path):
    out = tmp_path / "out.pdf"
    out.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        pdfcraft.redact(source(tmp_path), out, [SSN], cli="pdfcraft-cli", runner=FakeCli())
    assert out.read_bytes() == b"keep me"


def test_missing_cli_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv(pdfcraft.CLI_ENV, str(tmp_path / "no-such-cli.exe"))
    assert pdfcraft.find_cli() is None
    with pytest.raises(pdfcraft.PdfCraftError, match="not installed"):
        pdfcraft.redact(source(tmp_path), tmp_path / "out.pdf", [SSN])


def test_bates_runs_one_sequence_across_files(tmp_path):
    a = source(tmp_path, "a.pdf")
    b = source(tmp_path, "b.pdf", pages=["Exhibit B."], metadata={})
    fake = FakeCli()
    stamped = pdfcraft.bates([(a, tmp_path / "a-b.pdf"), (b, tmp_path / "b-b.pdf")],
                             BatesConfig(prefix="ACME", start=1, digits=6),
                             cli="pdfcraft-cli", runner=fake)
    assert [(s.first, s.last) for s in stamped] == [("ACME000001", "ACME000002"),
                                                    ("ACME000003", "ACME000003")]
    assert "ACME000003" in text_of(tmp_path / "b-b.pdf")[0]
    call = fake.scripts[0][0]
    assert call["tool"] == "doc_bates_multi" and call["args"]["start_number"] == 1


def test_bates_refuses_before_writing_when_an_output_exists(tmp_path):
    a, b = source(tmp_path, "a.pdf"), source(tmp_path, "b.pdf")
    (tmp_path / "b-b.pdf").write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        pdfcraft.bates([(a, tmp_path / "a-b.pdf"), (b, tmp_path / "b-b.pdf")],
                       cli="pdfcraft-cli", runner=FakeCli())
    assert not (tmp_path / "a-b.pdf").exists()


def test_cli_redact_without_pdfcraft_says_so_and_offers_rebuild(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(pdfcraft.CLI_ENV, str(tmp_path / "missing"))
    assert main(["redact", str(source(tmp_path)), SSN, "-o", str(tmp_path / "o.pdf")]) == 2
    err = capsys.readouterr().err
    assert "not installed" in err and "--engine rebuild" in err


def test_cli_bates_pypdf_engine_continues_the_sequence(tmp_path, capsys):
    a = source(tmp_path, "a.pdf")
    b = source(tmp_path, "b.pdf", pages=["Exhibit B."], metadata={})
    out = tmp_path / "out"
    assert main(["bates-stamp", str(a), str(b), "--out-dir", str(out), "--prefix", "X",
                 "--engine", "pypdf"]) == 0
    assert "X000003" in text_of(out / "b-bates.pdf")[0]


# --------------------------------------------------------------------- live

live = pytest.mark.skipif(not pdfcraft.available(), reason="pdfcraft-cli is not installed")


@live
def test_live_pdfcraft_redaction_keeps_layout_and_removes_metadata(tmp_path):
    out = tmp_path / "out.pdf"
    outcome = pdfcraft.redact(source(tmp_path), out, [SSN, "never in the file"])
    assert outcome.passed, outcome.as_dict()
    pages = text_of(out)
    assert all(SSN not in page for page in pages)
    assert "The lease ends in June." in pages[0]
    assert "Jane Secret" not in str(pypdf.PdfReader(str(out)).metadata or {})


@live
def test_live_pdfcraft_bates_sequence(tmp_path):
    a = source(tmp_path, "a.pdf")
    b = source(tmp_path, "b.pdf", pages=["Exhibit B."], metadata={})
    stamped = pdfcraft.bates([(a, tmp_path / "a-b.pdf"), (b, tmp_path / "b-b.pdf")],
                             BatesConfig(prefix="ACME-", digits=4, start=7))
    assert [(s.first, s.last) for s in stamped] == [("ACME-0007", "ACME-0008"),
                                                    ("ACME-0009", "ACME-0009")]
