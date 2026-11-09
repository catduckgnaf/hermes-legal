import json

from hermes_legal import cli


def _data_dir(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(data))
    return data


def _matter_folder(tmp_path):
    folder = tmp_path / "client-matter"
    folder.mkdir()
    (folder / "intake.md").write_text("intake")
    (folder / "brief.docx").write_bytes(b"brief")
    return folder


def test_cli_matter_open_list_recent_and_documents(monkeypatch, tmp_path, capsys):
    _data_dir(monkeypatch, tmp_path)
    folder = _matter_folder(tmp_path)

    assert cli.main(["matter", "open", str(folder), "--json"]) == 0
    opened = json.loads(capsys.readouterr().out)
    assert opened["name"] == "client-matter"
    assert [d["relative_path"] for d in opened["documents"]] == [
        "brief.docx",
        "intake.md",
    ]

    assert cli.main(["matter", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listed] == [opened["id"]]

    assert cli.main(["matter", "recent", "--json"]) == 0
    recent = json.loads(capsys.readouterr().out)
    assert recent[0]["id"] == opened["id"]
    assert recent[0]["open_count"] == 1

    assert cli.main(["matter", "documents", str(opened["id"]), "--json"]) == 0
    documents = json.loads(capsys.readouterr().out)
    assert [d["relative_path"] for d in documents] == ["brief.docx", "intake.md"]


def test_cli_matter_open_a_file(monkeypatch, tmp_path, capsys):
    _data_dir(monkeypatch, tmp_path)
    folder = _matter_folder(tmp_path)
    assert cli.main(["matter", "open", str(folder / "brief.docx")]) == 0
    out = capsys.readouterr().out
    assert "brief.docx" in out
    assert "intake.md" in out


def test_cli_matter_open_missing_path_is_an_error(monkeypatch, tmp_path, capsys):
    _data_dir(monkeypatch, tmp_path)
    assert cli.main(["matter", "open", str(tmp_path / "missing")]) == 2
    assert "not a file or folder" in capsys.readouterr().err


def test_cli_recent_orders_the_last_opened_matter_first(
    monkeypatch, tmp_path, capsys
):
    _data_dir(monkeypatch, tmp_path)
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    assert cli.main(["matter", "open", str(first)]) == 0
    capsys.readouterr()
    assert cli.main(["matter", "open", str(second)]) == 0
    capsys.readouterr()
    assert cli.main(["matter", "open", str(first)]) == 0
    capsys.readouterr()
    assert cli.main(["matter", "recent"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].split("\t")[1] == "first"
    assert lines[1].split("\t")[1] == "second"


def test_cli_bare_matter_command_still_lists(monkeypatch, tmp_path, capsys):
    _data_dir(monkeypatch, tmp_path)
    folder = _matter_folder(tmp_path)
    assert cli.main(["matter", "open", str(folder)]) == 0
    capsys.readouterr()
    assert cli.main(["matter"]) == 0
    assert "client-matter" in capsys.readouterr().out
    assert cli.main(["matter", "documents", "9999"]) == 2
