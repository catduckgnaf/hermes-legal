"""Deadlines tests.

The two calculation tests below are worked examples, calculated by hand
first; the test asserts the code reproduces the hand result exactly and
shows the same steps.

HAND CALCULATION 1 — answer after personal service (Rule 12(a)(1)(A)(i)):
  Served with the summons and complaint on Monday, March 2, 2026.
  Rule 6(a): exclude the trigger day (March 2). Count 21 days:
  March 3 is day 1, March 4 day 2, ... March 23 is day 21.
  March 23, 2026 is a Monday, not a weekend or federal holiday.
  Hand result: due Monday, March 23, 2026. Service was personal, so
  Rule 6(d) adds nothing.

HAND CALCULATION 2 — document requests served by mail (Rule 34(b)(2)(A)):
  Served by mail on Friday, March 6, 2026.
  Rule 6(a): exclude March 6. Count 30 days: March 7 is day 1, ...
  March 31 is day 25, April 1 day 26, April 2 day 27, April 3 day 28,
  April 4 day 29, April 5 day 30. April 5, 2026 is a Sunday, so under
  Rule 6(a) the period continues to Monday, April 6, 2026 — the day the
  period would otherwise expire. Rule 6(d) then adds 3 days for service
  by mail: April 7 is 1, April 8 is 2, April 9 is 3. April 9, 2026 is a
  Thursday, not a weekend or federal holiday.
  Hand result: due Thursday, April 9, 2026.
"""
import datetime

import pytest

from hermes_legal import db, deadlines, matters


# ------------------------------------------------------------------- rules

def test_every_rule_carries_source_and_version_date():
    rules = deadlines.load_rules()
    assert rules, "no rules loaded from the data files"
    for rule in rules.values():
        assert rule["source"], rule["id"]
        assert rule["source_url"], rule["id"]
        assert rule["version_date"], rule["id"]
        assert rule["citation"], rule["id"]


def test_frcp_service_response_examples_present():
    rules = deadlines.load_rules()
    assert deadlines.get_rule("frcp-12a1ai-answer-after-service")["period_days"] == 21
    assert deadlines.get_rule("frcp-34b2a-document-request-response")["period_days"] == 30
    assert deadlines.get_rule("frcp-6a")["citation"].endswith("6(a)")
    assert deadlines.get_rule("frcp-6d")["additional_days"] == 3


# -------------------------------------------------------------- calculation

def test_worked_example_1_answer_after_personal_service():
    calc = deadlines.calculate(
        "frcp-12a1ai-answer-after-service", datetime.date(2026, 3, 2),
        service_method="personal")
    assert calc.due_date == datetime.date(2026, 3, 23)  # hand result above
    assert calc.citation.startswith("Fed. R. Civ. P. 12")
    assert "2024-12-01" in calc.rule_source  # version date is shown
    joined = "\n".join(calc.steps)
    assert "exclude the trigger day" in joined
    assert "2026-03-02 + 21 days = 2026-03-23" in joined
    assert "does not apply" in joined  # Rule 6(d), personal service
    assert calc.warning == deadlines.VERIFY_WARNING


def test_worked_example_2_document_requests_by_mail():
    calc = deadlines.calculate(
        "frcp-34b2a-document-request-response", datetime.date(2026, 3, 6),
        service_method="mail")
    assert calc.due_date == datetime.date(2026, 4, 9)  # hand result above
    joined = "\n".join(calc.steps)
    assert "2026-03-06 + 30 days = 2026-04-05" in joined
    assert "a Sunday" in joined and "2026-04-06" in joined  # Rule 6(a) roll
    assert "adds 3 days because service was by mail" in joined
    assert "2026-04-06 + 3 days = 2026-04-09" in joined


def test_electronic_service_adds_no_days():
    # Same facts as worked example 2, but e-service: Rule 6(d) does not
    # apply, so the date stops at the Rule 6(a) roll, Monday April 6.
    calc = deadlines.calculate(
        "frcp-34b2a-document-request-response", datetime.date(2026, 3, 6),
        service_method="electronic")
    assert calc.due_date == datetime.date(2026, 4, 6)


def test_last_day_on_federal_holiday_rolls_forward():
    # Trigger Thursday, November 5, 2026; day 21 is Thursday,
    # November 26, 2026 (Thanksgiving Day), so it rolls to Friday,
    # November 27, 2026.
    calc = deadlines.calculate(
        "frcp-12a1ai-answer-after-service", datetime.date(2026, 11, 5))
    assert calc.due_date == datetime.date(2026, 11, 27)
    assert any("Thanksgiving" in step for step in calc.steps)


def test_counting_rule_alone_cannot_be_calculated():
    with pytest.raises(ValueError, match="no period"):
        deadlines.calculate("frcp-6a", datetime.date(2026, 3, 2))


def test_unknown_rule_and_service_method_raise():
    with pytest.raises(ValueError, match="unknown rule"):
        deadlines.calculate("nope", datetime.date(2026, 3, 2))
    with pytest.raises(ValueError, match="unknown service method"):
        deadlines.calculate("frcp-12a1ai-answer-after-service",
                            datetime.date(2026, 3, 2), service_method="pigeon")


