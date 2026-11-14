"""Deadline remainder tests for issue #6.

HAND CALCULATION 3 — document requests served by mail, with a three-day
roll chain (Rule 34(b)(2)(A), counted under Rule 6(a), Rule 6(d) added):
  Served by mail on Thursday, April 23, 2026.
  Rule 6(a): exclude April 23. Count 30 days: April 24 is day 1, ...
  April 30 is day 7, May 23 is day 30. May 23, 2026 is a Saturday, so
  the period continues to Sunday, May 24; that is a Sunday, so it
  continues to Monday, May 25; May 25 is Memorial Day, a federal
  holiday, so it continues to Tuesday, May 26, 2026 — the day the
  period would otherwise expire.
  Rule 6(d) then adds 3 days for service by mail: May 27 is 1,
  May 28 is 2, May 29 is 3. May 29, 2026 is a Friday.
  Hand result: due Friday, May 29, 2026.

HAND CALCULATION 4 — document requests served by mail, where the days
Rule 6(d) adds land the period on a weekend (same rules):
  Served by mail on Monday, March 9, 2026.
  Rule 6(a): exclude March 9. Count 30 days: March 10 is day 1, ...
  March 31 is day 22, April 8 is day 30. April 8, 2026 is a Wednesday,
  so no roll applies at that check.
  Rule 6(d) adds 3 days: April 9 is 1, April 10 is 2, April 11 is 3.
  April 11, 2026 is a Saturday, so the period continues to Sunday,
  April 12, and then to Monday, April 13, 2026.
  Hand result: due Monday, April 13, 2026.
"""
import datetime
import json

import pytest

from hermes_legal import db, deadlines, matters


def _setup(tmp_path):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "m"; folder.mkdir()
    return conn, matters.open_folder_as_matter(conn, folder, "Demo")


# ------------------------------------------- worked examples, steps shown

def test_worked_example_3_roll_chain_shows_every_step():
    calc = deadlines.calculate(
        "frcp-34b2a-document-request-response", datetime.date(2026, 4, 23),
        service_method="mail")
    assert calc.due_date == datetime.date(2026, 5, 29)  # hand result above
    assert calc.citation.startswith("Fed. R. Civ. P. 34")
    assert "2024-12-01" in calc.rule_source
    joined = "\n".join(calc.steps)
    assert "2026-04-23 + 30 days = 2026-05-23" in joined
    assert "a Saturday" in joined and "2026-05-24" in joined
    assert "a Sunday" in joined and "2026-05-25" in joined
    assert "Memorial Day" in joined and "2026-05-26" in joined
    assert "adds 3 days because service was by mail" in joined
    assert "2026-05-26 + 3 days = 2026-05-29" in joined
    assert calc.warning == deadlines.VERIFY_WARNING
    assert deadlines.VERIFY_WARNING in joined


def test_worked_example_4_roll_after_added_days_shows_every_step():
    calc = deadlines.calculate(
        "frcp-34b2a-document-request-response", datetime.date(2026, 3, 9),
        service_method="mail")
    assert calc.due_date == datetime.date(2026, 4, 13)  # hand result above
    joined = "\n".join(calc.steps)
    assert "2026-03-09 + 30 days = 2026-04-08" in joined
    assert "no roll" in joined  # the Wednesday last day is stated, not silent
    assert "2026-04-08 + 3 days = 2026-04-11" in joined
    assert "a Saturday" in joined and "2026-04-12" in joined
    assert "a Sunday" in joined and "2026-04-13" in joined
    # The check after the added days closes with its own result line.
    assert any("Step 5 result" in step and "2026-04-13" in step
               for step in calc.steps)


def test_no_additional_time_rule_is_stated_not_silent():
    # Worked example 1's rule carries no additional-time rule in its data
    # file, so the steps must say so instead of omitting the question.
    calc = deadlines.calculate(
        "frcp-12a1ai-answer-after-service", datetime.date(2026, 3, 2),
        service_method="personal")
    joined = "\n".join(calc.steps)
    assert "no additional-time rule" in joined
    assert "no days are added" in joined


def test_no_roll_at_first_check_is_stated():
    calc = deadlines.calculate(
        "frcp-12a1ai-answer-after-service", datetime.date(2026, 3, 2),
        service_method="personal")
    assert any("no roll" in step and "2026-03-23" in step
               for step in calc.steps)


# ---------------------------------------------------- warning on surfaces

def test_candidate_dict_carries_the_warning():
    candidate = deadlines.extract_candidates(
        "The defendant shall answer on or before March 23, 2026.")[0]
    assert candidate.to_dict()["warning"] == deadlines.VERIFY_WARNING


def test_confirmed_candidate_row_stores_the_warning(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(
        "The defendant shall answer on or before March 23, 2026.")[0]
    deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                confirmed_by="reviewer")
    row = deadlines.list_deadlines(conn, mid)[0]
    assert deadlines.VERIFY_WARNING in row["calculation_json"]
    record = json.loads(row["calculation_json"])
    assert record["warning"] == deadlines.VERIFY_WARNING


