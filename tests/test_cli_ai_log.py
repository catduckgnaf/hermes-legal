"""`legal ai-log export`: the CLI surface for providers.export_ai_log."""
import json

import pytest

from hermes_legal import cli, db, matters, providers


@pytest.fixture
def logged_matter(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    folder = tmp_path / "matter"
    folder.mkdir()
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Demo — Alvarez (fictional)")
    providers.log_ai_use(conn, mid, providers.PROVIDERS[0], "intake summary", model="Qwen3 8B")
    conn.close()
    return mid


def test_ai_log_export_json(logged_matter, capsys):
    assert cli.main(["ai-log", "export", str(logged_matter)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported[0]["action"] == "intake summary"
    assert exported[0]["tier"] == "LOCAL_ONLY"


def test_ai_log_export_csv(logged_matter, capsys):
    assert cli.main(["ai-log", "export", str(logged_matter), "--format", "csv"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "id,matter_id,provider,tier,model,action,created_at"
    assert "intake summary" in lines[1]


def test_ai_log_export_unknown_matter_is_an_error(logged_matter, capsys):
    assert cli.main(["ai-log", "export", "999"]) == 2
    assert "no such matter" in capsys.readouterr().err