# --------------------------------------------------------------- extraction

ORDER = (
    "The defendant shall serve an answer to the complaint on or before "
    "March 23, 2026. Responses to requests for production are due within "
    "30 days after service of the requests. Any motion shall be filed by "
    "2026-05-01."
)


def test_extraction_returns_unconfirmed_candidates():
    candidates = deadlines.extract_candidates(ORDER)
    assert candidates and all(not c.confirmed for c in candidates)
    explicit = [c for c in candidates if c.kind == "explicit_date"]
    assert datetime.date(2026, 3, 23) in [c.due_date for c in explicit]
    assert datetime.date(2026, 5, 1) in [c.due_date for c in explicit]
    relative = [c for c in candidates if c.kind == "relative_period"]
    assert relative and relative[0].period_days == 30
    assert relative[0].rule_id == "frcp-34b2a-document-request-response"
    filing = [c for c in explicit if c.due_date == datetime.date(2026, 5, 1)]
    assert filing and filing[0].is_filing


def test_extraction_persists_nothing(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "m"; folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    deadlines.extract_candidates(ORDER)
    assert deadlines.list_deadlines(conn, mid) == []


# ------------------------------------------------------------- confirmation

def _setup(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "m"; folder.mkdir()
    return conn, matters.open_folder_as_matter(conn, folder, "Demo")


def test_no_deadline_without_named_human_confirmation(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(ORDER)[0]
    with pytest.raises(ValueError, match="confirmer is required"):
        deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                    confirmed_by="")
    assert deadlines.list_deadlines(conn, mid) == []


def test_human_confirmation_creates_verified_deadline(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(ORDER)[0]
    did = deadlines.confirm_candidate(
        conn, mid, candidate, "Answer due", confirmed_by="catduck reviewer")
    rows = deadlines.list_deadlines(conn, mid)
    assert [r["id"] for r in rows] == [did]
    assert rows[0]["verified"] == 1 and rows[0]["status"] == "confirmed"
    assert rows[0]["confirmed_by"] == "catduck reviewer"
    assert rows[0]["due_at"] == "2026-03-23"


def test_filing_deadline_requires_dual_entry(tmp_path):
    conn, mid = _setup(tmp_path)
    filing = [c for c in deadlines.extract_candidates(ORDER)
              if c.is_filing][0]
    with pytest.raises(ValueError, match="dual entry"):
        deadlines.confirm_candidate(conn, mid, filing, "Motion",
                                    confirmed_by="first reviewer")
    with pytest.raises(ValueError, match="must differ"):
        deadlines.confirm_candidate(conn, mid, filing, "Motion",
                                    confirmed_by="first reviewer",
                                    second_confirmer="first reviewer")
    deadlines.confirm_candidate(conn, mid, filing, "Motion",
                                confirmed_by="first reviewer",
                                second_confirmer="second reviewer")
    assert len(deadlines.list_deadlines(conn, mid)) == 1


def test_relative_candidate_needs_calculation_or_confirmed_date(tmp_path):
    conn, mid = _setup(tmp_path)
    relative = [c for c in deadlines.extract_candidates(ORDER)
                if c.kind == "relative_period"][0]
    with pytest.raises(ValueError, match="calculate it first"):
        deadlines.confirm_candidate(conn, mid, relative, "Responses",
                                    confirmed_by="reviewer")


def test_confirm_calculation_keeps_steps_and_warning(tmp_path):
    conn, mid = _setup(tmp_path)
    calc = deadlines.calculate("frcp-12a1ai-answer-after-service",
                               datetime.date(2026, 3, 2))
    deadlines.confirm_calculation(conn, mid, calc, "Answer due",
                                  confirmed_by="reviewer")
    row = deadlines.list_deadlines(conn, mid)[0]
    assert row["due_at"] == "2026-03-23"
    assert "P. 12" in row["rule_source"]
    stored = row["calculation_json"]
    assert "2026-03-23" in stored and deadlines.VERIFY_WARNING in stored


# --------------------------------------------------------------------- ics

def test_ics_export_contains_only_confirmed_deadlines(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(ORDER)[0]
    deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                confirmed_by="reviewer")
    # An unconfirmed row written outside this module's paths (verified=0)
    # must not reach a calendar either.
    conn.execute("INSERT INTO deadlines (matter_id, due_at, title) "
                 "VALUES (?, '2026-06-01', 'Unverified thing')", (mid,))
    conn.commit()
    ics = deadlines.export_ics(
        conn, mid, now=datetime.datetime(2026, 1, 1,
                                         tzinfo=datetime.timezone.utc))
    assert "BEGIN:VCALENDAR" in ics and "END:VCALENDAR" in ics
    assert "DTSTART;VALUE=DATE:20260323" in ics
    assert "Answer due" in ics and "20260601" not in ics
    assert "Unverified thing" not in ics
    assert deadlines.VERIFY_WARNING.split(".")[0] in ics.replace("\\,", ",")