def test_calendar_event_payload_carries_the_warning(tmp_path):
    conn, mid = _setup(tmp_path)
    calc = deadlines.calculate("frcp-12a1ai-answer-after-service",
                               datetime.date(2026, 3, 2))
    deadlines.confirm_calculation(conn, mid, calc, "Answer due",
                                  confirmed_by="reviewer")
    events = deadlines.export_calendar_events(conn, mid)
    assert len(events) == 1
    assert events[0]["warning"] == deadlines.VERIFY_WARNING
    assert deadlines.VERIFY_WARNING in events[0]["description"]


# ------------------------------------------- connected-calendar payload

def test_calendar_event_payload_shape_and_confirmed_only(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(
        "The defendant shall answer on or before March 23, 2026.")[0]
    did = deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                      confirmed_by="reviewer")
    conn.execute("INSERT INTO deadlines (matter_id, due_at, title) "
                 "VALUES (?, '2026-06-01', 'Unverified thing')", (mid,))
    conn.commit()
    events = deadlines.export_calendar_events(conn, mid)
    assert len(events) == 1  # the unverified row never becomes an event
    event = events[0]
    assert event["deadline_id"] == did
    assert event["matter_id"] == mid
    assert event["summary"] == "Answer due"
    assert event["start_date"] == "2026-03-23"
    assert event["end_date"] == "2026-03-24"  # exclusive, all-day event
    assert event["all_day"] is True
    assert event["status"] == "confirmed"
    assert event["uid"] == deadlines.deadlines_to_ics(
        deadlines.list_deadlines(conn, mid)).split("UID:")[1].split("\r\n")[0]


def test_single_unconfirmed_row_refused_as_calendar_event():
    with pytest.raises(ValueError, match="unconfirmed"):
        deadlines.deadline_to_calendar_event(
            {"id": 9, "due_at": "2026-03-23", "title": "Nope",
             "verified": 0, "status": "confirmed"})


def test_calendar_event_description_keeps_calculation_steps(tmp_path):
    conn, mid = _setup(tmp_path)
    calc = deadlines.calculate("frcp-34b2a-document-request-response",
                               datetime.date(2026, 3, 6),
                               service_method="mail")
    deadlines.confirm_calculation(conn, mid, calc, "Responses due",
                                  confirmed_by="reviewer")
    event = deadlines.export_calendar_events(conn, mid)[0]
    assert "2026-04-09" in event["start_date"]
    assert "adds 3 days because service was by mail" in event["description"]
    assert "P. 34" in event["description"]


# ------------------------------------------------- dual entry, all paths

def test_confirm_candidate_caller_can_raise_filing_requirement(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.extract_candidates(
        "The defendant shall answer on or before March 23, 2026.")[0]
    assert not candidate.is_filing
    with pytest.raises(ValueError, match="dual entry"):
        deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                    confirmed_by="first reviewer",
                                    is_filing=True)
    deadlines.confirm_candidate(conn, mid, candidate, "Answer due",
                                confirmed_by="first reviewer",
                                second_confirmer="second reviewer",
                                is_filing=True)
    assert len(deadlines.list_deadlines(conn, mid)) == 1


def test_confirm_candidate_rule_data_can_raise_filing_requirement(tmp_path):
    conn, mid = _setup(tmp_path)
    candidate = deadlines.Candidate(
        excerpt="Motion due May 1, 2026.", kind="explicit_date",
        raw="May 1, 2026", due_date=datetime.date(2026, 5, 1),
        rule_id="frcp-59b-new-trial-motion", is_filing=False)
    with pytest.raises(ValueError, match="dual entry"):
        deadlines.confirm_candidate(conn, mid, candidate, "New trial motion",
                                    confirmed_by="first reviewer")
    deadlines.confirm_candidate(conn, mid, candidate, "New trial motion",
                                confirmed_by="first reviewer",
                                second_confirmer="second reviewer")
    assert len(deadlines.list_deadlines(conn, mid)) == 1


# ------------------------------------------------------ holiday data file

def test_federal_holiday_table_is_data_with_a_source():
    table = deadlines.load_federal_holiday_table()
    assert table["source"]
    entries = table["holidays"]
    assert len(entries) == 11
    names = {entry["name"] for entry in entries}
    assert "Thanksgiving Day" in names and "Juneteenth National Independence Day" in names
    for entry in entries:
        assert entry["kind"] in ("fixed", "nth_weekday", "last_weekday")


def test_federal_holidays_2026_match_the_data_table():
    holidays = deadlines.federal_holidays(2026)
    assert holidays == {
        datetime.date(2026, 1, 1): "New Year's Day",
        datetime.date(2026, 1, 19): "Birthday of Martin Luther King, Jr.",
        datetime.date(2026, 2, 16): "Washington's Birthday",
        datetime.date(2026, 5, 25): "Memorial Day",
        datetime.date(2026, 6, 19): "Juneteenth National Independence Day",
        datetime.date(2026, 7, 4): "Independence Day",
        datetime.date(2026, 9, 7): "Labor Day",
        datetime.date(2026, 10, 12): "Columbus Day",
        datetime.date(2026, 11, 11): "Veterans Day",
        datetime.date(2026, 11, 26): "Thanksgiving Day",
        datetime.date(2026, 12, 25): "Christmas Day",
    }
