"""`legal doctor` exit codes: non-zero only when a required item is missing.

Optional integrations (editors, OCR, local-model runtimes, the CourtListener
token) are reported as ``missing`` lines so the user sees what is absent, but
they never fail the run: several are absent by design on a healthy install
(the CourtListener check is optional, and LOCAL-ONLY work needs no token).
"""
from hermes_legal import cli, doctor


def _checks(monkeypatch, *entries):
    monkeypatch.setattr(doctor, "CHECKS", list(entries))


def test_doctor_exits_zero_when_every_check_passes(monkeypatch, capsys):
    _checks(
        monkeypatch,
        ("Required thing", lambda: True, "Fix it.", True),
        ("Optional thing", lambda: True, "Optional hint.", False),
    )
    assert cli.main(["doctor"]) == 0
    assert "missing" not in capsys.readouterr().out


def test_doctor_exits_nonzero_when_a_required_check_fails(monkeypatch, capsys):
    _checks(
        monkeypatch,
        ("Required thing", lambda: False, "Fix it.", True),
        ("Optional thing", lambda: True, "Optional hint.", False),
    )
    assert cli.main(["doctor"]) == 1
    assert "missing  Required thing" in capsys.readouterr().out


def test_doctor_exits_zero_when_only_optional_checks_fail(monkeypatch, capsys):
    _checks(
        monkeypatch,
        ("Required thing", lambda: True, "Fix it.", True),
        ("Optional thing", lambda: False, "Optional hint.", False),
    )
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "missing  Optional thing" in out  # still reported, just not fatal


def test_doctor_run_counts_only_required_misses(monkeypatch):
    _checks(
        monkeypatch,
        ("Required ok", lambda: True, "Fix it.", True),
        ("Required missing", lambda: False, "Fix it.", True),
        ("Optional missing", lambda: False, "Optional hint.", False),
    )
    lines, missing = doctor.run()
    assert missing == 1
    assert any("Required missing" in line for line in lines)
    assert any("Optional missing" in line for line in lines)
